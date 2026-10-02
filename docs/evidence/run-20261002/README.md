# 三幕权威运行 · 台账（run-20261002）

> 本次运行按 `docs/runbook-three-acts.md` 执行：AGH Web UI + 录屏，三幕一条会话跑完。
> 台账由人工填写；数字汇总见同目录 `summary.md`（P4 由 agent 写入）。
> 时间列同时给 UTC 与北京时间（源事件 `ts` 为 UTC，此处换算 +8，便于回查）。
> 复盘所用的完整会话诊断包为 `agh-diagnostics-10c4cbf7-20261002-154248`
> （16 002 事件，含父会话，含 PII）。**该包已移出仓库**，存放于仓库之外，见本文末「证据落点」。

## 运行信息

| 项 | 值 |
|---|---|
| 运行日期 | 2026-10-02 |
| 路线 | ☑ **复现**（同参数；第三幕数字应与现有文档一致） |
| AGH 会话 ID | 运行会话（fork）`10c4cbf7c489d7845d847c6bbbe65dea` |
| 完整会话键 | `agnes:fork:10c4cbf7c489d7845d847c6bbbe65dea:10c4cbf7c489d7845d847c6bbbe65dea%3A0453c107-139a-40b1-9356-68de21eaeee1%3A1` |
| 父会话 | `0453c107-139a-40b1-9356-68de21eaeee1`（本次运行自其 seq 4443 处分叉） |
| 工作目录 | `D:\暂存\source` |
| 模型 | agnes-3.0-flash |
| MCP 工具数 | **13**（P0 实测） |
| 盲性验收 | **17/17**（P0 实测） |
| pytest | **56 passed**（P0 实测，10.13 s） |

## 时间线

阶段起点＝该阶段提示词事件的时间，阶段终点＝下一阶段提示词的到达时间（含人工操作间隙）。

| 阶段 | 开始（UTC） | 开始（北京） | 结束（UTC） | 耗时 | 会话事件 | 备注 |
|---|---|---|---|---|---|---|
| P0 自检 | 14:13:08 | 22:13:08 | 14:14:24 | 1 m 16 s | seq 13367→13437 | MCP 13 / 盲性 17/17 / pytest 56 passed；`eeg_fetch`→`raw_057280305171` |
| P1 第一幕 | 14:14:24 | 22:14:24 | 14:23:50 | 9 m 26 s | seq 13437→13854 | `eeg_evaluate`×4、`eeg_validate`×4、`eeg_inspect`×3；主结果 **0.5815**（`eval_8c77857b35a5`） |
| P2 第二幕 | 14:23:50 | 22:23:50 | 14:24:25 | 0 m 35 s | seq 13854→13876 | 审 `docs/report.md`：数出候选配置数、指出未校正 p |
| P3a budget=1 | 14:24:25 | 22:24:25 | 14:32:13 | 7 m 48 s | seq 13876→14308 | `eeg_trial_run`×20 + `eeg_defect_rate`×1；0 超时；2/20 显著 |
| P3b budget=4 | 14:32:13 | 22:32:13 | 14:39:30 | 7 m 17 s | seq 14308→14726 | `eeg_trial_run`×20 + `eeg_defect_rate`×1；0 超时；4/20 显著 |
| P3c budget=24·hill | 14:39:30 | 22:39:30 | 15:21:58 | 42 m 28 s | seq 14726→15457 | `eeg_trial_run`×28（20 成功 + **8 次超时重发**）；10/20 显著 |
| P3d budget=24·random | 15:21:58 | 23:21:58 | 15:39:24 | 17 m 26 s | seq 15457→15894 | `eeg_trial_run`×20 + `eeg_defect_rate`×2（含两臂合并）；0 超时；11/20 显著 |
| P4 收尾 | 15:39:24 | 23:39:24 | 15:41:46 | 2 m 22 s | seq 15894→16002 | `eeg_evidence` 复核 9 个 handle；写 `summary.md`；`turn/end` |
| **合计** | 14:13:08 | 22:13:08 | 15:41:46 | **1 h 28 m 38 s** | — | — |

> P0 曾在 14:09:14 先下发一次，随即被用户取消（seq 13349「把这次已取消的对话忘掉」），
> 14:13:08 重新下发并全程通过；上表取第二次。

## 异常与超时记录（如实填，不静默跳过）

| # | 阶段 | seed | 错误 | 处理 | 结果 |
|---|---|---|---|---|---|
| 1 | P3c budget=24·hill | 8 | `mcp server eeg-agent unavailable: MCP error -32001: Request timed out`，**连续 8 次** | 每次等待约 30 s–2 min 后**重发同一组参数**；期间用轻量 `eeg_artifacts` 探测确认 MCP 已恢复响应（重型调用超时、轻量调用正常） | 第 8 次重发命中 `eval_6c79fd3a3583`（n_evaluated=24，observed=0.5554，p=0.0323，significant=true）；该档最终 20/20 |
| 2 | P0（预演） | — | 首次 P0 自检后用户取消（“先把这次已取消的对话忘掉”） | 重新下发 P0 | 第二次 P0 全项通过 |

- 其余各档本轮**零超时**；三档最终均为 **20/20**，无静默跳过、无失败丢失。
- 超时根因：budget=24 单次试验耗时超客户端 2 分钟窗口（服务端仍在计算），非数据/工具缺陷。
- 更早的一次预算曲线批（2026-10-02 12:05–12:44 UTC，见 §证据落点）曾记录 7 次超时
  （budget=1：seed 8/10/11/15；budget=4：seed 11/15/16）；本轮重跑未再出现。

## 复现判定

「文档现有值」取本次运行前 `docs/report.md`（HEAD 版）与 `docs/zero-signal.md` 中的值。

| 项 | 本次值 | 文档现有值 | 是否一致 |
|---|---|---|---|
| 第一幕 within_subject 平衡准确率 | **0.5815**（`eval_8c77857b35a5`） | 0.6078（`eval_e1f105361a73`） | ✗ 不一致 |
| 第一幕 cross_subject 平衡准确率 | **0.5142**（`eval_45e9e5f5c119`） | 0.5083（`eval_eb605cf8fcb9`） | ✗ 不一致 |
| 第一幕置换检验 p（30 次合并） | **0.0323**（`eval_7e9cd9efe979`） | 0.0323（`eval_cb6ff2ae1fea`） | ✓ 一致 |
| 第一幕冻结基线 bandpower+LDA | **0.5667**（`eval_97c24b8b38c1`） | 0.5667（同 handle） | ✓ 一致（同 handle） |
| 第三幕 budget=1 defect_rate | **0.10**（2/20） | 0.10 | ✓ 一致 |
| 第三幕 budget=4 defect_rate | **0.20**（4/20） | 0.20 | ✓ 一致 |
| 第三幕 budget=24 defect_rate | **0.525**（21/40） | 0.525 | ✓ 一致 |

**判定：第三幕完全复现；第一幕不一致，且不一致有确定原因。**

- **第三幕（零信号）逐 handle 复现。** 本次 budget=1/4 两档产出的 40 个 `eval_*`
  handle 与更早一批（12:05 UTC）**完全相同**；budget=24 两臂亦复现同一批 handle。
  产物内容寻址（SHA-256），同参数即同 handle —— 这是「同参数 → 同数字」的机械证据。
- **第一幕的差异来自 agent 的配置选择漂移，不是数据或工具。**
  - 两次运行提示词相同、数据相同（`raw_057280305171`）、冻结基线 handle 相同（0.5667）。
  - 差异出在预处理：上次 `crop_sec=[0,4]`、`reject_uv=200` → `clean_ef8447bc1684`（270→269 段）；
    本次 `crop_sec=[0.5,3.5]`、`reject_uv=150` → `clean_c1f187bc3587`（270→251 段）。
  - 结果：within_subject **0.6078 → 0.5815**（Δ = −0.0263），cross_subject **0.5083 → 0.5142**。
  - 结论：同一提示词下，agent 的预处理/窗口选择并非确定，主结果随之漂移 ~0.03。
    已按决策「两次并列，把漂移本身写成结论」写入 `docs/report.md` §7 与 `README.md`。

> 一致项 → 已在 `README.md` / `docs/zero-signal.md` 补「已复现（run-20261002）」；
> 不一致项 → 已按上文说明原因，未替换数字，改为两次并列。

## 证据落点

| 产物 | 位置 |
|---|---|
| 完整会话诊断包（含 PII，**存于仓库之外**，不进仓库） | `d:\暂存\agh-diagnostics-10c4cbf7-20261002-154248`（16 002 事件，含父会话） |
| 更早一次导出的完整快照（含 PII） | `docs/evidence/full/`（`.gitignore` 排除） |
| 本次运行会话（fork，11 559 事件，已脱敏） | `docs/evidence/agh-session.jsonl` |
| 父会话（4 444 事件，已脱敏） | `docs/evidence/agh-session-act1-20261001.jsonl` |
| 人类可读调用轨迹 | `docs/evidence/agh-session-trace.md` |
| 第三幕数字汇总（P4 由 agent 写） | `docs/evidence/run-20261002/summary.md` |
| 预算曲线图 | `docs/figures/zero-signal-budget-curve.svg` |

> 导出/脱敏由 `scripts/export_session.py` 执行（规则写在代码里、可复核）；
> 轨迹由 `scripts/summarize_session.py` 生成。仓库内两份 `agh-session*.jsonl`
> 的工具调用序列与诊断包逐条一致（fork 部分 622 次调用，已校验）。
