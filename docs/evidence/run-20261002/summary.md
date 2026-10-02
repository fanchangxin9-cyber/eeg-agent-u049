# 第三幕 · 零信号对照实验 运行记录（run-20261002）

> 数据源：`raw_057280305171`（EEGMMIDB v1.0.0，被试 1–6，runs 4/8/12，left_vs_right_imagery，270 段，真实数据）
> 实验员侧记录；所有虚报率数字均取自 `eeg_defect_rate` 返回，未自行计算。
> 孪生体由 `eeg_trial_run` 按 seed 内部生成，未手工构造；孪生体不携带"我是孪生体"标记，meta/params 与真品逐字节相同（盲性 17/17 已验收）。

## 1. 三档对照表（全部字段取自 `eeg_defect_rate`）

### 各档单独汇总（每档 20 次试验，seed 1..20）

| 档 | 策略 | n | n_significant | defect_rate | wilson_ci95 | observed_mean | median_p | analytical_baseline |
|---|---|---|---|---|---|---|---|---|
| budget=1 | hill | 20 | 2 | **0.10** | [0.0279, 0.301] | 0.4944 | 0.629 | 0.0323 |
| budget=4 | hill | 20 | 4 | **0.20** | [0.0807, 0.416] | 0.5329 | 0.129 | 0.1176 |
| budget=24 | hill | 20 | 10 | **0.50** | [0.2993, 0.7007] | 0.5616 | 0.0484 | 0.4444 |
| budget=24 | random | 20 | 11 | **0.55** | [0.3421, 0.7418] | 0.5608 | 0.0323 | 0.4444 |
| **budget=24 合并** | hill+random | 40 | 21 | **0.525** | [0.375, 0.6706] | 0.5612 | 0.0323 | 0.4444 |

### budget=24 两臂配对（同 seed，可配对比对）

| 臂 | observed_mean | defect_rate | median_p |
|---|---|---|---|
| hill | 0.5616 | 0.50 | 0.0484 |
| random | 0.5608 | 0.55 | 0.0323 |
| **hill − random** | **+0.0008** | −0.05 | +0.0161 |

**可辨别性判断**：两臂 observed_mean 之差仅 +0.0008（远小于折间 std 0.019），
Wilson 区间大幅重叠；在零信号数据上，hill（自适应爬山）与 random（纯抽样）
产出的"最好配置"均值几乎相同。**无可辨别的差别**——偏差来自"搜索/挑"这个
动作本身（把噪声抬成高分），而非"会推理的搜索比笨搜索强"。即便随机抽样，
只要搜 24 个再挑最好报 p，虚报率同样 0.55。

### 关键结论
1. **虚报率随搜索规模单调上升**：budget=1 → 0.10；budget=4 → 0.20；budget=24 → 0.525（合并）。
   即便不搜索（budget=1），30 次置换的 p 下限 1/31=0.0323 本身使"显著"宽于名义 0.05。
2. **各档实测值都高于各自 analytical_baseline**（0.10 vs 0.0323；0.20 vs 0.1176；0.525 vs 0.4444），
   偏差随规模放大，且不止于"选择"——还有配置异质 / 自适应搜索的额外贡献。
3. 这套"不会撒谎"的流程在**完全没有信号**的数据上，仍能报出 21/40（合并）的"显著"。

## 2. 第一幕（审流程前的基线分析）可引用数字 · eeg_evidence claims

`eeg_evidence` 对上述 9 个 handle 的调用返回 `refused: []`（无合成数据、全部可放行）：

| handle | 来源工具 | 对应配置 |
|---|---|---|
| `eval_f3e2ae7ae619` | eeg_evaluate | bandpower+LDA, within_subject（0.5785） |
| `eval_1ad0ccd0f7c6` | eeg_evaluate | CSP+LDA, within_subject（0.5806） |
| `eval_45e9e5f5c119` | eeg_evaluate | CSP+LDA, cross_subject（0.5142） |
| `eval_8c77857b35a5` | eeg_evaluate | CSP+LDA, 窗口[0.5,3.5], within_subject（0.5815，主结果） |
| `eval_5a7ec8bf3159` | eeg_validate | 置换 batch1（seed=1, n=10） |
| `eval_1308dba6b12e` | eeg_validate | 置换 batch2（seed=2, n=10） |
| `eval_19b187557ac5` | eeg_validate | 置换 batch3（seed=3, n=10） |
| `eval_7e9cd9efe979` | eeg_validate | 合并 30 次置换（p=0.0323） |
| `eval_97c24b8b38c1` | eeg_evaluate | 冻结基线 bandpower+LDA（0.5667） |

（claim 明细：C1 balanced_accuracy_mean、C2 std、C3 accuracy、C4 f1_macro、C5 cohen_kappa 等
均带 handle + tool + config，全部 `refused: []`。）

## 3. 各档 handle 清单（按 seed 升序）

### budget=1 · hill（20）
| seed | handle |
|---|---|
| 1 | `eval_2117a113ea12` |
| 2 | `eval_7adb03da01a9` |
| 3 | `eval_be3fc9bca51b` |
| 4 | `eval_2d88c8cf95af` |
| 5 | `eval_022e9395f2d7` |
| 6 | `eval_2f2a89a85b25` |
| 7 | `eval_dd97aac4fb2f` |
| 8 | `eval_78b558773456` |
| 9 | `eval_c049acd5b92e` |
| 10 | `eval_cdb73b157d24` |
| 11 | `eval_7b398734f7ca` |
| 12 | `eval_e1414aeeb761` |
| 13 | `eval_355d3f1a063f` |
| 14 | `eval_cdca91bbbcaf` |
| 15 | `eval_846bff3f6fe1` |
| 16 | `eval_7b9221cc9d2d` |
| 17 | `eval_672d20b94f47` |
| 18 | `eval_2344850450dd` |
| 19 | `eval_16ae69f88608` |
| 20 | `eval_6a0b1afb1c2b` |

### budget=4 · hill（20）
| seed | handle |
|---|---|
| 1 | `eval_8f9b66895f75` |
| 2 | `eval_dadbab309f0c` |
| 3 | `eval_dffe8f681ffb` |
| 4 | `eval_c764ea093287` |
| 5 | `eval_5028fcd0be75` |
| 6 | `eval_c4e86a9ab7cf` |
| 7 | `eval_a69e79dbdd67` |
| 8 | `eval_afafe7b2089c` |
| 9 | `eval_2ad64a4d0c04` |
| 10 | `eval_6be1bf01adb0` |
| 11 | `eval_9bfed7fbce65` |
| 12 | `eval_e2274de919ed` |
| 13 | `eval_a5723d05afbc` |
| 14 | `eval_d3903c9721c0` |
| 15 | `eval_960e04818139` |
| 16 | `eval_8415979d1c32` |
| 17 | `eval_50e59c4fcb9e` |
| 18 | `eval_2f5fc766dc69` |
| 19 | `eval_afcf928ed184` |
| 20 | `eval_f7a3ca0b14b0` |

### budget=24 · hill（20）
| seed | handle |
|---|---|
| 1 | `eval_a433a12a5244` |
| 2 | `eval_b816a573523c` |
| 3 | `eval_d845f695f058` |
| 4 | `eval_6e474a9aa704` |
| 5 | `eval_da073d11fe1e` |
| 6 | `eval_d02dd5de6920` |
| 7 | `eval_be41fc3df59a` |
| 8 | `eval_6c79fd3a3583` |
| 9 | `eval_8d27e398d1f3` |
| 10 | `eval_d85d6df8ad25` |
| 11 | `eval_48cae117f544` |
| 12 | `eval_67fe3aceabed` |
| 13 | `eval_2b30bb137eee` |
| 14 | `eval_d9bdc2fe40ca` |
| 15 | `eval_fb292f55e5c2` |
| 16 | `eval_206114846da0` |
| 17 | `eval_3182d88f8e57` |
| 18 | `eval_3de8afb8ac09` |
| 19 | `eval_2f8ef2eb459b` |
| 20 | `eval_5e22724660be` |

### budget=24 · random（20，同 seed 与 hill 配对）
| seed | handle |
|---|---|
| 1 | `eval_80c623937b73` |
| 2 | `eval_9cc108ce78a5` |
| 3 | `eval_3cc6987d232d` |
| 4 | `eval_0e304dc13f8e` |
| 5 | `eval_671134866383` |
| 6 | `eval_8e9d7880b7af` |
| 7 | `eval_71504a41a67c` |
| 8 | `eval_ff99f3cd9f87` |
| 9 | `eval_4a5a89e71c82` |
| 10 | `eval_6f79ab7303c7` |
| 11 | `eval_794cb33dedee` |
| 12 | `eval_beee6f5befec` |
| 13 | `eval_fb41bf2098a6` |
| 14 | `eval_c1b25a94c593` |
| 15 | `eval_eddb38c4dab9` |
| 16 | `eval_e8ebea1826c2` |
| 17 | `eval_48d2a22dcd04` |
| 18 | `eval_899639c00739` |
| 19 | `eval_ea106cada71c` |
| 20 | `eval_8a32ca74b5ee` |

## 4. 各档运行记录（超时与处理）

| 档 | 总次数 | 成功 | MCP 超时次数 | 处理 |
|---|---|---|---|---|
| budget=1 · hill | 20 | 20 | 0（本轮） | 无 |
| budget=4 · hill | 20 | 20 | 0（本轮） | 无 |
| budget=24 · hill | 20 | 20 | **seed=8 连续 8 次** | 见下 |
| budget=24 · random | 20 | 20 | 0（本轮） | 无 |

**budget=24 · hill · seed=8 详细记录**：
- 第 1–7 次：`MCP error -32001: Request timed out`（budget=24 单次 2–4 分钟，超出客户端 2 分钟窗口，服务端实际仍在算）；每次等待约 30s–2min 后**重发同一组参数**（产物内容寻址，可复现，不会重复造数据）。
- 期间用轻量 `eeg_artifacts` 探测确认 MCP 已恢复响应（轻量调用正常，仅 budget=24 重型调用超时）。
- 第 8 次重发命中，返回 `eval_6c79fd3a3583`（n_evaluated=24, observed=0.5554, p=0.0323, significant=true）。
- **全程无静默跳过**，最终 n=20/20。

> 注：更早的会话（P3a/P3b 重跑前）曾记录 40 次合计 7 次超时（A 臂 seed=8/10/11/15，B 臂 seed=11/15/16），
> 本次 run-20261002 三档重跑仅 budget=24·hill·seed=8 触发 8 次超时，其余各档本轮零超时。

## 5. 一句话回答引子

**这套"不会撒谎"的流程，在完全没有信号的数据上，把虚报率从名义 0.05 抬到了 0.525
（budget=24，40 次里 21 次报出"显著"）；搜索规模越大虚报率越高——budget=1→0.10、
budget=4→0.20、budget=24→0.525，而即便只用随机抽样（不推理）也能到 0.55，
说明偏差主要来自"挑"这个动作本身，而非"会推理的智能体"。**
