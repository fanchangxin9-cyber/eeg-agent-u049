# 第三幕 · 无人值守复现 · 台账（run-20261003）

> ⚠ **本目录为重建版。** 原目录于 2026-10-03 被误删——它**未进 git**（`git log --all` 无记录）、
> **回收站亦无**（属永久删除）。本次从 AGH 会话库的自动备份
> `~/.agh/data/sessions.backup-20261003.db` 重建：
>
> - `agh-session-p3abc.jsonl`、`agh-session-p3d.jsonl` —— 由 `scripts/export_session.py`
>   从备份库**逐事件精确重建**（同格式、同脱敏规则，可复核）。
> - `README.md`（本文）与 `summary.md` —— 据会话账本（提示词、工具调用、`eeg_defect_rate`
>   返回值）与 `docs/zero-signal.md` §8/§9 **重写**。其中数字**全部取自会话内工具返回**，
>   未自行计算、未从正文抄。
> - `logs/` —— 由会话账本**重新生成**的工具调用轨迹（原始 run log 未留存）。
>
> 重建日期：2026-10-03。重建不改动 `docs/zero-signal.md` 等正文任何数字。

## 本次要回答的问题

第三幕（零信号对照）的**四档**结果，用 **AGH SDK 无人值守**重跑，能否**逐 handle 复现**？

- 无人值守的意义：避免实验员知情造成的人为干扰，保证盲性纪律（见预注册「直测层」讨论）。
- 复现的判据：产物**内容寻址**（SHA-256）——同 `(源数据, seed, strategy, budget, n_perm)`
  必然得到同一 `eval_*` handle，也就必然是同一结果。故「同 handle」是机械证据，不靠肉眼比对。

## 运行信息

| 项 | 值 |
|---|---|
| 运行日期 | 2026-10-03 凌晨（北京时间）；源事件 `ts` 为 UTC（2026-10-02 下午），本文时间列同时给两者 |
| 路线 | ☑ **复现**（同参数；第三幕数字应与 `docs/zero-signal.md` §9.1 / §8.1 一致） |
| 执行方式 | **AGH SDK 无人值守**（非人工），`--profile local-dev`，`approvals.mode=off` |
| P3a/P3b/P3c 会话 | `agnes:local:local-dev:cli:workspace:326ab9666820d5a8`（1442 事件） |
| P3d 会话 | `agnes:local:local-dev:cli:workspace:8ef763dcb750ea1f`（495 事件） |
| P3d 工作目录 | `D:\暂存\p3d`（新工作区；原工作区会话因持久态分叉无法开新 turn，故改用干净工作区） |
| 数据源 | `raw_057280305171`（EEGMMIDB，被试 1–6，270 段，`is_synthetic=false`） |
| 模型 | agnes-3.0-flash |
| 参数 | `n_perm=30`、`alpha=0.05`；每档 `seed=1..20` |
| 技能 | `honest-lie`（第三幕配套方法，实验员侧） |

## 提示词（四段，逐字见会话导出）

| 阶段 | 会话 seq | 时间（UTC） | 要点 |
|---|---|---|---|
| P3a · budget=1 | 205 | 2026-10-02 17:15:57 | `budget=1, hill, seed=1..20`；串行；超时重发同参；跑完 `eeg_defect_rate` 汇总 |
| P3b · budget=4 | 642 | 2026-10-02 17:20:39 | `budget=4, hill, seed=1..20`；其余同上 |
| P3c · budget=24 · hill | 1041 | 2026-10-02 17:28:04 | `budget=24, hill, seed=1..20`；其余同上 |
| P3d · budget=24 · random + 合并 | 45（p3d 会话） | 2026-10-02 18:00:32 | `budget=24, random, seed=1..20`；跑完分别汇总 random 臂、hill 臂（既有 handle）、两臂合并 40 |

> 三段 P3a/P3b/P3c 跑在**同一条会话**里（连续三档）；P3d 因原工作区会话分叉，改在
> **新工作区 `D:\暂存\p3d`** 的新会话中运行，提示词里直接写入 hill 臂既有 20 个 handle，
> 以确保合并步骤有上下文。

## 时间线

阶段起点＝该档提示词到达时间，终点＝该轮 `turn/end`。时间为 UTC（括号内为北京时间 +8）。

| 阶段 | 开始（UTC / 北京） | 结束（UTC） | 耗时 | 工具调用 | 备注 |
|---|---|---|---|---|---|
| 探测回合 | 16:41:42 / 00:41:42 | 17:12:46 | — | `eeg_artifacts`×6 | 探针：确认 MCP 可用、找回 `raw_057280305171` |
| **P3a** budget=1 | 17:15:57 / 01:15:57 | 17:18:51 | 2 m 54 s | `eeg_trial_run`×20 + `eeg_defect_rate`×1 | 20/20 成功 |
| **P3b** budget=4 | 17:20:39 / 01:20:39 | 17:24:30 | 3 m 51 s | `eeg_trial_run`×20 + `eeg_defect_rate`×1 | 20/20 成功 |
| **P3c** budget=24·hill | 17:28:04 / 01:28:04 | 17:40:11 | 12 m 07 s | `eeg_trial_run`×20 + `eeg_defect_rate`×1 | 20/20 成功 |
| P3d 探测 | 17:59:46 / 01:59:46 | 17:59:51 | 5 s | `eeg_artifacts`×1 | 新会话找回源数据 |
| **P3d** budget=24·random + 合并 | 18:00:32 / 02:00:32 | 18:13:34 | 13 m 02 s | `eeg_trial_run`×20 + `eeg_defect_rate`×3 | 20/20 成功；含两臂合并 |

> 三档 P3a–P3c 之间夹着约 2 分钟的人工/调度间隙（17:18:51→17:20:39、17:24:30→17:28:04），
> 计入上表起点与终点，未计入单档耗时。

## 结果（全部取自 `eeg_defect_rate` 返回值，未自行计算）

| 档 | seed | n | defect_rate | wilson_ci95 | n_significant | observed_mean | median_p | analytical_baseline | 会话 |
|---|---|---|---|---|---|---|---|---|---|
| P3a budget=1 | 1–20 | 20 | **0.10** | [0.0279, 0.301] | 2 | 0.4944 | 0.629 | 0.0323 | p3abc |
| P3b budget=4 | 1–20 | 20 | **0.20** | [0.0807, 0.416] | 4 | 0.5329 | 0.129 | 0.1176 | p3abc |
| P3c budget=24·hill | 1–20 | 20 | **0.50** | [0.2993, 0.7007] | 10 | 0.5616 | 0.0484 | 0.4444 | p3abc |
| P3d budget=24·random | 1–20 | 20 | **0.55** | [0.3421, 0.7418] | 11 | 0.5608 | 0.0323 | 0.4444 | p3d |
| P3d 合并（hill+random） | 1–20 ×2 | 40 | **0.525** | [0.375, 0.6706] | 21 | 0.5612 | 0.0323 | 0.4444 | p3d |

> P3d 的 `eeg_defect_rate` 被调用 3 次：random 臂（20）、hill 臂（20，既有 handle 复核）、
> 两臂合并（40）。上表 random 行取第 1 次返回，合并行取第 3 次返回。

## 复现判定

「归档值」取 `docs/zero-signal.md` §9.1（budget=1/4）与 §8.1/§8.2（budget=24）。

| 项 | 本次（无人值守） | 归档值 | 是否一致 |
|---|---|---|---|
| budget=1 defect_rate | 0.10（2/20） | 0.10（2/20） | ✓ |
| budget=4 defect_rate | 0.20（4/20） | 0.20（4/20） | ✓ |
| budget=24·hill defect_rate | 0.50（10/20） | 0.50（10/20） | ✓ |
| budget=24·random defect_rate | 0.55（11/20） | 0.55（11/20） | ✓ |
| budget=24 合并 defect_rate | 0.525（21/40） | 0.525（21/40） | ✓ |
| observed_mean（合并） | 0.5612 | 0.5612 | ✓ |
| median_p（合并） | 0.0323 | 0.0323 | ✓ |

**判定：第三幕四档逐 handle 完全复现。**

- 四档的 `eval_*` handle 与归档 `docs/zero-signal.md` §9.5 / §8.5 所列**逐条相同**
  （清单见 `summary.md`）。产物内容寻址，同参数即同 handle——这是「同参数 → 同数字」的机械证据。
- 两臂 observed_mean 之差（hill − random）= 0.5616 − 0.5608 = **+0.0008**，与 §8.2 一致：
  零信号上无可辨别差别，偏差不依赖搜索的智能性。

## 审批与异常记录（如实填，不静默跳过）

| # | 阶段 | 现象 | 处理 | 结果 |
|---|---|---|---|---|
| 1 | p3abc 探测回合 | 3 次 `approval/asked`（seq 43、78、112） | 每次紧随同毫秒的 `approval/decided`——无人值守下策略自动放行，未阻塞 | 无影响 |
| 2 | 全部 P3 档 | **零 MCP 超时** | —— | 80/80 次 `eeg_trial_run` 一次成功返回，**无重发** |

> 对照：`run-20261002` 人工轮（Web UI）在 budget=1/4 两档记录 **7 次 MCP 超时**、budget=24
> 两臂另有多起超时重发。本次无人值守全程零超时——原因之一是 SDK 侧单发串行、无并发堆积。
> 无论超时与否，均**无静默跳过**，各档最终 n 均为 20/20。

## 证据落点

| 产物 | 位置 |
|---|---|
| P3a/P3b/P3c 会话导出（1442 事件，已脱敏） | `agh-session-p3abc.jsonl`（本目录） |
| P3d 会话导出（495 事件，已脱敏） | `agh-session-p3d.jsonl`（本目录） |
| 结果汇总（含 handle 清单） | `summary.md`（本目录） |
| 工具调用轨迹（重建） | `logs/p3abc-toolcalls.log`、`logs/p3d-toolcalls.log` |
| 会话源（备份库） | `~/.agh/data/sessions.backup-20261003.db`（重建后未改动） |
| 对照正文 | `docs/zero-signal.md` §8、§9 |

> 导出/脱敏由 `scripts/export_session.py` 执行（规则写在代码里、可复核）；
> 本次重建以 `AGH_HOME` 指向备份库的临时副本运行该脚本，**未触碰**当前 `sessions.db`。