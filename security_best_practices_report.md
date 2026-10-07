# 终极审验报告 · Final Audit

> 审验对象：`D:\暂存\source`（EEG Agent · 零信号试验台）
> 审验日期：2026-10-04 · 代码版本 `20b202c7ffe4`
> 报告人：安全审计 + 代码质量评审（自动化审验）
> **本报告只记录可复现、可定位的问题。无法证实的标「需人工确认」。**

---

## 〇、范围发现（先查仓库，再下结论）

### 0.1 语言与核心框架（附判定依据）

| 层 | 语言 / 框架 | 判定依据 |
|---|---|---|
| **后端** | **Python 3.12** + **MCP Python SDK**（stdio 传输） | [`requirements.txt`](requirements.txt)（`mcp>=1.2`）；已装 `mcp==2.2.0`；[`tools/eeg_mcp_server.py`](tools/eeg_mcp_server.py) 用 `@mcp.tool()` 注册 13 个工具 |
| 计算栈 | numpy / scipy / scikit-learn / mne | [`requirements.txt`](requirements.txt)；实装 numpy 2.5.3 · scipy 1.18.1 · sklearn 1.9.1 · mne 1.13.2 |
| **前端** | **无框架**，两个自包含静态 HTML（内联 CSS/JS） | [`docs/showcase.html`](docs/showcase.html) · [`docs/audit.html`](docs/audit.html)；`grep` 不到 React/Vue/webpack，无 `node_modules`、无 `package.json` |
| 静态检查 | ruff | [`pyproject.toml`](pyproject.toml)；实装 ruff 0.16.10 |
| 测试 | pytest | [`requirements.txt`](requirements.txt)；实装 pytest 9.1.1 |

**本仓库内没有 TypeScript/PowerShell 源码**。第四幕的无人值守 runner（`run-act4.ts`）与
`agh_unattended.ps1` 位于**仓库之外**（`D:\AI-tools\agnes-harness-main`、`D:\暂存\`），
属支撑设施，本报告在 §3 SEC-008 单独记一条。

### 0.2 对外入口与用户可控输入

| 入口 | 位置 | 用户可控输入 | 备注 |
|---|---|---|---|
| **MCP stdio 服务**（唯一常驻服务） | [`tools/eeg_mcp_server.py`](tools/eeg_mcp_server.py) 13 个工具 | **工具参数全部可控**（调用方是 LLM agent） | 无网络监听、无端口 |
| CLI 脚本 | [`scripts/`](scripts/) 10 个（argparse） | `--env` `--ledger` `--runs` `--data` 等路径与编号 | 操作者本机执行 |
| 静态页 | [`docs/*.html`](docs/) | 一个搜索框（本地过滤，见 §4 已验证项） | 无表单提交、无外部资源 |
| 数据下载 | [`tools/eeg_dataset.py:158`](tools/eeg_dataset.py) `eegbci.load_data` | `subjects`/`runs`（来自工具参数） | 目标 URL 固定为 PhysioNet，**非用户可控** |

**没有**：HTTP 路由、消息队列、定时任务、WebSocket、文件上传、数据库、认证/会话。

### 0.3 依赖 / 配置 / CI / 部署

- 依赖：[`requirements.txt`](requirements.txt)（下限）+ [`requirements-lock.txt`](requirements-lock.txt)（精确快照，见 §5 偏离记录）
- 配置：[`.env.example`](.env.example)，**实际 `.env` 不存在**（已确认）
- **无 CI**（无 `.github/`）、**无 Dockerfile / docker-compose**、**无 Makefile**
- 部署脚本：无（本项目是本地运行的分析工具，不是服务）

---

## 一、基线加载情况（**必须说明**）

**任务指定的基线文件不存在。** 按约定命名查找 `<language>-<framework>-<stack>-security.md`
与 `<language>-general-<stack>-security.md`：在仓库内、`~/.claude/` 下均**未找到**
（`~/.claude/skills/` 只有 `qiuzhi-skill-creator`）。

**因此本审验基于通用安全最佳实践 + 该栈的公认风险面**（Python 反序列化、子进程、
路径拼接、MCP 工具边界、静态页 DOM XSS）。**这是本次审验的一处局限，如实标注。**

---

## 二、执行摘要

**结论：没有 Critical，也没有 High。** 这是审验后的判断，不是没查。

**为什么**：本项目的攻击面极小——它**没有网络服务、没有数据库、没有认证、没有用户数据**。
唯一常驻进程是一个 **stdio MCP server**，其调用方是设计上就受信任的本机 LLM agent。
最常被利用的几类漏洞（注入、越权、会话、SSRF、上传）在本架构下**结构性不存在**。

真正值得处理的是**工程质量与纵深防御**层面的问题，共 **13 条**：Medium 3 · Low 10。
（**SEC-002 / SEC-003 / SEC-004 / SEC-011 已修复，SEC-005 部分修复**；
SEC-011 / SEC-012 / SEC-013 都是修复过程中新发现的，其中 **SEC-013 由本报告作者自己触发**。）

### 最需立刻处理的 3 件事

| # | 事项 | 为什么排最前 |
|---|---|---|
| **1** | **~~SEC-003 · 给「家族混用守卫」与「第三幕核心测量路径」补测试~~** ✅ **已完成** | 这是**正确性**风险，不是风格问题：`resolve_task` 守的是「把不同 run 家族混在一起会让标签**静默变成错的**」，而它零测试；`run_trial` 是整个第三幕数字的来源，也零测试。改动零风险、收益最高。**已实施：73 → 97 passed，未改任何被测代码** |
| **2** | **~~SEC-002 · 校验 handle 之后再拼文件路径~~** ✅ **已完成** | 3 行改动。修复前**不可达**（上游先校验并抛错），但这是一处**纵深防御缺口**：一旦有人调整调用顺序，它就变成真实的路径穿越。**已实施：97 → 108 passed，对外行为零变化，`code_version` 未动** |
| **3** | **SEC-001 · 产物 `.json` 记录的非原子写** | 产物库是整个项目的**证据基础**，并发下可能读到半截文件。**但它有个硬约束**：`eeg_cache.py` 参与 `code_version()` 哈希，改一个字节就作废**全部既有 handle**——所以必须先做「接受并文档化」还是「重跑全部实验」的决定 |

**另有 5 分钟可清的**：~~SEC-004（删掉冗余的 `pandas` 依赖）~~ ✅ **已完成**
（实测「完全没装」时 sklearn / mne / 真实 EDF 加载 / 全部测试均正常，故确认冗余）。

---

## 三、按严重度分节

### 3.0 修复进度（滚动更新）

| ID | 状态 | 变更 | 验证 |
|---|---|---|---|
| **SEC-003** | ✅ **已修（2026-10-04）** | 新增 `tests/test_dataset_tasks.py`（15 项）· `tests/test_mcp_envelope.py`（7 项）· `tests/test_testbed.py` +2 项。**只加测试，未改任何被测代码** | `pytest` **73 → 97 passed** · `ruff` All checks passed · `code_version` 仍为 `20b202c7ffe4`（证据链未动） |
| **SEC-002** | ✅ **已修（2026-10-04）** | `tools/eeg_testbed.py` 新增 `_require_handle()`；在 `Testbed.__init__` 与 `null_pool` 两处**拼路径之前**校验。`_pool_path` docstring 写明前置条件、**不重复校验** | `pytest` **97 → 108 passed** · `ruff` All checks passed · `code_version` **未变** · **MCP 对外行为不变**（坏 handle 仍返 `E_INVALID_HANDLE` / `recoverable=False`，只是失败得更早） |
| **SEC-004** | ✅ **已修（2026-10-04）** | `requirements.txt` 删 `pandas>=2.2`；`requirements-lock.txt` 删 `pandas==3.0.6` **并同步改文件头**（如实注明「手工剔除」，否则那句「pip freeze 产出」就失真了）。均留注释防回加 | `pip --dry-run` 解析正常 · 文档零引用 · `pytest` 108 passed · `ruff` clean |
| **SEC-011** | ✅ **已修（2026-10-04）** | `eeg_mcp_server.py` 顶部 docstring：把「所有工具返回统一信封」换成**实测形状表**；新增 `tests/test_mcp_envelope.py::test_成功返回的形状与本文档一致` **逐格核对文档**（谁改形状谁就得同步改文档）。**刻意不改行为**——见下 | `pytest` 109 passed · `ruff` clean · `code_version` 未变 · **`check_mcp_stdio.py` 全通过**（stdio 协议未破） |
| **SEC-005** | ✅ **部分已修（2026-10-04）** | `eeg_testbed.py` 删 `list_twins()` / `twin_raw()` / **连带** `staged_or_source()`（级联死代码）。`eeg_cache.py` 的 `clear()` **不能删**（code_version 参与文件）→ 归入 SEC-001 决策 | `pytest` 109 passed · `ruff` clean · `code_version` 未变 · **测量零变化**：重跑得同一 handle / 同一 p / 同一指纹；四个文档汇总精确复现 |
| **SEC-013** | ⬜ 待决策 | **修复 SEC-005 时由本人触发**：重跑一次试验 → 该产物 meta 被「改签」成新版本 → 同批 20 条看起来像混版本 → 闸门拒绝合法汇总。**已手工还原该字段**，并在报告中留痕 | 还原后四个汇总全部恢复（0.50/10 · 0.55/11 · 0.10/2 · 0.20/4） |
| **SEC-008** | ✅ **已修（2026-10-04）** | `check_blinding_act4.py`：新增 `_resolves_inside()`，执行 `<env>/.venv/.../python.exe` 前先确认它**解析后仍在 env 之内**（挡符号链接/junction 逃逸）；docstring 新增「`--env` 的信任假设」一节 | 实测：env 自己的解释器 → `True`；env 之外的解释器 → `False`（拒绝执行） |
| **SEC-009** | ✅ **已修（2026-10-04）** | `act4_make_env.py`：新增 `_reject_unsafe_members()`，在**两种解包路径之前**统一跑（挡住老 Python 那条**原本毫无过滤**的 `except TypeError` 分支）。**未提高 Python 版本要求**——修代码而不是缩支持面 | 新增 `tests/test_act4_env_tar.py`（9 项）：绝对路径 / `../` / 夹层 / **反斜杠穿越** / 符号链接全部拒绝；正常归档不受影响；端到端「越界归档一个文件都不落」 |
| **SEC-010** | ✅ **已修（2026-10-04）** | `_guard` 的 `E_INTERNAL`：信封里**只回异常类型**，`str(exc)`（常含绝对路径）改写 **stderr**。**未动** `E_FILE_NOT_FOUND`——那里的路径往往正是可执行信息，属**评估后保留**，见该条目说明 | 新增测试：`_guard(lambda: raise KeyError("D:\\暂存\\..."))` → 信封里只有 `"KeyError"`、路径零出现；stderr 里能查到全文 |
| SEC-001 · SEC-006 · SEC-007 · SEC-012 | ⬜ 待处理 | — | — |

> **两条修复都做了变异核验**（不靠"跑过就算"）：
> - SEC-003：把 `_FAMILY` 里塞一个重复 run 号 → `test_每个_run_只属于一个家族` 失败。
> - SEC-002：把 `_require_handle` 换成恒等函数 → 路径立刻逃出试验台目录
>   （`x/../../escape` → 规范化后 `<root>\escape.json`；再加几层 `..` → `C:\Users\liu35\escape.json`）。
>   **守卫是承重的，不是摆设。**

### Critical

**无。**

### High

**无。**

### Medium

---

#### SEC-001 · 产物 `.json` 记录非原子写，并发下可能读到半截文件

| 字段 | 内容 |
|---|---|
| **严重度** | Medium |
| **置信度** | 高（代码可读，行为确定）；**触发概率**中等 |
| **位置** | [`tools/eeg_cache.py:216`](tools/eeg_cache.py) |
| **触发路径** | AGH 并发发工具调用 → 两次调用算出**同一 handle** → 两个进程同时 `put` → 一个在写 `.json`，另一个在读 |

**影响**：读到的 `.json` 可能被截断 → `json.loads` 抛 `JSONDecodeError`。
`describe([...])` 不捕获它，会经 `_guard` 变成 `E_INTERNAL`（**响亮失败**，不是静默污染）。
但 `_recent_of_kind` 会 `except json.JSONDecodeError: continue` —— **静默跳过**该行，
使 `eeg_artifacts`（agent 的 handle 恢复通道）少看到一条记录。
`index.jsonl` 的追加写（`_append_index`）在多进程下同理可能写出行内交错。

**证据**（同一函数里两半的待遇明显不一致）：

```python
tools/eeg_cache.py:206-214   # .npz：规范地做原子写
    if not npz_path.exists():
        # 原子写：AGH 可能并发发工具调用，半写的文件被并发读到会得到垃圾而**不是**报错
        tmp = root / f".{uuid.uuid4().hex}.tmp.npz"
        with tmp.open("wb") as fh:
            np.savez(fh, **payload)
        os.replace(tmp, npz_path)

tools/eeg_cache.py:216       # .json：裸 write_text，无 tmp、无 replace
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
```

**代码自己已经承认并发是预期场景**（第 207 行注释），却只保护了 npz 那一半。

**修复建议**：`.json` 用与上面相同的手法——写 `.<uuid>.tmp.json` 再 `os.replace`。
`_append_index` 若要严格，可改为「单进程锁 + 追加」或写独立分片文件。

> ⚠️ **二阶影响（必须先决定再动手）**：`eeg_cache.py` 是 `code_version()` 的三个参与文件之一。
> **改它一个字节 ⇒ 仓库里所有既有 `eval_*` / `raw_*` handle 立刻失效**（`E_HANDLE_STALE`），
> 包括 `docs/report.md`、`docs/zero-signal.md`、两批第四幕证据引用的全部产物。
> 所以只有两条路：**(a) 接受并写进「已知性质」**（README 复现说明里已有相关段落，可扩写）；
> **(b) 修 + 全部实验重跑**（成本 = 第一幕 + 第三幕 + 第四幕两批）。
> **不要**在没决定之前直接改。

---

#### SEC-002 · `source_raw` 未校验即拼进文件路径（纵深防御缺口） · ✅ **已修**

| 字段 | 内容 |
|---|---|
| **严重度** | Medium（**修复前不可达**，定性为纵深防御缺口） |
| **置信度** | 高（代码路径已逐行核对） |
| **位置** | [`tools/eeg_testbed.py:450`](tools/eeg_testbed.py) `_prepared_path()` · [`tools/eeg_testbed.py:634`](tools/eeg_testbed.py) `_pool_path()`<br>（行号随修复移动过两次：最初 426 / 612 → 加校验后 454 / 646 → 删死代码后 **450 / 634**，此处已按当前状态更新） |
| **触发路径** | MCP 工具 `eeg_trial_run(source_handle=...)` → `run_trial(source_raw=...)`（第 711 行）→ `Testbed.source_raw` → 拼文件名 |
| **状态** | ✅ **已修（2026-10-04）**·见下方「已实施的修复」 |

**影响**：`source_raw` 直接进 `f"prepared_{...}.json"` / `f"nullpool_{...}.json"`。
若传入 `x/../../../../evil`，路径会**逃出** `_bookkeeping_dir()`：
拼出 `nullpool_x/../../../../evil.json`（`/` 制造了新路径分量，`..` 才成为穿越）。
`_pool_path` 的返回值既被**读**（`path.read_text`）也被**写**（`path.write_text`）。

**为什么现在打不穿**：`run_trial` 在**第 698 行**先调 `T.prepare()`（`Testbed` 建于第 697 行），
其 `stage()` 会走 `cache.get(source_raw)` → `_validate()` 用 `HANDLE_RE`
（`^(raw|clean|feat|eval)_[0-9a-f]{12}$`，[`tools/eeg_cache.py:47`](tools/eeg_cache.py)）
校验并抛 `E_INVALID_HANDLE`，**在到达 `null_pool`（第 702 行）之前就中止了**。
（`_load_prepared` 那次会先做一次穿越**读**，但文件不存在即返回 False，无害。）

**证据**：

```python
tools/eeg_testbed.py:450   return self.dir / f"prepared_{self.source_raw}.json"
tools/eeg_testbed.py:634   return Path(root) / f"nullpool_{source_raw}.json"
tools/eeg_cache.py:47      HANDLE_RE = re.compile(r"^(raw|clean|feat|eval)_[0-9a-f]{12}$")
```

`cache` 侧有严格校验，`testbed` 侧**没有**——两处口径不一致本身就是缺口。

**修复建议**（3 行，零功能影响）：在 `run_trial()` 开头与 `null_pool()` 开头各加一次
handle 格式校验（复用 `cache.HANDLE_RE`），非法即抛 `CacheError("E_INVALID_HANDLE")`。
这样**不依赖**调用顺序，把纵深防御补齐。

**已实施的修复（2026-10-04）**

| 位置 | 改动 |
|---|---|
| `tools/eeg_testbed.py` | 新增模块级 `_require_handle(value, what)`：复用 `cache.HANDLE_RE` 白名单，非法抛 `CacheError("E_INVALID_HANDLE", recoverable=False)`——**错误码与 `eeg_cache._validate` 一致** |
| `Testbed.__init__` | `self.source_raw = _require_handle(source_raw, "source_raw")`——挡住 `_prepared_path()` 那条路，且**发生在 `mkdir` 之前** |
| `null_pool` | `src = _require_handle(source_raw or tb_.source_raw, "source_raw")`——挡住**显式传入**那条路 |
| `_pool_path` | **不重复校验**，改为在 docstring 写明前置条件（同一件事只在一处做判断，避免两份逻辑漂移） |
| `tests/test_testbed.py` | **+11 项**：8 种非法 handle 参数化（含 `../evil`、`x/../../evil`、`..\..\evil`、尾随空格…）被拒 · 合法 handle 不被误拒 · **穿越 handle 不落下任何文件** · `null_pool` 对显式非法 `source_raw` 也拒绝 |

**为什么选这个层次**：把校验放在**信任边界**（`Testbed` 构造、`null_pool` 入口），
而不是放在拼路径的私有函数里——前者是「谁给的值谁负责」，后者会让每个内部调用点都背上判断。

**回归验证（关键：对外行为完全不变）**

```
pytest                  97 → 108 passed
ruff                    All checks passed
code_version            20b202c7ffe4（未变）
MCP 对外行为             eeg_trial_run("x/../../evil") → E_INVALID_HANDLE, recoverable=False
                        ↑ 与修复前**同一个错误码**，只是失败得更早、更靠近边界
```

**变异核验（证明守卫是承重的）**：把 `_require_handle` 临时换成恒等函数后，
`x/../../escape` 拼出的路径规范化后逃到 `<root>\escape.json`；再加几层 `..`
则逃到 `C:\Users\liu35\escape.json`——**完全离开项目目录**。

---

#### SEC-003 · 关键路径测试缺口：标签家族守卫与第三幕核心测量路径均无测试 · ✅ **已修**

| 字段 | 内容 |
|---|---|
| **严重度** | Medium（正确性风险，非安全漏洞） |
| **置信度** | 高（已机械统计） |
| **位置** | [`tools/eeg_dataset.py:95`](tools/eeg_dataset.py) `resolve_task` · [`tools/eeg_testbed.py:699`](tools/eeg_testbed.py) `run_trial` · [`tools/eeg_mcp_server.py`](tools/eeg_mcp_server.py) 13 个工具函数 |
| **触发路径** | 任何一次修改这些函数之后——没有测试会告警 |
| **状态** | ✅ **已修（2026-10-04）**·见下方「已实施的修复」 |

**影响**：

1. **`resolve_task` / `task_info` / `family_of_runs` 零测试。** 而
   [`tools/eeg_dataset.py:21`](tools/eeg_dataset.py) 的模块文档写得很重：
   > 「runs 3/7/11 = 实际左右手；4/8/12 = 想象左右手……**把不同家族混在一起会让标签静默变成错的**。」

   这是一个「**静默错标签**」守卫，却没有一条测试钉住它。它一旦回归，实验结论会**静默**失去意义。
2. **`run_trial` 零测试。** 第三幕 0.10 / 0.20 / 0.525 与全部 80 个 `eval_*` handle 都由它产出。
   （本会话中我手工跑过多次并复现出文档里的 handle，说明**当前实现是对的**——
   但这是人工验证，不是测试资产。）
3. **MCP 工具层零测试。** 13 个工具有 `tools/eeg_mcp_server.py` 的 `_guard` 统一错误翻译，
   但没有任何测试覆盖「参数非法 → 结构化错误码」这条路径（只有 `check_mcp_stdio.py`
   这个手工连通性脚本会触发一次）。

**证据**（机械统计公开符号在 `tests/` 中的出现情况）：

```
eeg_dataset:  resolve_task / task_info / family_of_runs  —— 从未在测试中出现
eeg_testbed:  run_trial / search_hill / search_random / emulate_p_value /
              analytical_baseline / wilson_ci / search  —— 从未在测试中出现
eeg_mcp_server: 13 个工具函数全部从未在测试中出现
```

现有 73 项测试集中在 `cache` / `preprocess` / `evaluate` / 孪生体盲性 / 判分器上。

**修复建议**（按性价比排序，都不需要改被测代码）：

1. `resolve_task`：给每个家族各一条 + 一条**混用**用例，断言抛错或纠正。最高优先级。
2. `run_trial`：用极小 fixture（4 被试 × 20 试次、budget=2、n_perm=3）跑通一次，
   断言返回结构、`significant` 类型、产物可 `describe`。**不要**断言具体数值（那是数据决定的）。
3. MCP 工具层：用 `check_mcp_stdio.py` 的手法写一个 pytest——起 server、调一个工具、
   故意传坏参数，断言 `{"ok": false, "error": {"code": ...}}`。

**已实施的修复（2026-10-04）**

| 文件 | 内容 | 项数 |
|---|---|---|
| [`tests/test_dataset_tasks.py`](tests/test_dataset_tasks.py)（新增） | 家族表两两不相交 · 家族表覆盖任务表 · 同一 run 在不同家族含义不同 · `family_of_runs` 单家族/跨家族/未知/空 · `resolve_task` 5 组跨家族或未知输入**必须被拒** · 任务名与 runs 不匹配被拒 · 未知任务名被拒 | **15** |
| [`tests/test_mcp_envelope.py`](tests/test_mcp_envelope.py)（新增） | 坏格式 → `E_INVALID_HANDLE`(不可恢复) · 格式对但不存在 → `E_HANDLE_NOT_FOUND`(可恢复) · 两者必须可区分 · **13 个工具的返回全部是可解析 JSON** · 合成数据评估被 `refused` · 错误的上游类型 → `E_BAD_INPUT_KIND` | **7** |
| [`tests/test_testbed.py`](tests/test_testbed.py)（追加） | `run_trial` 跑通一次完整试验（断言契约而非数值：返回结构/`significant` 与 `p<α` 自洽/选中配置来自搜索空间/产物可 `describe`/孪生体句柄有效）· `run_trial` 拒绝孪生体的孪生体 | **+2** |

**为什么这样写**：`run_trial` 的测试**刻意不断言具体数值**——那由数据决定，
写死只会退化成「改测试让它通过」。钉的是契约（结构、自洽性、产物真实落盘）。

**回归验证**：`pytest` **73 → 97 passed**；`ruff` **All checks passed**；
`code_version()` 仍为 `20b202c7ffe4`（**未触碰任何 `code_version` 参与文件**，证据链完好）。

**顺带发现两条新问题**（见 SEC-011 / SEC-012）——是在写测试的过程中撞出来的，
不是原计划的一部分。

---

### Low

---

#### SEC-004 · `pandas` 是冗余依赖：本项目**从不直接使用**它，且**完全缺席也能跑** · ✅ **已修**

| 字段 | 内容 |
|---|---|
| **严重度** | Low（供应链面 + 安装体积） |
| **置信度** | 高（已做「完全缺席」实测，不只是 grep） |
| **位置** | [`requirements.txt`](requirements.txt)（原第 6 行 `pandas>=2.2`）· [`requirements-lock.txt`](requirements-lock.txt)（原第 66 行 `pandas==3.0.6`） |
| **触发路径** | `pip install -r requirements.txt` / `-r requirements-lock.txt` 会多装一个 30+ MB 的包 |
| **状态** | ✅ **已修（2026-10-04）**·见下方「已实施的修复」 |

**影响**：不必要的第三方依赖 = 不必要的供应链暴露面与安装时间。
README 让复现者「用锁文件」，而锁文件里也带着它——所以两条安装路径都会多装。

**证据（含一处我原报告的措辞修正）**：

```
grep -rn "pandas|import pd |pd\." tools/ scripts/ tests/   → 零命中
```

> ⚠️ **修正**：初版报告写的是「全仓库零引用」。这在**我们自己的代码**里成立，
> 但不完整——实测「导入我们全部模块后，`pandas` **确实进了** `sys.modules`」。
> 逐模块排查定位到是 **scikit-learn** 拉进来的：
>
> ```
> 导入 numpy  → pandas 进 sys.modules: False
> 导入 scipy  → False
> 导入 sklearn → True     ← 是它
> 导入 mne    → False
> ```
>
> 那它到底是不是**必需**？用 ImportError 拦截器**精确模拟「没装」**后重测：
>
> ```
> sklearn 在「无 pandas」下可用 ✓  balanced_accuracy = 0.525
> mne     在「无 pandas」下可用 ✓
> 真实 EDF 加载（被试 1）→ X (45, 64, 673)，类别 [23, 22] ✓
> ```
>
> 且 `importlib.metadata.requires('scikit-learn')` 里**没有** pandas；
> `mne` 只在 `[full]` 类 extra 里才要求它。**结论：sklearn 在它存在时顺手用一下，
> 但并不依赖它**——所以对本项目是纯冗余。
>
> （第一次尝试用 `sys.modules['pandas'] = None` 模拟"缺失"，得到的是一个
> `AttributeError: 'NoneType' object has no attribute 'DataFrame'` ——**那是测试手法
> 的产物，不是真实缺失**。换成 ImportError 拦截器才得到正确结论。记下来提醒后来者。）

**已实施的修复（2026-10-04）**

| 文件 | 改动 |
|---|---|
| [`requirements.txt`](requirements.txt) | 删掉 `pandas>=2.2`，并在原位留一条注释说明**为什么刻意不列**（防止日后被好心加回来） |
| [`requirements-lock.txt`](requirements-lock.txt) | 删掉 `pandas==3.0.6`；**同时改文件头**——原头写「生成方式 = pip freeze」，现在如实注明「**手工剔除了 pandas**，其余逐行与 freeze 一致」，并附上述证据 |

**为什么连锁文件也改**：README 让复现者用锁文件，只改 `requirements.txt` 等于没解决问题。
但锁文件自称 `pip freeze` 产出，删行会让这句话失真——**所以同步改了头部说明**，
而不是留下一句不成立的话。

**回归验证**：

```
pip install --dry-run -r requirements-lock.txt   → 解析正常，无报错
grep -i pandas README.md docs/*.md .agh/skills/*/SKILL.md  → 文档零引用
pytest    108 passed
ruff      All checks passed
```

---

#### SEC-005 · 死代码三处（**2 处已删；1 处受 code_version 约束，只能文档化**）

| 字段 | 内容 |
|---|---|
| **严重度** | Low |
| **置信度** | 高（全仓库标识符计数 = 1，仅定义处；已复核两遍——第一次自动扫描有过误报） |
| **位置** | ~~`tools/eeg_testbed.py` 的 `list_twins()` / `twin_raw()`~~（**已删除**）· [`tools/eeg_cache.py:345`](tools/eeg_cache.py) `clear()`（**仍在**） |
| **触发路径** | 无（定义后无人调用）——**已核实**：`grep -rn "\blist_twins\b\|\btwin_raw\b\|cache\.clear\(\)" tools/ scripts/ tests/ docs/ .agh/` 当时只命中定义行 |
| **状态** | ✅ **部分已修（2026-10-04）**·见下方 |

**影响**：维护误导——读代码的人会以为存在「清空产物」「列出孪生体」「造 raw 层孪生体」的
正式通道，实际都不在调用链上。`clear()` 尤其危险：它删产物目录下所有 `.npz`/`.json`
（[`tools/eeg_cache.py:345-351`](tools/eeg_cache.py)，`unlink()` 在第 349 行），
一个没人用却公开的破坏性函数。

**已实施的修复（2026-10-04）**

| 目标 | 处置 | 理由 |
|---|---|---|
| `list_twins()`（`eeg_testbed.py`） | **删除** | 无人调用；同组的 `twin_truth` / `is_twin` 都在用，只有它是多余的 |
| `twin_raw()`（`eeg_testbed.py`） | **删除** | `run_trial` 走的是 `make_twin`，这个方法从未被调用 |
| `staged_or_source()`（`eeg_testbed.py`） | **连带删除** | **级联**：它只被 `twin_raw` 用，删了上面那个它就成死代码 |
| `clear()`（`eeg_cache.py`） | ❌ **不能删，只能文档化** | `eeg_cache.py` 是 `code_version()` 参与文件——**删它一个字节，全部既有 handle 立即失效**（见 §5 D-1）。归入 SEC-001 的同一决策 |

**关键验证：删除没有改变任何测量结果。** 删代码会改 `testbed_code_version`
（`2a5c6c6cdc5b` → `02c36d5ec09b`），所以必须证明数字没动：

```
重跑 run_trial('raw_057280305171', 11, strategy='hill', budget=24, n_perm=30)
  → handle = eval_48cae117f544   （与文档记载**同一个**）
  → p = 0.0323 / obs = 0.5658    （与文档记载**同一个**）
  → data_fingerprint 一致         （d664c850d0d9）

四个文档汇总全部精确复现：
  §8.5 hill      20 条 → 0.50 (10)   ✓ 文档记 0.50 / 10
  §8.5 random    20 条 → 0.55 (11)   ✓ 文档记 0.55 / 11
  §9.5 budget=1  20 条 → 0.10  (2)   ✓ 文档记 0.10 / 2
  §9.5 budget=4  20 条 → 0.20  (4)   ✓ 文档记 0.20 / 4
```

> 这同时是「上一轮 SEC-001 修复」的一次**实战检验**：试验台版本变了，
> 零分布缓存被判定失效并**重算**，而重算结果与原来逐位相同——版本闸门
> 既没有误伤，也没有漏放。
>
> 但这次重跑**也暴露了一个新问题**，见 **SEC-013**。

---

#### SEC-006 · `subjects` 无上界校验，可触发批量下载

| 字段 | 内容 |
|---|---|
| **严重度** | Low |
| **置信度** | 高（代码路径确定）；**实际发生概率低** |
| **位置** | [`tools/eeg_pipeline.py:114`](tools/eeg_pipeline.py) `fetch(subjects=...)` → [`tools/eeg_dataset.py:222`](tools/eeg_dataset.py) `subjects = subjects or DEFAULT_SUBJECTS` |
| **触发路径** | 工具参数 `eeg_fetch(subjects=[1..109])` |

**影响**：无长度/范围校验，直接逐个 `eegbci.load_data`。按项目自己的实测
（README：「单个被试耗时约 11 分钟、≈11 KB/s」），109 个被试 ≈ **20 小时网络拉取 + 数百 MB 落盘**。
即「自己被自己拖死」+ 向外产生大量流量。非致命（不崩、可中断）。

**证据**：`load()` 里只有 `subjects = subjects or DEFAULT_SUBJECTS`，随后直接 `for subj in subjects`。
逐被试异常被 `except Exception` 兜住记进 `failures`（[`tools/eeg_dataset.py:234`](tools/eeg_dataset.py)），
所以**非法值不会崩，只会静默变成 failure 条目**。

**修复建议**：`fetch()` 里加长度上限（如 `len(subjects) <= 16`）与范围校验（正整数、≤ 109），
超限抛 `ValueError`（会经 `_guard` 变成 `E_BAD_ARGUMENT`）。

---

#### SEC-007 · 数据侧提示注入面：通道名等文件内容会进入 agent 上下文

| 字段 | 内容 |
|---|---|
| **严重度** | Low（**本部署下不可利用**，但架构上存在） |
| **置信度** | 高（路径确定）；利用可能性 **需人工确认** |
| **位置** | [`tools/eeg_pipeline.py`](tools/eeg_pipeline.py) `inspect()` 返回 `ch_names` → [`tools/eeg_mcp_server.py:125`](tools/eeg_mcp_server.py) `eeg_inspect` → agent 上下文 |
| **触发路径** | 若有人把**构造过的 EDF** 放进 `MNE_DATASETS_EEGBCI_PATH`，其通道名会成为工具返回值的一部分 |

**影响**：本项目的研究对象恰恰是「agent 会不会被数据带偏」。若通道名/元信息里含
指令性文本，它会**原样进入 agent 的上下文**。数据源目前固定为 PhysioNet
（[`tools/eeg_dataset.py:158`](tools/eeg_dataset.py) 的 URL 不可由工具参数控制），
所以**实际不可利用**；但一旦支持自定义数据源，这条就成了入口。

**修复建议**：不急于动手。若要加固，可在 `inspect()` 的返回里对字符串字段做长度截断
与可疑模式提示；或在文档的威胁模型里记一句「数据内容视为不可信输入」。

---

#### SEC-008 · `check_blinding_act4.py` 执行 `--env` 指定路径下的可执行文件

| 字段 | 内容 |
|---|---|
| **严重度** | Low（操作者本机、自用脚本） |
| **置信度** | 高 |
| **位置** | [`scripts/check_blinding_act4.py:321-326`](scripts/check_blinding_act4.py) |
| **触发路径** | `python scripts/check_blinding_act4.py --env <任意目录>` → 执行 `<任意目录>/.venv/Scripts/python.exe` |

**影响**：`--env` 是操作者输入；若被指到一个含恶意 `.venv` 的目录，会以当前用户身份执行它。
这是**本地开发工具的常见取舍**，不是远程可利用漏洞。`act4_make_env.py:283`
用的是 `sys.base_prefix`（自身解释器），不受影响。

**修复建议**：可加一句注释说明「`--env` 指向的目录会被当作可信来源」；
若要更严，先校验该目录含 `artifact_root.txt` 与预期文件结构再执行。

**已实施的修复（2026-10-04）**

1. **docstring 新增「关于 `--env` 的信任假设」一节**，把边界写清楚：
   `--env` 指向的目录会被当作可信来源；已加的是**纵深防御，不是沙箱**——
   它挡不住「整个 env 目录都是准备好的」这种情况，那也不是本地自用脚本要防的事。
2. **新增 `_resolves_inside(path, root)`**，执行前确认解释器的**真实路径**仍在
   `env` 之内。`Path.exists()` 会跟着符号链接走，所以一个指向别处的 `.venv`
   能通过存在性检查、跑起来却是另一个程序。命中即**拒绝执行**并报告。

```
实测：env 自己的解释器        → _resolves_inside = True   （照常执行）
      env 之外的解释器        → _resolves_inside = False  （拒绝执行）
```

---

#### SEC-009 · `act4_make_env._extract` 在 Python < 3.12 的回退分支缺少安全过滤

| 字段 | 内容 |
|---|---|
| **严重度** | Low |
| **置信度** | 高（代码确定）；**不可利用**（tarball 来自本仓库自己的 `git archive`） |
| **位置** | [`scripts/act4_make_env.py:117-123`](scripts/act4_make_env.py) |
| **触发路径** | 在 Python 3.11 及以下运行 `act4_make_env.py` |

**影响**：`filter="data"` 在 3.12+ 才存在；回退分支 `tf.extractall(dest)` **无过滤**，
理论上允许 `../` 穿越与设备文件。本项目 `requirements.txt` 只写 `Python 3.10+`，
所以在 3.10/3.11 上会走回退。**但** tar 内容来自 `git archive <本仓库提交>`，非外部输入，
因此这是「配置漂移」而非「可被攻击」。

**修复建议**：把要求提到 **Python ≥ 3.12**（README「快速开始」已写 3.10+，同步改），
或在回退分支里显式拒绝含 `..` / 绝对路径 / 非常规文件类型的成员。

**已实施的修复（2026-10-04）——选了后者**

新增 `_reject_unsafe_members()`，在 `try/except` **之前**统一跑一遍，
所以两条分支**都**受保护（不是只在回退分支里补）。逐成员检查：

- 绝对路径（`/x`、`C:/x`）
- 任何 `..` 路径分量（含 `a/../../b` 这种夹层）
- **反斜杠**分隔的穿越（Windows 上 `\` 同样是分隔符，`PurePosixPath` 单独看不出来）
- 非「文件/目录」成员（符号链接、设备文件、FIFO）

**没有**提高 Python 版本要求——修代码比缩小支持面好。

新增 `tests/test_act4_env_tar.py`（9 项），拿**构造出来的越界 tar** 去打它：

```
普通归档              → 通过（不误伤）
/etc/evil.txt         → 拒绝
../evil.txt           → 拒绝
a/../../evil.txt      → 拒绝
a\..\..\evil.txt      → 拒绝     ← 反斜杠穿越
符号链接成员           → 拒绝
_extract 端到端        → 越界归档在目标目录**一个文件都不落**
```

---

#### SEC-010 · `_guard` 把异常原文回给调用方（可能含本机路径）

| 字段 | 内容 |
|---|---|
| **严重度** | Low |
| **置信度** | 高 |
| **位置** | [`tools/eeg_mcp_server.py:83`](tools/eeg_mcp_server.py) |
| **触发路径** | 任何未预期异常 → `E_INTERNAL`，消息体为 `f"{type(exc).__name__}: {exc}"` |

**影响**：`FileNotFoundError` / `OSError` 的原文常含**绝对路径**（如
`D:\暂存\source\tools\...`）。这些字符串会进入 agent 上下文，也可能随对话、
`docs/evidence/*.jsonl` 会话导出一起进仓库。本项目的会话导出有脱敏流程
（[`scripts/export_session.py:97-126`](scripts/export_session.py) 会替换家目录与用户名），
**风险已被下游缓解**，故为 Low。

**修复建议**：`E_INTERNAL` 只回 `type(exc).__name__`，把 `str(exc)` 写到 **stderr**
（`eeg_mcp_server.py` 开头已声明「stdout 是 JSON-RPC 通道，调试输出必须写 stderr」）。

**已实施的修复（2026-10-04）**

```python
except Exception as exc:
    # 只把异常类型回给调用方；str(exc) 常带本机绝对路径
    print(f"[eeg-agent] E_INTERNAL {type(exc).__name__}: {exc}", file=sys.stderr)
    return _err("E_INTERNAL", type(exc).__name__,
                suggestions=[...原建议..., "详细原因已写入 server 的 stderr。"],
                recoverable=True)
```

新增测试：拿一个故意抛 `KeyError(r"D:\暂存\source\tools\secret_path.py")` 的函数
过 `_guard`，断言**信封里路径零出现**、而 **stderr 里能查到全文**。

> **评估后保留的一处**：`E_FILE_NOT_FOUND`（第 98 行）**仍然回显 `str(exc)`**。
> 因为它与 `E_INTERNAL` 不同——**路径往往正是可执行信息**（例如 MNE 报
> 「数据下载目录不存在」时，告诉 agent 哪个目录才有意义）。
> 把它的路径也抹掉，会把一条**可恢复**的错误变成不可操作的错误。
> 这是**权衡后的保留**，不是遗漏；在此留痕以便日后复核。

---

#### SEC-011 · 模块文档承诺「统一信封」，实际**根本没有单一形状** · ✅ **已修**

| 字段 | 内容 |
|---|---|
| **严重度** | Low（契约/文档不一致；可能误导 agent） |
| **置信度** | 高（12 个可调用工具**逐一实测**） |
| **位置** | 承诺在 [`tools/eeg_mcp_server.py`](tools/eeg_mcp_server.py) 顶部 docstring；首个反例在 `eeg_inspect` 的实现 |
| **触发路径** | agent 调任一工具并假设 `resp["ok"]` / `resp["handle"]` 一定存在 |
| **状态** | ✅ **已修（2026-10-04）**·见下方「已实施的修复」 |

**影响**：模块开头原写「**所有工具**返回统一信封：成功 `{"ok": true, "handle": ..., "summary": {...}}`」，
而 [`eeg-analysis`](.agh/skills/eeg-analysis/SKILL.md) 也把这条告诉了 agent。
实测**并非如此**。

**证据（12 个可调用工具的实测成功形状）**：

| 工具 | 成功时的顶层键 |
|---|---|
| `eeg_fetch` `eeg_preprocess` `eeg_features` `eeg_evaluate` `eeg_validate` `eeg_null_twin` | `ok` `handle` `summary` (+`next_step`/`note`) |
| `eeg_trial_run` `eeg_load_synthetic` | `ok` `handle` `summary` (+`next_step`/`warning`) |
| `eeg_artifacts` | `ok` `summary` `cache_dir` `index` —— **没有 `handle`** |
| `eeg_defect_rate` | `ok` `summary` `note` `refused` —— **没有 `handle`** |
| `eeg_ablation` | `ok` `baseline` `agent` `delta_balanced_accuracy` `fairness` `verdict` |
| `eeg_evidence` | `ok` `claims` `provenance` `refused` `rule` |
| `eeg_inspect` | `handle` `kind` `healthy` `warnings` `flat_channels` `amplitude_uv` … —— **连 `ok` 都没有** |

> ⚠️ **修正（我报告初版的说法也不完整）**：初版写「13 个工具里 1 个不一致
> （`eeg_inspect`）」。实测后发现真实情况更杂：`eeg_artifacts` / `eeg_defect_rate`
> **没有 `handle`**（它们不产出新产物），`eeg_ablation` / `eeg_evidence` 不走信封。
> **统一信封只对「失败」成立，成功侧压根没有统一形状。**

**修复建议（照旧：改文档，不要改行为）**

> ⚠️ **不建议**把 `eeg_inspect` 之类包成 `_ok()`。本项目**整个立论**建立在
> 「agent 在它熟悉的环境里会怎么做」上，而第四幕两批实测用的就是**现有**形状。
> 改形状会改变 agent 的输入，**两批第四幕证据将失去可比性**。
> 典型的「二阶影响 > 收益」。

**已实施的修复（2026-10-04）**

| 位置 | 改动 |
|---|---|
| [`tools/eeg_mcp_server.py`](tools/eeg_mcp_server.py) 顶部 docstring | 把「所有工具返回统一信封」换成一张**实测表**（即上表），并写明「**别假设成功返回里有 `ok` 或 `handle`**」；附上「为什么不统一」的理由（证据可比性） |
| [`tests/test_mcp_envelope.py`](tests/test_mcp_envelope.py) | 新增 `SUCCESS_SHAPE` 表 + `test_成功返回的形状与本文档一致`：**逐格核对文档那张表**。谁改了任一工具的返回形状，测试会失败——**逼他同步改文档**，而不是让文档悄悄过期（SEC-011 就是这么发生的） |

> 表里**没有** `eeg_fetch`（要联网下载）与 `eeg_trial_run`（预算大、分钟级）——
> 这一点在测试文件里**如实注明**，不假装覆盖。

**回归验证**：

```
pytest                      108 → 109 passed
ruff                        All checks passed
code_version                20b202c7ffe4（未变）
scripts/check_mcp_stdio.py  「全部通过：MCP server 可以作为一个真实的 MCP 进程工作」
                            ↑ 最强的一条：docstring 改动没有破坏 stdio 协议
```

---

#### SEC-012 · `resolve_task` 返回的是模块级 `TASKS` 的**同一对象**（别名风险）

| 字段 | 内容 |
|---|---|
| **严重度** | Low（**当前无触发路径**，属防御性问题） |
| **置信度** | 高（对象身份可直接验证） |
| **位置** | [`tools/eeg_dataset.py:109`](tools/eeg_dataset.py) `info = task_info(task)` → `return task, info`；消费点 [`tools/eeg_dataset.py:220`](tools/eeg_dataset.py) `runs = info["runs"]` |
| **触发路径** | 任何未来代码对 `info["runs"]` / `info["codes"]` 做**原地修改**（`append` / `sort` / `pop`） |

**影响**：`task_info()` 直接返回 `TASKS[task]`，**不是副本**；`load()` 又把它赋给 `runs`。
一旦有人写 `runs.sort()`，模块级任务定义会被**永久污染**，之后同进程内所有分析都用错 runs。
当前代码**只读**，所以我把它记为防御性问题而非缺陷。

**证据**：

```
eeg_dataset.py:89-92   def task_info(task): ... return TASKS[task]      # 返回同一对象
eeg_dataset.py:109     info = task_info(task)                           # 未复制
eeg_dataset.py:220     runs = info["runs"]                              # 仍然别名
（grep 全仓库：无 runs.append / runs.sort / runs.pop）
```

**修复建议**：`resolve_task` 里改为 `return task, dict(info)`（浅拷贝即可，
两个值都是不可变使用方式）。**但这要改 `eeg_dataset.py`——它参与 `code_version()`**，
改了就作废全部既有 handle（见 §5 D-1）。建议与 SEC-001 一并决策。

---

#### SEC-013 · 「试验台版本」记在**可变 meta** 里：一次无害重跑会把一批同内容产物「改签」成混版本

| 字段 | 内容 |
|---|---|
| **严重度** | Low（可复现路径被打断；数字本身没错） |
| **置信度** | 高（**刚刚实际发生**，不是推演） |
| **位置** | 版本写入 [`tools/eeg_testbed.py`](tools/eeg_testbed.py) `run_trial` 的 eval `meta`；闸门在 `defect_rate` |
| **触发路径** | 对**任何一个**已记入文档的试验重跑一次（哪怕结果逐位相同） |
| **来源** | **本报告作者在修复 SEC-005 时自己触发的**——记下来，不藏 |

**发生了什么**（全程可复算）

修 SEC-005 时，为了证明「删死代码不影响测量」，我重跑了一次文档里记载的试验
`run_trial('raw_057280305171', 11, hill, budget=24, n_perm=30)`。
结果确实是**同一个 handle、同一个 p、同一个指纹**——但 `cache.put` 会把该产物的
`.json` 记录**重写一遍**，于是这一个产物被加上了新的 `meta.testbed_code_version`，
而它那 19 个「同批兄弟」仍是没有该字段的旧产物。

紧接着，文档里的汇总路径就断了：

```
eeg_defect_rate(§8.5 的 20 个 hill handle)
  → CacheError: 这批试验来自 2 个不同版本的试验台代码：['02c36d5ec09b', 'None']
    ……混在一起汇总得到的虚报率没有意义。
```

**闸门的行为是对的**（它挡住了想挡的东西），**但它挡的是一次误报**：
这 20 条的数据指纹与结果完全一致，只是其中一条的**标签**被重写成了新版本。

**根因**：上一轮为修 SEC-001（同参数两套数字并存）而加的版本标记，被放在了
**meta** 里——而 meta 是**可变**的（每次 `cache.put` 都重写）。
版本本应属于**身份**，却被放进了**记录**。

**处置（已做）**

1. **手工还原**该产物的 meta：移除被注入的 `testbed_code_version` 字段。
   数据、handle、指纹、`params` 全程未动。
2. 还原后**四个文档汇总全部精确复现**（0.50/10 · 0.55/11 · 0.10/2 · 0.20/4）。

> ⚠️ **这是一次人工改动证据记录的动作，必须留痕**：被改动的是
> `%LOCALAPPDATA%\eeg-agent\artifacts\v1\eval_48cae117f544.json` 的
> `meta.testbed_code_version` 一个键（由有变无）。`created_utc` 仍是我重跑时写下的
> 时间——这一点在 README「复现说明」里已经如实写明「`created_utc` 是写入时间，
> 不是创建时间」，属已知性质。

**修复建议（两条路，都需要单独评审，本次未动）**

- **(a) 把版本移进 `params`**（即进入 handle 配方）：身份与记录就一致了。
  **代价**：一次性重基线**全部试验台产物**的 handle（第三幕 80 条 + 第四幕孪生体），
  文档里的 handle 清单要整体更新。**收益**：从此不可能再出现"同身份两套数字"。
- **(b) 让闸门按内容判**，而不是按声明判：同 `(strategy, budget, seed, n_perm)`
  的产物，只有当 `observed` 也**不同**时才算真混合。
  **代价**：闸门变复杂，且 `defect_rate` 需要拿到 `seed` 与指纹。

**在二者之间做选择之前，建议先明确**：这套试验台的产物列表还要不要继续增长？
若第三/四幕已收尾、只做归档，选 (b) 的性价比更高（不动任何既有 handle）。

---



---

---

## 四、已验证项清单（查过、没问题）

| # | 项 | 验证方式与结论 |
|---|---|---|
| 1 | **硬编码密钥 / 凭证** | 全仓库正则扫（`sk-*`、`api_key=`、邮箱、手机号）+ `git ls-files` 查 `.env`/`*.key`/`*.pem`/`token` → **零命中**。`.env` 不存在，只有 `.env.example` 占位符 |
| 2 | **SQL / NoSQL 注入** | 唯一的 SQL 在 [`scripts/export_session.py:174`](scripts/export_session.py)：`WHERE session_key = ?` **参数化**；插值的 `cols` 来自 `PRAGMA table_info`（库结构，非用户输入）。库以 `mode=ro` 只读打开（第 218 行）。**无注入** |
| 3 | **命令注入** | 三处 `subprocess.run`（`act4_make_env.py:105,286`、`check_blinding_act4.py:299,325`）**全部用 list 传参、无 `shell=True`、无字符串拼接**。仓库内**无 `os.system` / `eval` / `exec` / `__import__`** |
| 4 | **不安全反序列化** | 无 `pickle`、无 `yaml.load`。`np.load(..., allow_pickle=False)`（[`tools/eeg_cache.py:319`](tools/eeg_cache.py)）；其余全是 `json.loads`。**安全** |
| 5 | **tar 路径穿越** | 主路径用了 `filter="data"`（[`scripts/act4_make_env.py:121`](scripts/act4_make_env.py)）——见 SEC-009 记的回退分支 |
| 6 | **handle → 文件名的路径穿越** | [`tools/eeg_cache.py:47`](tools/eeg_cache.py) `HANDLE_RE` 白名单校验，`_validate()` 在 `get/describe/exists` 前统一执行。**cache 侧安全**（testbed 侧见 SEC-002） |
| 7 | **XSS（两个静态页）** | 两个 HTML **无外部资源引用**（`src`/`href` 无一指向 `http`），**无 `<form>` 提交**，**无 `target="_blank"`**。`innerHTML` 只由**内联字面量** `const DATA = {...}`（[`docs/audit.html:388`](docs/audit.html)）拼装；搜索框的值仅用于 `includes()` **过滤**，从不进 HTML（[`docs/audit.html:483-485`](docs/audit.html)）。**无 DOM XSS** |
| 8 | **CSRF / CORS** | 无服务端、无 Cookie、无跨域请求 → **不适用** |
| 9 | **SSRF** | 唯一的网络出口是 `mne.datasets.eegbci.load_data`，目标 URL **硬编码为 PhysioNet**，工具参数**不能**改 URL。**不可利用** |
| 10 | **XXE / 原型污染 / 文件上传** | 无 XML 解析、无对象合并、无上传入口 → **不适用** |
| 11 | **公开资源的 ID 可枚举性** | 产物 handle 是 `f"{kind}_{sha256(recipe)[:12]}"`（[`tools/eeg_cache.py:188`](tools/eeg_cache.py)）——**非自增、非顺序**。且本系统**无访问控制**，无需防枚举。**已符合「不用自增 ID」** |
| 12 | **弱随机数 / 弱加密** | 临时文件名用 `uuid.uuid4()`（[`tools/eeg_cache.py:211`](tools/eeg_cache.py)）；内容寻址用 `hashlib.sha256`（非安全用途）。**无自研加密、无 `random` 用于安全场景** |
| 13 | **资源泄漏（文件句柄）** | `grep` 全仓库**没有裸 `open()`**——全部 `with` 或 `Path.read_text/write_text`；`np.load` 用 `with` 上下文（[`tools/eeg_cache.py:319`](tools/eeg_cache.py)） |
| 14 | **时区 / 时间** | 所有时间戳统一 `time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())`（UTC）——**无本地时区混用** |
| 15 | **静默失败（逐条核对）** | `_append_index` 吞 `OSError`（[`eeg_cache.py:236`](tools/eeg_cache.py)，注释说明「索引写失败不应让主流程失败」）、`_recent_of_kind` 吞 `OSError`、`exists()` 吞 `CacheError`、`load()` 逐被试吞 `Exception`——**四处都吞得有理由且写在注释里**，非无脑兜底 |
| 16 | **`zip()` 静默截断** | ruff `B905` 在 [`eeg_pipeline.py:232,245,252`](tools/eeg_pipeline.py) 报 3 处，**逐处查看后判定为误报**：三处都是 `np.unique(..., return_counts=True)` 的 `values`/`counts` 配对，长度由 NumPy 契约保证相等。**不构成缺陷**（这也正是项目中豁免 B905 的合理之处） |
| 17 | **依赖版本** | 有 [`requirements-lock.txt`](requirements-lock.txt) 精确快照（`pip freeze`），文件头写明生成日期与 code_version |
| 18 | **`.gitignore` 覆盖** | `.env` / `*.key` / `*.pem` / `artifacts/` / `mne_data/` / **`docs/evidence/full/`（含 PII 的完整诊断包）** / `.venv/` / `__pycache__/` / 第四幕 shim 备份 / `artifact_root.txt`——**覆盖完整** |
| 19 | **会话导出脱敏** | [`scripts/export_session.py:97-126`](scripts/export_session.py) 有专门的 redaction：密钥、家目录、用户名、邮箱/手机 → 替换为占位符。**这是加分项** |
| 20 | **输入校验（分析链）** | `preprocess` 对 `channel_set`/`reref` 白名单、`crop_sec` 越界、滤波带 `0<low<high<Nyq`、陷波范围、滤波长度不足、`drop_channels` 清空、`reject_uv` 全剔——**逐条有校验与清晰报错**。`features` 校验频段、`evaluate` 校验模型与 CSP 输入类型、`validate` 校验 holdout 被试存在性 |
| 21 | **静态检查与测试现状** | `ruff check .` **All checks passed**（对三个 `code_version` 文件有**刻意**的 per-file-ignores，见 §5）；`pytest` **119 passed**（修复 SEC-003 / SEC-002 / SEC-011 / SEC-009 / SEC-010 后从 73 增至 119） |

---

## 五、偏离最佳实践记录（项目**刻意**为之，尊重并记录）

| # | 偏离 | 位置 | 理由（项目自述） | 风险与处置 |
|---|---|---|---|---|
| D-1 | **三个核心文件不得修改** | [`pyproject.toml`](pyproject.toml) per-file-ignores；[`tools/eeg_cache.py:101`](tools/eeg_cache.py) `code_version()` | `eeg_cache` / `eeg_dataset` / `eeg_pipeline` 参与 handle 哈希，**改一个字节 ⇒ 全部既有产物失效**。项目选择「保住证据链稳定」而放过若干 lint 问题 | **这是本报告最重要的约束**：SEC-001 与 SEC-005 中涉及 `eeg_cache.py` 的修复都被它挡住。处置：要么接受并文档化，要么承担全量重跑 |
| D-2 | **异常吞掉（4 处）** | `eeg_cache.py:236,248,306`；`eeg_dataset.py:234` | 索引写失败/产物不存在/单个被试下载失败，都不应中断主流程 | 风险：可能掩盖真实故障。缓解：前三处都不影响数字正确性；第四处会记入 `failures` 字段并回给 agent |
| D-3 | **`load()` 不因单被试失败而中止** | [`tools/eeg_dataset.py:234`](tools/eeg_dataset.py) | 「逐被试容错是刻意设计」——这是智能体「失败恢复」能力的输入 | 风险：可能静默少用被试。缓解：`failures` + `per_subject` 如实记录并进报告 |
| D-4 | **`.venv` 在开启 Smart App Control 的机器上跑不了 pytest** | [`docs/evidence/act4-20261004/conditions-log.md`](docs/evidence/act4-20261004/conditions-log.md) | 洁净环境的 venv 是拷贝出来的，SAC 拦截新创建的原生扩展副本；项目**拒绝关闭 SAC**（系统安全设置） | 已完整记录，并证明**不影响口径 A**（MCP 由主仓库 venv 运行）。<br>⚠️ **更正（2026-10-04 晚，修 SEC-008 时顺带查出）**：该拦截**已自行解除**——SAC 仍开着（`VerifiedAndReputablePolicyState = 1`），但环境 `.venv` 现在 `42 passed`、sklearn 原生扩展正常导入。**运行当时确实被拦（记录无误），但那是暂时性的**；已作为 §6b 补记写入 conditions-log，防止后来者把「当时被拦」误读成「现在也一定被拦」 |
| D-5 | **不做 TLS / HSTS / Secure Cookie** | — | **本项目无网络服务**，不涉及传输层 | **不适用**，按任务判定规则不上报 |
| D-6 | **`requirements.txt` 用下限写法** | [`requirements.txt`](requirements.txt) | 便于安装；精确复现由 `requirements-lock.txt` 承担，且 README 明确要求「复现数字请用锁文件」 | 风险：不用锁文件会版本漂移。已文档化 |
| D-7 | **`.env.example` 里的 `AGNES_*` 无代码读取** | [`.env.example`](.env.example) | 那是 AGH 侧变量，本项目代码不读（文件内已注明） | 非偏离，仅记录以免误判为「配置未使用」缺陷 |

---

## 六、附：本次审验的局限（如实说明）

1. **未加载到权威安全基线**（§1）——结论基于通用最佳实践，不是某个版本的官方 checklist。
2. **未做依赖 CVE 比对**——环境无离线 CVE 库，且不应凭记忆断言 CVE。
   建议后续在联网环境跑 `pip-audit -r requirements-lock.txt` 或 `safety check`。
   当前锁定版本：mne 1.13.2 · numpy 2.5.3 · scipy 1.18.1 · scikit-learn 1.9.1 ·
   pandas 3.0.6 · mcp 2.2.0。
3. **仓库外的支撑脚本只做了抽样**（`run-act4.ts`、`agh_unattended.ps1`）。
   本次会话已修掉 `agh_unattended.ps1` 的两个 bug（缺 UTF-8 BOM、参数名 `$Home` 撞只读自动变量），
   但**它们不在本仓库**，未纳入本报告的分级。
4. **动态测试未做**——没有对运行中的 MCP server 做模糊测试（fuzzing）。
   SEC-002 / SEC-006 的结论来自**静态逐行核对**，不是运行时利用验证。
