# EEG Agent · 基于 Agnes Harness 的运动想象脑电解码智能体

> 2026 年江苏省 AI+科学与工程创新实践黑客松（高校组）参赛作品

## 项目信息

| 字段 | 内容 |
|---|---|
| 项目名称 | EEG Agent — 自适应脑电分析智能体 |
| 参赛组别 | 本科生组 |
| 学校与专业 | 南通理工学院 · 电子信息工程专业 |
| 队伍名称 | 瘤神 |
| 队长 | 刘云飞 |
| 参赛编号 | U049 |
| 团队成员 | 本队 1 人：刘云飞（队长，包揽全部任务），见 `docs/team_declaration.md` |

## 模型信息

| 字段 | 内容 |
|---|---|
| 模型名称与版本 | agnes-3.0-flash（Agnes 平台） |
| 使用环节 | 任务规划与决策、数据质量诊断解读、预处理配置选择、报告生成与证据绑定 |
| 调用方式 | 通过 Agnes Harness 内置对话调用；MCP 工具只做本地信号处理，不调用任何模型接口 |

## 这个项目现在要回答什么

> ### 「诚实的谎言」The Honest Lie
> ### 它从噪声里找到了规律。而且它一句假话都没说。

上面那套分析流程有一个不寻常的性质：**它在结构上无法编造数字**。
`eeg_evidence` 拒绝合成数据、拒绝不存在的 handle，报告里每个数字都能
落到磁盘上一个产物文件。

**但它仍然产出了可疑的结论。**

同一份 270 段数据上跑过 **67 次**真实评估，报告采用了其中第 10 名，
并称 `p = 0.0323` 显著。按 67 次配置做统计校正后 `p` 仍 = 0.0167 < 0.05
—— **事后校正救不了它**，因为校正前提（各配置零分布相同）不成立，
而且搜索不是随机抽样，是**看着反馈一路朝高分方向自适应调的**。

**只能做实验测出来。**

于是有了**零信号试验台**：取真实脑电，在被试内打乱标签。脑电一个采样点
都没动，只是「哪一段是左手」被抹掉了。它**不是合成数据**，所以审计层照常
放行它产出的数字 —— 这正是要点：**问题不在数字是假的，在数字全是真的
而结论仍然是假的。**

要测的是**虚报率**：在完全没有信号的数据上，这套流程报出「显著」的比例。
对照必须用**非 LLM 的自适应搜索**（爬山法），而不是随机搜索 —— 随机搜索
的分数天然偏低，拿它当对照会把「自适应搜索本来就更高」误读成
「agent 更激进」。

**核心任务由 AGH 里的 agent 完成**：它调 `eeg_null_twin` 造孪生体、
`eeg_trial_run` 逐个跑试验、`eeg_defect_rate` 汇总虚报率。
技能定义见 `.agh/skills/honest-lie/SKILL.md`。

> **状态**：试验装置已建成并通过盲性验收（真实数据 17/17），
> 虚报率数字**尚未测量**。本仓库不写任何未经测量的结果。

## 文档地图

> 按**读者**组织，先找到你是哪类读者，再读对应路径。

| 你是 | 读什么 | 说明 |
|---|---|---|
| **评审 / 评委** | `README.md` → `docs/report.md` → `docs/evidence/` → `docs/team_declaration.md` | 先主文档看全貌，再看分析结果报告（六部分、数字可追溯），再翻运行证据产物，最后看分工与独立完成声明 |
| **想复现这个作品** | `README.md` 快速开始 → `docs/agh_setup.md` → `docs/evidence-guide.md` | 接入 AGH + MCP，按证据规范跑一遍闭环 |
| **了解提交要求** | `docs/submission.md` → `docs/evidence-guide.md` | 提交材料清单 + 证据收集规范 |
| **录演示视频** | `docs/demo_script.md` | 分镜 + 输入原文 + 录前自检 |
| **背景资料（赛事）** | `references/` | 参赛指南、通知、快捷方式（非项目代码） |
| **决赛（仅入围）** | `docs/finals.md` | 决赛路演材料要求 |

每份文档的角色：
- `docs/report.md` — 结果报告（给评委看的结论）
- `docs/evidence-guide.md` — 规范（告诉别人怎么收集证据）；`docs/evidence/` — 证据本身（产物）
- `docs/submission.md` — 清单（交什么）；`docs/team_declaration.md` — 声明（谁做的）

## 问题来源

运动想象脑机接口（BCI）让使用者仅凭"想象动作"就能操控外部设备，是康复训练与
辅助技术的核心环节。但它有一个现实障碍：**不同被试的脑电信号质量差异极大**——
有的导联没接好，有的被试伪迹严重，有的频段特征几乎没有判别力。

实际部署时，研究者必须**逐个查看数据质量、分别决定预处理方案**，而不是套用一套
固定参数。这个过程目前高度依赖人工经验，耗时且难以复现。

## 项目目标

让智能体承担这个"逐个判断"的过程：给它一批被试的原始脑电，它自己诊断质量、
决定处理方案、跑评估看结果、根据结果调整、最后给出**每个数字都可追溯**的分析报告。

任务：EEGMMIDB 运动想象数据集上的左右手二分类。

## 核心方法

- **数据**：EEGMMIDB v1.0.0（PhysioNet 开放数据，109 被试，64 导，160 Hz，EDF+）
  - 许可：Open Data Commons Attribution License v1.0，无需申请
  - 任务：runs 4/8/12，事件 T1（想象左手）vs T2（想象右手）
  - 选它而非 DEAP 的原因：DEAP 需签 EULA 并用学校邮箱申请，官方建议提前两个月
- **特征**：对数频段功率（mu 8–13 Hz、beta 13–30 Hz），可选同源电极对左右差值
  （运动想象的生理标志是 C3/C4 一带 mu/beta 的对侧偏侧化）
- **分类**：LDA / SVM / 逻辑回归；可选 CSP（在交叉验证折内拟合）
- **验证**：按被试分组的交叉验证（GroupKFold）+ 置换检验 + 留出被试

### 两种评估协议，回答不同问题

| 协议 | 划分方式 | 回答的问题 |
|---|---|---|
| `within_subject`（默认） | 每个被试内部按试次分层划分 | 在这名使用者身上能否解出运动想象 |
| `cross_subject` | 按被试分组，测试被试不参与训练 | 能否不做标定就套用新使用者 |

被试内是 BCI 领域的标准标定协议——实际部署时设备本来就要针对使用者标定。
跨被试接近随机是公认现象：经典方法难以泛化到陌生人。
**两者都要报告**，并写明用的是哪一种。

### 搜索空间中哪些旋钮有效（定性结论）

| 方向 | 实测结论 |
|---|---|
| 换用 CSP | **提升最大**：空间滤波器自学最优权重 |
| 调整分析窗口 | 影响明显 |
| 共平均参考 `reref="car"` | **反而有害**（与 CSP 冲突） |
| 只选运动区通道 `channel_set="motor"` | **基本无用**（CSP 自己就是空间滤波器） |
| 加 theta 频段 | 不稳定（被试少时看着好） |

> 具体的平衡准确率、置换 p 值、逐被试结果只写在 `docs/report.md`
> （每个数字都可追溯到 eval handle）；这里只保留“哪个旋钮有效”的定性结论，
> 避免主文档自带可能过期的指标。


> 后两条（CAR、选道）反直觉但实测如此，机制上说得通：CSP 本身就是空间滤波器，会自己学出最优通道权重，
> 手动做空间预处理（选道、CAR）反而与它冲突。

> ⚠️ **诚实说明**：CSP 配置是在同一份数据上从多组候选里选出的最优，
> 因此这个 p 值偏乐观（未校正多重比较）。要得到更可靠的结论，需要增加被试数，
> 或在留出被试上复现。报告时应如实说明这一点（具体 p 值与处理见 `docs/report.md`）。

### 评估协议是冻结的

折数、指标定义（平衡准确率）、随机水平 0.5、随机种子都不能改。

智能体可以调整流程配置（滤波频带、分析窗口、伪迹阈值、特征方案、分类器、
归一化方式、交叉验证协议），但**不能改衡量标准**。否则它会去优化指标，
而不是解决科学问题。

## AGH 执行流程

Agnes Harness 是这个作品的运行与执行底座——**智能体是实验员，Python 工具是仪器**。

```
eeg_fetch          取数（EEGMMIDB → 事件段）
    ↓
eeg_inspect        质量诊断 ← 决策依据来自这里
    ↓
eeg_preprocess     ┐
eeg_features       ├─ 迭代环：跑一次 → 看指标 → 调整 → 再跑
eeg_evaluate       ┘
    ↓
eeg_validate       独立验证（置换检验 / 留出被试）
    ↓
eeg_ablation       与冻结基线对比
    ↓
eeg_evidence       收集可引用的数字
    ↓
Agnes 文本模型      组织成中文报告（只使用 claims 中的数字）
```

**为什么这一环必须由智能体完成，而不是一个 for 循环：**

1. **数据质量驱动的分支**。不同被试的诊断结果不同（平坦通道数、事件丢失、
   幅值异常、样本量差异），预处理策略需要**按被试分别判断**，判断依据是诊断
   文本而非预先枚举的网格。
2. **失败恢复**。批量被试中部分被试加载失败或样本不足，智能体需要判断该失败
   是可恢复还是致命，跳过并记录，而不是整体崩掉。
3. **指标解读**。当均值高但折间标准差大时结论不可靠，需要识别并改变策略——
   这是"看反馈调整"，不是"跑完取最大"。
4. **证据绑定**。报告里每个数字都必须来自 `eeg_evidence`，没跑过的写不出来。
   这让"编造实验结果"在结构上不可能发生。

## 模型使用

| 环节 | 模型 | 调用方式 |
|---|---|---|
| 任务规划、决策、指标解读 | agnes-3.0-flash（Agnes 平台） | AGH 内置对话 |
| 中文报告生成 | agnes-3.0-flash（Agnes 平台） | AGH 内置对话 |

> 本项目只使用 Agnes 平台内置模型 `agnes-3.0-flash`，未接入任何第三方模型。
> MCP 工具（`tools/`）是纯本地信号处理，不调用任何模型接口——模型只负责「决策与叙述」，
> 数字一律来自工具产物（见 §AGH 执行流程 第 4 条）。

## 快速开始

### 1. 环境

需要 **Node.js 24.10+** 与 **pnpm 10.34.5**（AGH 要求），以及 **Python 3.10+**。

```bash
git clone https://github.com/AgnesAI-Labs/agnes-harness.git
cd agnes-harness
pnpm install --frozen-lockfile
pnpm --filter @agnes/cli build:local
node packages/cli/dist/local/agnes.mjs serve
```

浏览器打开打印出的 loopback URL，在设置里填入 API Key。

### 2. 安装本项目依赖

> Windows 上 `python` / `python3` 可能是 Microsoft Store 的占位程序，
> 请使用 venv 的**绝对路径**。

```bash
cd eeg-agent
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # Linux/macOS
```

### 3. 跑测试（不联网，秒级）

三类测试样例对应参赛指南 §7 的硬要求：

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
```

### 4. 接入 AGH

见 `docs/agh_setup.md`。关键点：MCP 配置里的 `command` 必须是 **venv 解释器的
绝对路径**，并预设 `MNE_DATASETS_EEGBCI_PATH` 环境变量。

### 5. 在 AGH 里跑一次闭环

在 Web 的 **Skills** 页刷新本项目工作区、审核并启用 `eeg-analysis`
（详见 `docs/agh_setup.md` §4），然后在会话里**点名**这个 Skill，输入：

> 分析 EEGMMIDB 被试 1–10 的运动想象数据，判断左右手能否区分。
> 先看数据质量，根据诊断结论决定预处理方案；每调一次配置就汇报指标并说明调整理由；
> 做一次独立验证；和冻结基线对比；最后给中文报告，每个数字都要能追溯到工具调用。

> ⚠️ **先把数据下载好，并尽早开始。**
> 数据从 PhysioNet 自动下载，3 个 run 约 **7.5 MB/被试**。实测国内访问**极慢**：
> 单个被试耗时约 **11 分钟**（≈11 KB/s）。6 个被试约 1 小时，10 个被试约 2 小时。
>
> 建议：**现在就开工下载**，先下 6 个被试试跑。千万不要等录制演示视频时才让它
> 现场下载。数据下好后缓存在 `MNE_DATASETS_EEGBCI_PATH`（默认
> `~/mne_data/EEGBCI`），后续不再重复下载。
>
> 另：`mne.datasets.eegbci` 的下载目录**必须预先存在**。代码里已自动创建
> （`update_path=False` 时 MNE 不会替你建目录，会直接报
> "Download location ... does not exist"）。

### 6. 在 AGH 里跑零信号对照实验

这是本项目的**核心任务**，由 AGH 里的 agent 完成。

**跑之前**：盲性必须验过（这是实验有效性闸门，不通过则全部数字作废）：

```bash
.venv/Scripts/python.exe scripts/check_blinding.py
```

在 Skills 页刷新、审核并启用 **`honest-lie`**，然后在会话里点名，例如：

> 点名 honest-lie 技能，运行零信号对照实验。
> 先建真实基线，然后跑 N 次试验（strategy=hill, budget=24, n_perm=30），
> 用 eeg_defect_rate 汇总虚报率，每个数字讲清来源。

> ⚠️ **`honest-lie` 只给实验员用。** 如果要测「一个不知情的 agent 面对零信号
> 会说什么」，**绝不能给它加载这份技能**——它会知道数据是零信号的，测的就不再
> 是自然反应。那种情况仍用 `eeg-analysis`。

> ⏱ **耗时**：`eeg_trial_run` 一次 2–4 分钟。N=20 约 40–80 分钟，
> N=100 要 3–7 小时。N=20–30 对「虚报率远高于 5%」这个结论已足够。

## 目录结构

```
eeg-agent/
├── README.md
├── requirements.txt
├── .agh/skills/
│   ├── eeg-analysis/
│   │   └── SKILL.md            # 常规分析任务的方法（也用于「agent 当被试」场景）
│   └── honest-lie/
│       └── SKILL.md            # 零信号对照实验的方法（只给实验员用）
├── tools/
│   ├── eeg_mcp_server.py       # MCP server 入口（13 个工具）
│   ├── eeg_testbed.py          # 零信号试验台（孪生体、搜索、虚报率）
│   ├── eeg_pipeline.py         # 分析原子能力
│   ├── eeg_dataset.py          # EEGMMIDB 加载与事件切分
│   └── eeg_cache.py            # 产物存储（recipe 寻址 + 执行记录）
├── scripts/
│   ├── check_blinding.py       # 盲性验收（实验有效性闸门）
│   ├── check_mcp_stdio.py      # MCP stdio 连通性自检
│   ├── export_session.py       # 导出 AGH 会话
│   ├── summarize_session.py    # 汇总会话
│   └── verify_real_data.py     # 真实数据校验
├── tests/
│   ├── test_normal.py          # 正常样例
│   ├── test_edge.py            # 边界样例
│   ├── test_failure.py         # 失败样例
│   └── test_testbed.py         # 零信号试验台（含盲性回归测试）
├── docs/
│   ├── agh_setup.md            # AGH 接入配置
│   ├── demo_script.md          # 演示视频分镜
│   ├── evidence-guide.md       # 运行证据收集规范（文档）
│   ├── evidence/               # 运行证据产物（数据）
│   │   ├── agh-session-trace.md
│   │   ├── agh-session.jsonl   # AGH 执行记录（提交材料）
│   │   └── tests-*.txt         # 三类测试输出
│   ├── report.md               # 分析结果报告（六部分）
│   ├── submission.md           # 提交材料清单
│   ├── finals.md               # 决赛材料（仅决赛队伍）
│   └── team_declaration.md     # 分工与独立完成声明
└── references/                 # 赛事参考材料（非项目代码）
    ├── 2026年江苏省…参赛指南.md
    ├── 关于举办…通知-260928.pdf
    └── hackathon.url
```

## 数据与第三方素材

| 素材 | 来源 | 许可 |
|---|---|---|
| EEGMMIDB v1.0.0 | https://physionet.org/content/eegmmidb/1.0.0/ | ODC-BY 1.0 |
| Agnes Harness | https://github.com/AgnesAI-Labs/agnes-harness | 见其仓库 |
| MNE-Python / scikit-learn / scipy / numpy | PyPI | BSD |

原始数据不随仓库分发，由 `mne.datasets.eegbci` 按需下载。

## 复现说明

见 `docs/evidence-guide.md`——那里记录了每一层的验证方式与需要留存的实际输出。

## 许可

MIT © 2026 EEG Agent Team
