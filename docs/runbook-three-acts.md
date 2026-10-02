# 三幕完整运行手册（AGH Web UI + 录屏）

> **用途**：把项目**从头到尾**在 AGH 里完整跑一遍，作为一次「权威运行」，
> 同时录屏剪出演示视频。
> 本手册给出**逐条可粘贴的提示词**、每条的预期时长与预期产物、以及要拍的镜头。

---

## 0. 先读这一段：这次运行会得到什么、不会得到什么

**产物是内容寻址的。** handle 由 `(代码版本, 操作, 上游 handle, 参数, 数据指纹)` 的
SHA-256 决定（`tools/eeg_cache.py` → `put()`）。所以：

| 这次运行 | 结果 |
|---|---|
| 用**与现有文档相同的参数**（本手册默认） | **复现**——数字与 `docs/` 里已有的一致，不产生新数字 |
| 用**新的 seed 或更大的规模** | 产生**新数字**，需要重新回填文档 |

**代码版本是哈希的一部分。** `code_version()` 取
`tools/eeg_pipeline.py` / `eeg_dataset.py` / `eeg_cache.py` 三个文件的 SHA-256 前 12 位。
**运行前后都不要改这三个文件**，否则所有 handle 与数字都会变，复现即失效。
（当前代码版本 = `20b202c7ffe4`，与现有产物一致；P0 会让 agent 顺带验一遍。）

本手册默认走**复现**路线。复现本身是有价值的证据：

1. **证明流程可复现**——同一输入两次运行给出逐位相同的结果，这是参赛材料里
   最有说服力的可复现性证据。
2. **得到一份连续、干净的会话记录**（第一幕 → 第二幕 → 第三幕在同一会话里），
   比此前分散在多轮、多会话里的记录更易核验。
3. **补齐 §9.5 的 handle 清单**（已从产物索引提取，见 `docs/zero-signal.md` §9.5）。

> ⚠️ **如果你想要「新数字」**（例如把 n 从 20 提到 40、或换一批 seed），
> 在本手册里把所有 `seed=1..20` 改成新范围即可，但**必须**同时准备回填
> `README.md` / `docs/report.md` / `docs/zero-signal.md` / `docs/finals.md` /
> `docs/submission.md`。**不要**把新数字和旧数字混在同一份文档里。

---

## 1. 运行前自检（**不通过不要开始**）

在 IDE 终端（不是 AGH 会话终端）执行：

```powershell
# 1) 数据已缓存（应看到 S001–S006 各 3 个 .edf，共 18 个；EDF 在每被试的子目录里，
#    所以要加 -Recurse，否则只列出 6 个目录、看不到文件）
dir $env:USERPROFILE\mne_data\EEGBCI\MNE-eegbci-data\files\eegmmidb\1.0.0\ -Recurse -Filter *.edf

# 2) 盲性验收（实验有效性闸门，必须 17/17）
.venv\Scripts\python.exe scripts\check_blinding.py

# 3) 测试套件（应全绿）
.venv\Scripts\python.exe -m pytest tests\ -q
```

在 AGH Web UI 里确认：

- 设置 → MCP：`eeg-agent` **已启用 / 连接正常**，工具数 **13**。
- Skills 页：`eeg-analysis` 与 `honest-lie` 均已审核并启用。
- 新建会话时**工作目录必须选 `D:\暂存\source`**（否则读写 `docs/` 会错位）。

**录制准备**：OBS 1080p、保留鼠标轨迹、字体放大；不要露 API Key / 邮箱 / 学号。

---

## 2. 三幕提示词（逐条粘贴）

> 每条提示词都是**一个完整的用户回合**。粘贴 → 等它跑完 → 粘下一条。
> 会话上下文会保留，所以后续提示词不需要重复前面的背景。

### 会话步数上限（为什么必须分条）

单轮请求上限 **80 步**（`max_steps`），每次 `eeg_trial_run` 占 1 步。
第三幕 80 次试验塞不进一轮，因此按 budget 档位拆成 4 条。

---

### P0 · 运行前自检

> 预期：约 1–2 分钟（含 pytest）。要拍的镜头：MCP 设置页 13 个工具、盲性 17/17、pytest 全绿。

```
【P0 · 运行前自检】这是一次完整三幕运行的开始。只做自检，不要开始分析。

依次完成并用清单汇报：
1. 用 eeg_fetch(subjects=[1,2,3,4,5,6], task="left_vs_right_imagery", runs=[4,8,12])
   取数（数据已缓存，应当很快）。确认返回的 raw handle 是 **raw_057280305171**。
   这是**内容寻址的复现校验**：若 handle 不同，说明数据或代码版本有变，
   立刻停下报告，不要继续。
   （备选：eeg_artifacts(kind="raw", limit=100) 也能列出它；默认 limit=10 看不到，
   因为它之后又生成了 29 个 raw 产物。）
2. 用 shell 运行盲性验收：.venv\Scripts\python.exe scripts\check_blinding.py
   必须全部通过（17/17）。不通过就停下并报告，不要继续。
3. 用 shell 运行测试套件：.venv\Scripts\python.exe -m pytest tests\ -q
   记录通过数/总数与耗时。
4. 汇总四件事：可用 MCP 工具数（应为 13）、数据 handle（应为 raw_057280305171）、
   盲性结果、测试结果。

只汇报，不要开始第一幕。等我说「开始第一幕」。
```

---

### P1 · 第一幕：把工具做出来（完整分析）

> 预期：约 10–13 分钟。要拍的镜头：`todo` 规划 → 诊断 → 迭代环（分数变化 + 调整理由）→ 两协议并排 → 置换检验分批合并 → pytest 自证 → 异常分支 → 写报告。
>
> **提示词里刻意不写窗口、阈值、频带**——让 agent 自己从诊断结论推出来，
> 否则「反馈调整」这个得分点会退化成「照参数执行」。

```
【P1 · 第一幕】开始第一幕。

点名 eeg-analysis 技能，完成一次完整的 EEG 运动想象解码分析。
这是参赛作品的演示，请把过程做扎实。

【第一步：先规划】
用 todo 工具列出你计划执行的步骤，再开始动手。

【第二步：分析】
分析 EEGMMIDB 被试 1-6 的运动想象数据，判断左右手能否区分。
要求：
- 先做质量诊断，根据诊断结论决定预处理方案，不要套用固定参数
- 每调一次配置就汇报指标，并写清「观察 → 决定 → 理由 → 下一步」
- 两种交叉验证协议 within_subject 和 cross_subject 都跑并分别报告
- 做置换检验证明结果不是流程泄漏造成的。注意 p 值下限是 1/(n+1)，
  次数不足会把真实效应误判为不显著；单次调用装不下时按 skill 里的办法
  分批再合并（每批 10 次、不同 seed、模型/协议/折数一致）
- 与冻结基线对比，给出增益并说明来源

【第三步：自查】
分析完成后，用 shell 工具运行项目的测试套件自证工具链正常：
  .venv\Scripts\python.exe -m pytest tests\ -q
并解释三类测试（正常/边界/失败）各自覆盖了什么。

【第四步：异常处置】
过程中如果任何步骤失败，判断它是否可恢复：可恢复就调整后重试，
不可恢复就记录原因并说明用什么替代证据弥补，不要跳过不提。

【第五步：出报告】
用 eeg_evidence 收集所有可引用的数字，然后写中文报告到 docs/report.md，
六个部分：数据概况、方法（含为什么这样选）、结果、验证、与基线对比、局限。
报告里每个数字都必须能在 evidence 的 claims 里找到，并标明用的是哪种协议。
局限部分如实写被试数、个体差异、多重比较等问题。
```

**异常分支**（第一幕跑完后紧接着发，专门拍「自愈」）：

```
请查看一下 eval_000000000000 这个结果的详细内容
```

> 它会收到 `E_HANDLE_NOT_FOUND`，返回值里带一份最近可用的 handle 列表——
> **看它怎么用这份清单自愈**，这才是要拍的画面。

---

### P2 · 第二幕：审这份报告（选择偏差）

> 预期：约 1–2 分钟（纯推理，无重计算）。要拍的镜头：它逐条列出实际比较过的配置与 handle，并承认「p 值未做选择校正」。

```
【P2 · 第二幕】现在切换角色：你不是分析员，是审计员。

审查你刚写出的 docs/report.md（第一幕产物），回答并给出依据：

1. 这份报告里的「显著」结论（p 值）是在多少个候选配置里挑出来的？
   把你在第一幕实际比较过的配置逐条列出：配置内容 + 对应 eval_* handle + 指标。
2. 这个 p 值有没有为「选择」这一步做校正？如果没有，说明偏差方向（乐观还是保守）。
3. 抽查 3 个报告里的数字，给出它们各自的 eval_* handle，确认都能在
   eeg_evidence 的 claims 里找到。
4. 用一句话回答引子里的问题：这份报告的「显著发现」里，有多少来自数据、
   有多少来自「挑」这个动作？并说明为什么这个问题不能靠统计校正回答、
   只能靠实验测出来。

不要修改 docs/report.md。这是审计，不是重写。
```

---

### P3a · 第三幕：零信号试验台 · budget=1（不搜索）

> 预期：约 5–8 分钟（单次约 10–20 秒）。要拍的镜头：声明停止准则 → 串行逐个 `eeg_trial_run` → `eeg_defect_rate` 汇总。

```
【P3a · 第三幕 · budget=1】点名 honest-lie 技能。从现在起你是零信号对照实验的实验员。

先写下停止准则，然后严格照做：
- 本档：budget=1（不搜索）、n_perm=30、strategy=hill、seed=1..20，共 20 次试验。
- 数据源用 raw_057280305171（用 eeg_artifacts 找回）。
  不要手工造孪生体——eeg_trial_run 会按 seed 自己造。
- 必须串行：一次只发一个 eeg_trial_run，等它返回再发下一个。不要并行。
- 遇到 MCP 超时：等待约 2 分钟后**重发同一组参数**（产物内容寻址，可复现），
  并记录是第几次、什么错。不要静默跳过。
- 把每次返回的 eval_* handle 按 seed 顺序记下来。

20 次跑完后：
1. 调 eeg_defect_rate(trial_handles=[...20 个 handle...]) 汇总，报出
   defect_rate、wilson_ci95、observed_mean、median_p、analytical_baseline。
2. 把 20 个 handle 按 seed 升序列出。

每个数字只许来自工具返回，不要自己算。
```

---

### P3b · 第三幕 · budget=4

> 预期：约 10–15 分钟（单次约 20–60 秒）。

```
【P3b · 第三幕 · budget=4】继续第三幕，跑 budget=4 这一档。

- budget=4、n_perm=30、strategy=hill、seed=1..20，共 20 次试验。
- 数据源仍用 raw_057280305171。同样串行、超时按同一组参数重发、记录错误。
- 跑完后用 eeg_defect_rate 汇总，报出 defect_rate、wilson_ci95、observed_mean、
  median_p、analytical_baseline，并把 20 个 handle 按 seed 升序列出。
```

---

### P3c · 第三幕 · budget=24 · hill 臂

> 预期：约 60–90 分钟（单次 2–4 分钟）。**这是最长的一段**，中途会有超时重试，如实记录。

```
【P3c · 第三幕 · budget=24 · hill 臂】继续第三幕，跑 budget=24 的 hill 臂。

- budget=24、n_perm=30、strategy=hill、seed=1..20，共 20 次试验。
- 数据源仍用 raw_057280305171。串行执行；MCP 超时等待约 2 分钟后重发同一组参数，
  记录每次超时（第几次、什么错）。
- 跑完后用 eeg_defect_rate 汇总这一臂，报出 defect_rate、wilson_ci95、
  observed_mean、median_p、analytical_baseline，并把 20 个 handle 按 seed 升序列出。
```

---

### P3d · 第三幕 · budget=24 · random 臂 + 合并

> 预期：约 60–90 分钟。跑完这一臂后做配对比对与合并汇总。

```
【P3d · 第三幕 · budget=24 · random 臂 + 合并】

- budget=24、n_perm=30、strategy=random、seed=1..20，共 20 次试验
  （seed 必须与 hill 臂相同，这样才是配对比对）。
- 同样串行、超时重发、记录错误。
- 跑完后：
  1. 用 eeg_defect_rate 汇总 random 臂（20 个 handle），报出全部汇总字段。
  2. 再把 hill 臂与 random 臂共 40 个 handle 一起汇总，得到 budget=24 的合并结果。
  3. 给出两臂 observed_mean 之差（hill − random），并判断「有没有可辨别的差别」。
  4. 把 random 臂 20 个 handle 按 seed 升序列出。
```

---

### P4 · 收尾：汇总与落盘

> 预期：约 2 分钟。要拍的镜头：三档结果表 + 结论一句话。

```
【P4 · 收尾】把三幕的结论汇总。

1. 给一张表：budget=1 / 4 / 24 三档的 defect_rate、wilson_ci95、observed_mean、
   median_p、analytical_baseline，以及 budget=24 两臂（hill / random）的分列。
   所有数字取自 eeg_defect_rate 的返回。
2. 用 eeg_evidence 收集第一幕可引用的数字，列出 claims 里的 handle。
3. 把上面的表、三档 handle 清单、以及每档的运行记录（超时次数与处理）写进
   docs/evidence/run-20261002/summary.md（若目录不存在就创建）。
4. 用一句话回答引子：这套「不会撒谎」的流程，在完全没有信号的数据上，
   把虚报率抬到了多少；搜索规模越大是否越高。

不要修改 docs/report.md / docs/zero-signal.md / README.md——那些由我统一回填。
```

---

## 3. 运行时长与镜头配比

| 阶段 | 预期时长 | 视频镜头（建议保留） |
|---|---|---|
| P0 自检 | 1–2 min | MCP 13 工具、盲性 17/17、pytest 全绿 |
| P1 第一幕 | 10–13 min | 规划 → 诊断 → 迭代 2–3 轮 → 两协议 → 置换分批合并 → pytest → 异常自愈 → 报告 |
| P2 第二幕 | 1–2 min | 它逐条列出配置与 handle、承认未校正 |
| P3a budget=1 | 5–8 min | 停止准则 → 串行试验 → 汇总表 |
| P3b budget=4 | 10–15 min | 同上（可快进） |
| P3c budget=24 hill | 60–90 min | 只保留首尾 + 超时重试那一次 |
| P3d budget=24 random | 60–90 min | 同上 + 配对比对结论 |
| P4 收尾 | 2 min | 三档表 + 一句话结论 |

**合计约 2.5–3.5 小时**（大部分是 budget=24 的串行试验）。

> **剪辑界线**：剪掉等待是编辑，编造流程是造假。
> 可以快进/跳过重复等待、用字幕交代「此处省略 N 次试验」；
> **不能**拼接出没真正发生的流程，**不能**篡改任何数字或界面。

---

## 4. 故障与超时处置（照此办，并如实记录）

| 情况 | 处置 |
|---|---|
| `eeg_trial_run` 超时 / `OVERLOADED` | 等约 2 分钟让 MCP 空闲，**重发同一组参数**；记录第几次、什么错 |
| `E_HANDLE_NOT_FOUND` | 读 `suggestions`，或 `eeg_artifacts` 找回有效 handle |
| 单轮步数用尽（80 步） | 会话里发「继续，接着跑 seed=X 到 Y」 |
| agent 绕圈 / 卡住 | 如实重录，不要用剪辑掩盖；必要时砍掉该镜头保证整体流畅 |
| 数据未缓存 | **不要**在录制时等下载（约 11 分钟/被试）——回到 §1 先下好 |

---

## 5. 跑完之后（由我统一回填）

运行结束后，把 `docs/evidence/run-20261002/summary.md` 与会话导出交回，我据此：

1. 导出并脱敏会话记录 → `docs/evidence/agh-session*.jsonl` 与 `-trace.md`
   （`scripts/export_session.py` + `scripts/summarize_session.py`）。
2. 核对新数字与 `README.md` / `docs/report.md` / `docs/zero-signal.md` /
   `docs/finals.md` / `docs/submission.md` 是否一致；
   - **复现路线**：一致则不动数字，只补「已复现」说明。
   - **新数字路线**：逐处替换，并检查全文无旧值残留。
3. 复查：`grep -rnE "0\.[6-9][0-9]|accuracy *= *[0-9]" docs/ README.md`
   （确认没有未经验证的指标残留）。
