# EEG Agent · Code Wiki

> 基于 Agnes Harness 的运动想象脑电解码智能体 — 代码架构与开发文档

---

## 目录

1. [项目概述](#1-项目概述)
2. [整体架构](#2-整体架构)
3. [目录结构](#3-目录结构)
4. [核心模块详解](#4-核心模块详解)
5. [关键类与函数](#5-关键类与函数)
6. [MCP 工具清单](#6-mcp-工具清单)
7. [数据流与依赖关系](#7-数据流与依赖关系)
8. [缓存与内容寻址机制](#8-缓存与内容寻址机制)
9. [零信号试验台](#9-零信号试验台)
10. [项目运行方式](#10-项目运行方式)
11. [配置与环境变量](#11-配置与环境变量)
12. [测试体系](#12-测试体系)
13. [Skills 说明](#13-skills-说明)

---

## 1. 项目概述

### 1.1 项目定位

**EEG Agent** 是一个自适应脑电（EEG）运动想象解码智能体，用于 2026 年江苏省 AI+科学与工程创新实践黑客松（高校组）。项目的核心目标不是交付"一个高准确率的脑电分类器"，而是交付**一个可复现的测量**——量化"先挑配置、再报未校正 p 值"这个动作的虚报率（false positive rate）。

### 1.2 核心问题

> "从一堆配置里挑最好的那个，再报数"这个动作本身，会把噪声抬成多少"显著"？

项目通过**四幕实验**回答这个问题：

| 幕 | 名称 | 核心动作 | 关键结果 |
|---|---|---|---|
| 第一幕 | 取证 | 搭建 BCI 解码智能体，跑真实数据分析 | 产出可追溯的分析报告 |
| 第二幕 | 反转 | 智能体审计自己的报告 | 承认"先挑后报"的选择偏差 |
| 第三幕 | 定量 | 零信号试验台机械搜索 | 虚报率 **0.525**（budget=24） |
| 第四幕 | 结案 | 智能体本体直测 | 宽口径 **0.20 → 0.40**，同口径 **0.10 → 0.30** |

### 1.3 技术栈

- **语言**：Python 3.10+
- **核心库**：MNE（EEG 读取/CSP）、NumPy、SciPy、scikit-learn
- **服务框架**：MCP（Model Context Protocol），版本 1.x/2.x 兼容
- **执行底座**：Agnes Harness (AGH) — 智能体运行环境
- **模型**：agnes-3.0-flash（仅用于决策与叙述，不参与信号处理）
- **数据集**：EEGMMIDB v1.0.0（PhysioNet，109 被试，64 导，160 Hz）

---

## 2. 整体架构

### 2.1 设计哲学

```
智能体是实验员，Python 工具是仪器
```

- **智能体（AGH）**：负责任务规划、数据质量诊断解读、预处理配置选择、报告生成与证据绑定
- **MCP 工具（tools/）**：纯本地信号处理，不调用任何模型接口
- **数字一律来自工具产物**，模型只负责"决策与叙述"

### 2.2 分层架构

```
┌─────────────────────────────────────────────────────┐
│                  Agnes Harness (AGH)                │
│         任务规划 · 决策 · 报告生成（agnes-3.0）      │
└───────────────────────┬─────────────────────────────┘
                        │ JSON-RPC (stdio)
┌───────────────────────▼─────────────────────────────┐
│              MCP Server (eeg_mcp_server.py)         │
│         13 个工具 · 统一错误信封 · 异常兜底          │
└───────────────────────┬─────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────┐
│              分析原子能力 (eeg_pipeline.py)          │
│   fetch → inspect → preprocess → features →         │
│   evaluate → validate → ablation → evidence         │
└──────────┬──────────────────────┬───────────────────┘
           │                      │
┌──────────▼──────────┐  ┌────────▼──────────────────┐
│ eeg_dataset.py      │  │ eeg_cache.py              │
│ EEGMMIDB 加载       │  │ 产物存储（recipe 寻址）   │
│ 事件切分            │  │ 血缘追踪 · 内容寻址        │
└─────────────────────┘  └───────────────────────────┘
           │                      │
┌──────────▼──────────────────────▼───────────────────┐
│              eeg_testbed.py (零信号试验台)           │
│   孪生体构造 · 机械搜索 · 虚报率汇总                 │
└─────────────────────────────────────────────────────┘
```

### 2.3 产物类别（Kinds）

所有中间产物通过 handle 引用，共四类：

| Kind | 含义 | 来源工具 |
|---|---|---|
| `raw_*` | 事件段数据（epochs × channels × times） | `eeg_fetch` |
| `clean_*` | 预处理后的事件段 | `eeg_preprocess` |
| `feat_*` | 特征矩阵（epochs × features） | `eeg_features` |
| `eval_*` | 评估结果 | `eeg_evaluate` / `eeg_validate` / `eeg_trial_run` |

---

## 3. 目录结构

```
eeg-agent/
├── README.md                     # 项目主文档（四幕叙事）
├── LICENSE                       # MIT 许可
├── pyproject.toml                # ruff 静态检查配置
├── requirements.txt              # 运行期依赖（下限写法）
├── requirements-lock.txt         # 精确版本快照（复现数字用）
├── requirements-dev.txt          # 开发依赖（ruff）
├── .env.example                  # 环境变量示例
├── .gitignore
│
├── .agh/skills/                  # AGH 技能定义
│   ├── eeg-analysis/
│   │   └── SKILL.md              # 常规分析任务方法（含铁律 5）
│   └── honest-lie/
│       └── SKILL.md              # 零信号对照实验方法
│
├── tools/                        # 核心代码（MCP 工具 + 分析能力）
│   ├── eeg_mcp_server.py         # MCP server 入口（13 个工具）
│   ├── eeg_pipeline.py           # 分析原子能力（核心业务逻辑）
│   ├── eeg_dataset.py            # EEGMMIDB 加载与事件切分
│   ├── eeg_cache.py              # 产物存储（recipe 寻址 + 执行记录）
│   └── eeg_testbed.py            # 零信号试验台
│
├── scripts/                      # 运维/实验脚本
│   ├── check_blinding.py         # 盲性验收（产物面，17 项）
│   ├── check_blinding_act4.py    # 盲性验收（环境面）
│   ├── act4_make_env.py          # 第四幕洁净环境构建
│   ├── act4_prepare.py           # 第四幕逐次准备
│   ├── act4_grade.py             # 第四幕判分
│   ├── act4_mcp_shim.py          # MCP 切换垫片
│   ├── check_mcp_stdio.py        # MCP stdio 连通性自检
│   ├── export_session.py         # 导出 AGH 会话
│   ├── summarize_session.py      # 汇总会话
│   └── verify_real_data.py       # 真实数据校验
│
├── tests/                        # 测试套件
│   ├── test_normal.py            # 正常样例
│   ├── test_edge.py              # 边界样例
│   ├── test_failure.py           # 失败样例
│   ├── test_testbed.py           # 零信号试验台
│   ├── test_act4_grading.py      # 第四幕判分器
│   ├── test_blinding_act4.py     # 环境面闸门
│   ├── test_mcp_envelope.py      # MCP 返回信封
│   ├── test_dataset_tasks.py     # 数据集任务
│   └── test_act4_env_tar.py      # 第四幕环境打包
│
├── docs/                         # 文档与证据
│   ├── showcase.html             # 展示页（单文件）
│   ├── audit.html                # 交互审计页
│   ├── report.md                 # 第一、二幕分析结果
│   ├── zero-signal.md            # 第三、四幕主结论
│   ├── agh_setup.md              # AGH 接入配置
│   ├── runbook-three-acts.md     # 前三幕运行手册
│   ├── runbook-act4.md           # 第四幕运行手册
│   ├── evidence-guide.md         # 证据收集规范
│   └── evidence/                 # 运行证据产物
│
└── references/                   # 赛事背景资料（非代码）
```

---

## 4. 核心模块详解

### 4.1 `tools/eeg_mcp_server.py` — MCP Server 入口

**职责**：将 EEG 分析能力暴露为 13 个 MCP 工具，通过 stdio 与 AGH 通信。

**关键设计**：

1. **stdout 是 JSON-RPC 通道**：任何调试输出必须写 stderr，否则污染协议
2. **统一错误信封**：所有工具失败返回 `{"ok": false, "error": {"code","message","recoverable","suggestions"}}`
3. **成功返回形状不统一**：各工具按用途返回不同顶层键（见 [MCP 工具清单](#6-mcp-工具清单)）
4. **异常兜底**：`_guard()` 将所有异常翻译为结构化错误，绝不泄漏 traceback 到协议通道；内部异常只返回类型名，避免本机路径泄漏

**版本兼容**：同时支持 MCP SDK 1.x（`FastMCP`）和 2.x（`MCPServer`）

**核心函数**：

| 函数 | 作用 |
|---|---|
| `_ok(handle, summary, **extra)` | 构造成功响应 JSON |
| `_err(code, message, suggestions, recoverable)` | 构造错误响应 JSON |
| `_guard(fn)` | 统一异常捕获与翻译 |

---

### 4.2 `tools/eeg_cache.py` — 产物存储（内容寻址）

**职责**：管理所有中间产物的磁盘存储与 handle 寻址。

**为什么需要它**：64 通道 EEG 事件段序列化为 JSON 可达数百 MB，工具间只传短 handle。

**核心机制**：

```
handle = f"{kind}_{hash(recipe)[:12]}"

recipe = {
    "schema": CACHE_SCHEMA,       # 缓存格式版本（破坏性变更时 +1）
    "code_version": code_version(),  # 核心三文件的内容哈希
    "op": kind,                   # 操作类型
    "parents": [...],             # 上游 handle（血缘）
    "params": {...},              # 本次操作参数
    "data": _fingerprint(payload) # 数组内容指纹
}
```

**关键特性**：

1. **确定性**：同输入 + 同参数 → 同 handle → 自动缓存复用
2. **血缘追踪**：`parents` 构成可审计的推导树
3. **代码版本绑定**：`code_version()` 哈希 `eeg_pipeline.py`、`eeg_dataset.py`、`eeg_cache.py` 三个文件，代码改动后旧产物自动失效（`E_HANDLE_STALE`）
4. **内容指纹**：`_fingerprint()` 对数组内容做 SHA-256，防止参数相同但内容不同的数组碰撞
5. **原子写**：先写 `.tmp` 再 `os.replace`，避免并发读到半写文件
6. **执行记录**：`index.jsonl` 追加式记录每次写入，可直接作为运行证据

**产物存放位置**：默认在 `%LOCALAPPDATA%/eeg-agent/artifacts/v{schema}`（仓库外），可用 `EEG_ARTIFACT_DIR` 覆盖。

**核心类与函数**：

| 名称 | 类型 | 作用 |
|---|---|---|
| `CacheError` | 异常类 | 带结构化错误码与恢复建议 |
| `cache_root()` | 函数 | 返回产物目录 |
| `code_version()` | 函数 | 核心三文件内容哈希（前 12 位） |
| `put(kind, arrays, meta, parents, params)` | 函数 | 写入产物并返回 handle |
| `get(handle)` | 函数 | 读取数组与记录 |
| `describe(handle)` | 函数 | 只读元信息，不加载数组 |
| `exists(handle)` | 函数 | 检查 handle 是否有效 |
| `list_recent(kind, limit)` | 函数 | 列出最近产物（错误恢复用） |
| `clear()` | 函数 | 清空全部产物 |

**错误码**：

| 错误码 | 含义 |
|---|---|
| `E_INVALID_HANDLE` | handle 格式非法 |
| `E_HANDLE_NOT_FOUND` | handle 不存在 |
| `E_HANDLE_STALE` | handle 由旧版本代码/格式生成 |
| `E_BAD_KIND` | 未知产物类别 |

---

### 4.3 `tools/eeg_pipeline.py` — 分析原子能力

**职责**：实现 EEG 分析的完整流水线，是核心业务逻辑所在。

**与原版的六处关键差别**：

1. **不硬编码采样率**：从产物元信息取 `sfreq`（EEGMMIDB 是 160 Hz，非 250 Hz）
2. **单位不盲**：伪迹阈值参数名直接写 `reject_uv`（微伏），内部换算为伏特比较
3. **按被试分组**：跨被试用 `GroupKFold`，避免训练集含测试被试样本
4. **产物落盘**：步骤间传 handle，不把数组序列化进模型上下文
5. **参数交给 agent**：滤波带宽、窗口、伪迹阈值、特征方案、分类器都不写死
6. **没有合成数据回退**：输入缺失一律报错，不静默改用合成数据

**流水线函数**：

| 函数 | 输入 | 输出 | 作用 |
|---|---|---|---|
| `fetch(subjects, task, runs)` | — | `raw_*` | 加载 EEGMMIDB 并切事件段 |
| `inspect(handle)` | `raw/clean/feat/eval` | dict | 元信息 + 质量诊断 |
| `preprocess(handle, ...)` | `raw_*` | `clean_*` | 裁剪/选道/陷波/带通/重参考/伪迹剔除 |
| `features(handle, feature_set, bands, normalize)` | `clean_*` | `feat_*` | 频段功率特征提取 |
| `evaluate(handle, model, use_csp, cv_folds, cv_scheme)` | `clean_*/feat_*` | `eval_*` | 交叉验证评估 |
| `validate(handle, scheme, ...)` | `clean_*/feat_*` | `eval_*` | 置换检验/留出被试 |
| `ablation(agent_eval_handle)` | `eval_*` | dict | 与冻结基线对比 |
| `evidence(eval_handles)` | `eval_*` 列表 | dict | 收集可写入报告的数字 |
| `provenance_raw(handle)` | 任意 | `raw_*` | 沿血缘回溯到原始数据 |

**冻结基线配置（BASELINE）**：

```python
BASELINE = {
    "name": "baseline_bandpower_lda",
    "low_hz": 8.0, "high_hz": 30.0,
    "crop_sec": [0.5, 3.5], "reject_uv": None,
    "channel_set": "all", "reref": "none",
    "feature_set": "bandpower", "bands": ["mu", "beta"],
    "normalize": "subject", "model": "lda",
    "use_csp": False, "cv_folds": 5, "cv_scheme": "within_subject",
}
```

**两种交叉验证协议**：

| 协议 | 划分方式 | 回答的问题 |
|---|---|---|
| `within_subject`（默认） | 每个被试内部按试次分层划分 | 在该使用者身上能否解出运动想象 |
| `cross_subject` | 按被试分组（GroupKFold），测试被试不参与训练 | 能否不做标定就套用新使用者 |

**频段定义**：

| 频段 | 范围 (Hz) |
|---|---|
| delta | 0.5 – 4.0 |
| theta | 4.0 – 8.0 |
| mu / alpha | 8.0 – 13.0 |
| beta | 13.0 – 30.0 |
| gamma | 30.0 – 45.0 |

---

### 4.4 `tools/eeg_dataset.py` — EEGMMIDB 加载与事件切分

**职责**：从 PhysioNet 下载 EEGMMIDB 数据集并切分为事件段。

**数据集信息**：
- EEG Motor Movement/Imagery Dataset, v1.0.0
- 109 名被试 · 64 导 EEG · 160 Hz · EDF+
- 许可：Open Data Commons Attribution License v1.0

**Run 家族**（T1/T2 在不同家族含义不同，不可混用）：

| 家族 | Runs | T1 | T2 |
|---|---|---|---|
| hands_execution | 3, 7, 11 | 左手 | 右手 |
| hands_imagery | 4, 8, 12 | 左手 | 右手 |
| feet_execution | 5, 9, 13 | 双手 | 双脚 |
| feet_imagery | 6, 10, 14 | 双手 | 双脚 |

**支持的任务**：

| 任务名 | 说明 |
|---|---|
| `left_vs_right_imagery`（默认） | 想象左手 vs 想象右手 |
| `fists_vs_feet_imagery` | 想象双手 vs 想象双脚 |
| `left_vs_right_movement` | 实际左手 vs 实际右手 |

**核心函数**：

| 函数 | 作用 |
|---|---|
| `load(subjects, task, runs, verbose)` | 加载多被试并拼接 |
| `synthetic(n_subjects, n_trials, ...)` | 合成数据（仅供测试） |
| `resolve_task(runs, task)` | 解析任务定义，拒绝跨家族混用 |
| `family_of_runs(runs)` | 判断 run 所属家族 |

**容错设计**：单个被试加载失败不中断整体，失败记录在 `failures` 中。

**加载参数**：
- `LOAD_TMIN = -0.2`, `LOAD_TMAX = 4.0`（保留宽窗口，分析窗口由预处理裁剪）
- `DEFAULT_SUBJECTS = list(range(1, 11))`（默认 1–10 号被试）
- `EXPECTED_N_CHANNELS = 64`

---

### 4.5 `tools/eeg_testbed.py` — 零信号试验台

**职责**：构造与真实数据 API 表面无法区分的"零信号孪生体"，测量流程在无信号数据上的虚报率。

**核心概念**：

- **零信号孪生体**：取真实 `raw_*`，在每个被试内部打乱标签。脑电信号一个采样点都不动，只是"哪段是左手"的信息被抹掉
- **盲性保证**：靠逐字节同构——meta/params 原样复制，血缘不指向真品，身份只记在产物目录外的旁路台账

**核心类与函数**：

| 名称 | 类型 | 作用 |
|---|---|---|
| `testbed_code_version()` | 函数 | 本模块内容哈希（试验装置身份，不进 handle 配方） |
| `make_twin(source_handle, seed, scheme)` | 函数 | 从真实 raw 造零信号孪生体 |
| `rewind_labels(handle, seed)` | 函数 | 对 clean/feat 表示重贴标签（性能优化） |
| `Testbed` | 类 | 试验台主体：表示缓存、搜索、评分 |
| `run_trial(source_raw, seed, strategy, budget, n_perm)` | 函数 | 跑一次完整搜索试验 |
| `defect_rate(trials, alpha)` | 函数 | 汇总虚报率 |
| `analytical_baseline(budget, n_perm)` | 函数 | 理论对照线 B/(B+n_perm) |
| `search_random()` / `search_hill()` | 函数 | 两种搜索策略 |

**搜索空间**（5 个旋钮，72 个配置）：

| 参数 | 可选值 |
|---|---|
| `crop_sec` | [0.5, 3.5] / [1.0, 4.0] / [0.0, 4.0] |
| `reject_uv` | None / 150.0 / 200.0 |
| `channel_set` | all / motor |
| `reref` | none / car |
| `use_csp` | False / True |

**版本归属设计**：试验台版本不并进 `cache.code_version()`（否则全库既有 handle 失效），而是通过三条平行路径管理：
1. 试验产物 meta 里记 `testbed_code_version`
2. 零分布缓存文件带版本，版本不符即整份作废
3. `defect_rate()` 拒绝汇总混合版本的批次

---

## 5. 关键类与函数

### 5.1 `eeg_cache.CacheError`

```python
class CacheError(Exception):
    def __init__(self, code, message, suggestions=None, recoverable=True):
        ...
    def as_dict(self) -> dict  # 转为 MCP 错误信封
```

带结构化错误码的异常，贯穿整个缓存层与流水线。

### 5.2 `eeg_testbed.Testbed`

试验台主体类，负责：
- `stage()`：复制源 raw 到试验台目录
- `prepare()`：对每个预处理组合算一次 clean/feat 表示（唯一重活，只做一次）
- `_representations(seed)`：把全部预计算表示重贴标签
- `_representation_for(cfg, seed)`：只重贴单个配置所需的表示
- `score(cfg, reps)`：在给定孪生体标签下评估一个配置

### 5.3 `eeg_pipeline` 核心评估函数

#### `_run_cv(X, y, subjects, model, use_csp, cv_folds, scheme)`

按指定协议做交叉验证，返回指标字典。

**被试内协议**（within_subject）：
- 每个被试内部用 `StratifiedKFold` 分层划分
- 折数自动压到该被试能支持的最大值
- 最终按被试汇总平衡准确率

**跨被试协议**（cross_subject）：
- 用 `GroupKFold(n_splits=cv_folds)` 按被试分组
- 测试被试完全不参与训练

#### `_estimator(model, use_csp, n_channels)`

构造 sklearn Pipeline：
- 非 CSP：`StandardScaler` + 分类器
- CSP：`mne.decoding.CSP` + 分类器（CSP 在折内拟合，不泄漏）

支持的模型：`lda`、`svm`（RBF）、`logreg`

### 5.4 `eeg_pipeline.validate()` — 三种验证方案

| scheme | 作用 |
|---|---|
| `shuffle_control` | 打乱标签重跑交叉验证，得到置换 p 值 |
| `shuffle_control_combine` | 合并多批置换结果（解决单次调用预算限制） |
| `holdout_subject` | 留出指定被试做独立验证 |

### 5.5 `eeg_pipeline.evidence()` — 证据收集

**结构性约束**：报告里出现的每一个数字都必须能在返回的 `claims` 中找到。基于合成数据的评估会被自动拒绝。

返回结构：
```python
{
    "ok": True,
    "claims": [{"id": "C1", "key": "...", "value": ..., "source": {...}, "config": {...}}],
    "provenance": [{"raw_handle": ..., "dataset": ..., ...}],
    "refused": [{"handle": ..., "reason": ...}],
    "rule": "报告中的每一个数值都必须能在 claims 中找到..."
}
```

---

## 6. MCP 工具清单

### 6.1 正常分析链（9 个工具）

| 工具 | 输入 | 输出 handle | 作用 |
|---|---|---|---|
| `eeg_fetch` | subjects, task, runs | `raw_*` | 下载并切分 EEG 事件段 |
| `eeg_inspect` | handle | — | 查看元信息与质量诊断 |
| `eeg_preprocess` | handle, low_hz, high_hz, notch_hz, crop_sec, reject_uv, drop_channels, channel_set, reref | `clean_*` | 滤波/裁剪/剔伪迹 |
| `eeg_features` | handle, feature_set, bands, normalize | `feat_*` | 提取频段功率特征 |
| `eeg_evaluate` | handle, model, use_csp, cv_folds, cv_scheme | `eval_*` | 交叉验证评估 |
| `eeg_validate` | handle, scheme, test_subjects, model, use_csp, cv_folds, n_permutations, cv_scheme, seed, batch_handles | `eval_*` | 置换检验/留出被试 |
| `eeg_ablation` | agent_eval_handle | — | 与冻结基线对比 |
| `eeg_evidence` | eval_handles | — | 收集可写入报告的数字 |
| `eeg_artifacts` | kind, limit | — | 列出现有产物 handle |

### 6.2 零信号试验台（3 个工具）

| 工具 | 输入 | 输出 | 作用 |
|---|---|---|---|
| `eeg_null_twin` | source_handle, seed, scheme | `raw_*` | 造零信号孪生体 |
| `eeg_trial_run` | source_handle, seed, strategy, budget, n_perm | `eval_*` | 跑一次完整搜索试验 |
| `eeg_defect_rate` | trial_handles, alpha | — | 汇总虚报率 |

### 6.3 工具链自检（1 个工具）

| 工具 | 输入 | 作用 |
|---|---|---|
| `eeg_load_synthetic` | n_subjects, n_trials | 载入合成数据，仅用于验证工具链连通性 |

> **注意**：合成数据产物带 `is_synthetic=True`，`eeg_evidence` 会拒绝引用，因此不可能悄悄进入正式结论。

### 6.4 返回值约定

**失败**（13 个工具统一）：
```json
{"ok": false, "error": {"code": "...", "message": "...", "recoverable": true, "suggestions": [...]}}
```

**成功**（各工具形状不同，不假设统一）：

| 工具 | 成功时顶层键 |
|---|---|
| `eeg_fetch`/`eeg_preprocess`/`eeg_features`/`eeg_evaluate`/`eeg_validate`/`eeg_null_twin` | `ok`, `handle`, `summary` (+`next_step`/`note`) |
| `eeg_trial_run`/`eeg_load_synthetic` | `ok`, `handle`, `summary` (+`next_step`/`warning`) |
| `eeg_artifacts` | `ok`, `summary`, `cache_dir`, `index`（无 `handle`） |
| `eeg_defect_rate` | `ok`, `summary`, `note`, `refused`（无 `handle`） |
| `eeg_ablation` | `ok`, `baseline`, `agent`, `delta_balanced_accuracy`, `fairness`, `verdict` |
| `eeg_evidence` | `ok`, `claims`, `provenance`, `refused`, `rule` |
| `eeg_inspect` | `handle`, `kind`, `healthy`, `warnings`, ...（连 `ok` 都没有） |

---

## 7. 数据流与依赖关系

### 7.1 模块依赖图

```
eeg_mcp_server.py
    ├── eeg_pipeline.py
    │       ├── eeg_cache.py
    │       └── eeg_dataset.py
    └── eeg_testbed.py  (延迟导入，仅试验台工具)
            └── eeg_cache.py
```

**延迟导入说明**：`eeg_testbed` 仅在 `eeg_null_twin`、`eeg_trial_run`、`eeg_defect_rate` 三个工具内延迟导入，避免主分析链不必要地加载试验台代码。

### 7.2 分析流水线数据流

```
eeg_fetch ──→ raw_* ──→ eeg_inspect (诊断)
                    │
                    ▼
            eeg_preprocess ──→ clean_*
                    │
                    ├────→ eeg_features ──→ feat_* ──→ eeg_evaluate (use_csp=False)
                    │                                    │
                    └────→ eeg_evaluate (use_csp=True)  │
                                                         ▼
                                                    eval_* ──→ eeg_validate
                                                              │
                                                              ├─→ eeg_ablation
                                                              └─→ eeg_evidence ──→ 报告
```

### 7.3 零信号试验数据流

```
真实 raw_* ──→ make_twin(seed) ──→ 孪生 raw_* (盲性保证)
                    │
                    ▼
            Testbed.prepare() ──→ 预计算 clean/feat 表示 (36 组合，只算一次)
                    │
                    ▼
            run_trial(seed, strategy, budget):
                1. _representations(seed) — 全部表示重贴标签
                2. search() — 爬山/随机搜索 budget 个配置
                3. null_pool() — 该配置的置换零分布 (全局缓存)
                4. emulate_p_value() — 计算 p 值
                5. 落成 eval_* 产物 (scheme="zero_signal_trial")
                    │
                    ▼
            eeg_defect_rate(trial_handles) — 汇总虚报率
```

---

## 8. 缓存与内容寻址机制

### 8.1 Handle 生成公式

```python
recipe = {
    "schema": CACHE_SCHEMA,           # = 1
    "code_version": code_version(),   # eeg_pipeline/dataset/cache 三文件哈希
    "op": kind,                       # raw/clean/feat/eval
    "parents": [上游 handle 列表],
    "params": {操作参数},
    "data": _fingerprint(数组内容),    # SHA-256 前 16 位
}
handle = f"{kind}_{sha256(recipe)[:12]}"
```

### 8.2 Handle 校验阶梯

`_validate(handle)` 依次检查：
1. **格式**：`HANDLE_RE = r"^(raw|clean|feat|eval)_[0-9a-f]{12}$"`
2. **存在**：`.json` 和 `.npz` 文件都存在
3. **schema**：`record["schema"] == CACHE_SCHEMA`
4. **code_version**：`record["code_version"] == code_version()`

任一失败抛出对应 `CacheError`。

### 8.3 产物文件结构

每个 handle 对应两个文件：
- `{handle}.npz`：NumPy 数组（`np.savez`，不压缩）
- `{handle}.json`：元信息记录（含 meta、params、parents、data_fingerprint 等）

另有 `index.jsonl`：追加式执行记录，每次 `put()` 追加一行。

### 8.4 代码版本机制

```python
def code_version() -> str:
    h = hashlib.sha256()
    for name in ("eeg_pipeline.py", "eeg_dataset.py", "eeg_cache.py"):
        h.update(name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]
```

**为什么只哈希这三个文件**：它们是分析链的核心，改动会影响计算结果。`eeg_mcp_server.py` 和 `eeg_testbed.py` 不参与此哈希：
- `eeg_mcp_server.py`：只做协议封装，改动不影响计算结果
- `eeg_testbed.py`：试验装置，有独立的 `testbed_code_version()` 机制

### 8.5 依赖版本锁定

`code_version()` 只哈希源码，不含库版本。因此：
- `requirements.txt`：下限写法，用于"能跑起来"
- `requirements-lock.txt`：`pip freeze` 精确快照，用于"逐位复现数字"

---

## 9. 零信号试验台

### 9.1 设计目标

测量"从 B 个配置里挑最好的再报数"这个动作在零信号数据上的虚报率。

### 9.2 孪生体盲性保证（三条结构性性质）

1. **内容指纹**：打乱 `y` 后 `X` 不变、`y` 变了 → 指纹变 → 自动得到新的合法 `raw_*` handle
2. **meta/params 原样复制**：`eeg_inspect` 回显的每一个字段与真品完全相同
3. **`parents=()`**：血缘不指向真品，溯源报出 EEGMMIDB

孪生体身份只写在产物目录外的 `manifest.jsonl`，agent 无任何工具能读到。

### 9.3 性能优化

**表示层复用**：`preprocess()` 与 `features()` 都不使用标签，所以同一份 X 的 clean/feat 表示对所有孪生体相同，只需算一次。每个孪生体独有的只有标签（`rewind_labels`）。

**零分布全局缓存**：被置换过的标签再打乱仍是均匀置换，所以配置 c 的零分布只依赖"数据 X"和"配置 c"，不依赖具体孪生体。全局只需算一次，所有孪生体共用。

### 9.4 两种搜索策略

| 策略 | 说明 |
|---|---|
| `hill`（爬山法） | 朝高分方向走，局部最优时随机重启 |
| `random`（随机搜索） | 从池中不重复抽取 budget 个 |

**实测结论**：在零信号数据上，两种策略无可辨别差别（零信号下所有配置期望值都是 0.5，不存在"烂配置"供自适应利用）。

### 9.5 理论对照线

```python
analytical_baseline = budget / (budget + n_perm)
```

推导：搜索取 B 次抽样的最大值，置换检验拿它与同一分布下的 n_perm 次抽样比较。"B 次抽样的最大值超过那 n_perm 次"等价于"全部 B+n_perm 次抽样中最大的那次落在前 B 次里"，概率即 B/(B+n_perm)。

### 9.6 虚报率汇总

`defect_rate()` 返回：
- `n_trials`：试验总数
- `n_significant`：显著次数（p < alpha）
- `defect_rate`：虚报率 = k/n
- `wilson_ci95`：Wilson 95% 置信区间
- `p_values`：所有 p 值（排序）
- `observed_mean/std/min/max`：观测平衡准确率统计

---

## 10. 项目运行方式

### 10.1 环境要求

- **Node.js** 24.10+ 与 **pnpm** 10.34.5（AGH 要求）
- **Python** 3.10+

### 10.2 安装步骤

```bash
# 1. 克隆并安装 AGH
git clone https://github.com/AgnesAI-Labs/agnes-harness.git
cd agnes-harness
pnpm install --frozen-lockfile
pnpm --filter @agnes/cli build:local
node packages/cli/dist/local/agnes.mjs serve

# 2. 安装本项目依赖（复现数字请用锁文件）
cd eeg-agent
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt  # 精确版本
# 或：.venv/bin/python -m pip install -r requirements.txt  # 下限写法

# 3. 跑测试
.venv/bin/python -m pytest tests/ -q

# 4. 接入 AGH（配置 MCP command 为 venv 解释器绝对路径）
# 详见 docs/agh_setup.md

# 5. 准备数据（首次下载较慢，约 11 分钟/被试）
# 数据缓存在 MNE_DATASETS_EEGBCI_PATH
```

### 10.3 运行 MCP Server

```bash
.venv/bin/python tools/eeg_mcp_server.py
```

启动后通过 stdio 与 AGH 通信，不监听端口。

### 10.4 四幕实验运行

详细提示词与步骤见：
- `docs/runbook-three-acts.md`（第一至三幕）
- `docs/runbook-act4.md`（第四幕）

**概览**：

| 阶段 | 在哪跑 | 关键动作 | 预期时长 |
|---|---|---|---|
| 前置自检 | IDE 终端 + AGH | 数据缓存、盲性 17/17、pytest 全绿、MCP 13 工具 | 首次约 1h |
| 第一幕 | 主仓库 AGH | 点名 `eeg-analysis`，贴 P1 | 10–13 min |
| 第二幕 | 同一会话 | 贴 P2（审计报告） | 1–2 min |
| 第三幕 | 同一会话 | 点名 `honest-lie`，贴 P3a→P3d | 2–3 h |
| 第四幕 | 洁净环境 | 逐次 `act4_prepare` + P1 变体 | 2–3 h |

### 10.5 盲性闸门（实验有效性前置条件）

```bash
# 产物面盲性（必须 17/17）
.venv/bin/python scripts/check_blinding.py

# 环境面盲性（第四幕）
.venv/bin/python scripts/check_blinding_act4.py --env <洁净环境> --ledger <台账>
```

---

## 11. 配置与环境变量

### 11.1 环境变量

| 变量 | 作用 | 默认值 |
|---|---|---|
| `EEG_ARTIFACT_DIR` | 产物缓存目录 | `%LOCALAPPDATA%/eeg-agent/artifacts` |
| `EEG_TESTBED_DIR` | 试验台簿记目录 | `%LOCALAPPDATA%/eeg-agent/testbed` |
| `MNE_DATASETS_EEGBCI_PATH` | EEGMMIDB 数据目录 | `~/mne_data/EEGBCI` |
| `MNE_DATA` | MNE 数据根目录 | `~/mne_data` |
| `AGNES_API_KEY` | Agnes 平台 API Key | —（AGH 侧使用） |
| `AGNES_BASE_URL` | Agnes API 地址 | `https://api.agnes-ai.cn/v1` |
| `AGNES_TEXT_MODEL` | 文本模型名 | `agnes-3.0-flash` |

### 11.2 ruff 配置（pyproject.toml）

```toml
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "UP", "B", "SIM", "RUF"]
ignore = ["E501", "RUF001", "RUF002", "RUF003", "RUF046"]
```

**特殊豁免**（保护产物稳定性）：

| 文件 | 豁免规则 | 原因 |
|---|---|---|
| `tools/eeg_cache.py` | UP035 | 参与 `code_version()` 哈希，改字节会让所有 handle 失效 |
| `tools/eeg_dataset.py` | F401, RUF100 | 同上 |
| `tools/eeg_pipeline.py` | B905, RUF059, RUF005, B007 | 同上 |

---

## 12. 测试体系

### 12.1 测试文件

| 文件 | 覆盖范围 |
|---|---|
| `test_normal.py` | 正常流程样例 |
| `test_edge.py` | 边界条件样例 |
| `test_failure.py` | 失败场景与错误恢复 |
| `test_testbed.py` | 零信号试验台（含盲性回归 + 版本闸门） |
| `test_act4_grading.py` | 第四幕判分器各判定路径 |
| `test_blinding_act4.py` | 环境面闸门（会话键中性/唯一） |
| `test_mcp_envelope.py` | MCP 返回信封形状核对 |
| `test_dataset_tasks.py` | 数据集任务解析与 run 家族校验 |
| `test_act4_env_tar.py` | 第四幕环境打包 |

### 12.2 运行测试

```bash
.venv/bin/python -m pytest tests/ -q
```

实测 **119 passed**，对应参赛指南 §7 的硬要求。

### 12.3 测试设计原则

- 测试函数名刻意用中文（可读性远胜英文名），因此不启用 `PL*` 系列规则
- 合成数据（`eeg_dataset.synthetic()`）仅供测试，不用于任何结果汇报
- `test_mcp_envelope.py` 逐格核对 13 个工具的成功返回形状

---

## 13. Skills 说明

### 13.1 `.agh/skills/eeg-analysis/SKILL.md`

常规分析任务的方法定义，含铁律 5 条：

1. **报告里的每一个数字都必须来自 `eeg_evidence` 的返回**
2. **评估协议是冻结的**（折数、指标定义、随机水平、随机种子不能改）
3. **报告里必须写明用的是哪种交叉验证协议**
4. **合成数据的任何结果都不得进入结论**
5. **报告 p 值前，必须先声明本次搜索过的配置数**（第三幕结论回填）

### 13.2 `.agh/skills/honest-lie/SKILL.md`

零信号对照实验的方法定义，只给实验员用。指导 agent 驱动 `eeg_trial_run` 逐个跑试验、`eeg_defect_rate` 汇总虚报率。

---

## 附录 A：错误码速查表

| 错误码 | 来源 | 含义 | recoverable |
|---|---|---|---|
| `E_INVALID_HANDLE` | cache | handle 格式非法 | False |
| `E_HANDLE_NOT_FOUND` | cache | handle 不存在 | True |
| `E_HANDLE_STALE` | cache | 旧版本代码/格式生成 | True |
| `E_BAD_KIND` | cache | 未知产物类别 | False |
| `E_BAD_INPUT_KIND` | pipeline | 输入类型不对 | False |
| `E_BAD_ARGUMENT` | mcp_server | 参数非法 | False |
| `E_FILE_NOT_FOUND` | mcp_server | 文件不存在 | True |
| `E_OUT_OF_MEMORY` | mcp_server | 内存不足 | True |
| `E_INTERNAL` | mcp_server | 内部异常（兜底） | True |
| `E_MISSING_LINEAGE` | pipeline | 无法回溯到原始数据 | — |
| `E_MIXED_TESTBED_VERSION` | testbed | 混合版本试验台批次 | False |

## 附录 B：关键常量速查

| 常量 | 值 | 位置 |
|---|---|---|
| `CACHE_SCHEMA` | 1 | eeg_cache.py |
| `DEFAULT_TASK` | `"left_vs_right_imagery"` | eeg_dataset.py |
| `EXPECTED_N_CHANNELS` | 64 | eeg_dataset.py |
| `LOAD_TMIN` / `LOAD_TMAX` | -0.2 / 4.0 | eeg_dataset.py |
| `DEFAULT_SUBJECTS` | range(1, 11) | eeg_dataset.py |
| `EVENT_T1` / `EVENT_T2` | 2 / 3 | eeg_dataset.py |
| `HANDLE_RE` | `^(raw\|clean\|feat\|eval)_[0-9a-f]{12}$` | eeg_cache.py |
| `BANDS` | delta/theta/mu/beta/gamma | eeg_pipeline.py |
| `BASELINE` | bandpower + LDA + 8-30Hz | eeg_pipeline.py |
| `CONFIG_POOL` | 72 个配置 | eeg_testbed.py |
