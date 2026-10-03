# EEG 运动想象解码分析报告

> 数据集：EEGMMIDB v1.0.0（PhysioNet，ODC-BY 1.0）
> 任务：左手 vs 右手运动想象（left_vs_right_imagery）
> 评估协议冻结：5 折交叉验证、平衡准确率、随机水平 0.5、随机种子固定

## 1 · 数据概况

- 原始 handle：`raw_df4892d4692f`，EEGMMIDB 被试 1–6，runs [4, 8, 12]，task = left_vs_right_imagery。
- 270 个 epochs，64 通道，160 Hz 采样，每被试 45 epochs。
- 类别分布：left_fist 137 / right_fist 133（基本平衡）。
- 质量诊断：幅值中位数 22 μV、p99 167 μV、max 639 μV；无平坦通道，无 warnings，整体健康。

## 2 · 方法（含选择依据）

预处理参数由质量诊断驱动：

- 带通 8–30 Hz（mu + beta 经典运动想象频段）；50 Hz 工频陷波。
- 分析窗口 [0.5, 3.5] s（提示后 0.5–3.5 s，判别信息集中段）。
- 伪迹阈值 reject_uv = 150（约为 p99 幅值 167 μV），剔除 19/270 个 epoch（7.04%），剩余 251。
- 不启用共平均参考（CAR）、不筛道（`channel_set=all`）——两者实测在该数据集上无益甚至有害（skill 表实测 CAR 0.552→0.528，`motor` 0.552→0.551）。

特征/模型（within_subject 协议，按 skill 的"影响大→影响小"顺序）：

| 配置 | 输入 | 模型 | within_subject 平衡准确率 ± std |
|---|---|---|---|
| bandpower(mu,beta)+LDA | feat | LDA | 0.487 ± 0.1299 |
| **CSP+LDA，crop [0.5,3.5]**（最佳） | clean | CSP+LDA | **0.4863 ± 0.0485** |
| CSP+LDA，crop [0.5,2.5] | clean | CSP+LDA | 0.4719 ± 0.0311 |
| CSP+LDA，crop [1.0,3.0] | clean | CSP+LDA | 0.4841 ± 0.1114 |

决策日志（四字段）：

- **观察**：bandpower+LDA 被试内协议 0.487，std 0.1299 偏大，比随机 0.5 还低。
  **决定**：切到 CSP+LDA（CSP 是空间滤波器，skill 表写明是该数据集上提升最大的旋钮）。
  **理由**：0.487 已证明 bandpower 路线不成立；CSP 在冻结基线上 0.4331 而 bandpower 基线同为 0.4331，说明该 6 被试集上 CSP 相对 bandpower 的优势需实测确认。
  **下一步**：`eeg_evaluate(handle=clean_a2caa401cffc, use_csp=True)`。
- **观察**：CSP+LDA crop [0.5,3.5] = 0.4863（std 0.0485），折间方差比 bandpower 明显更小。
  **决定**：按 skill 的"crop 影响明显值得单独试"，再试 [0.5,2.5] 与 [1.0,3.0] 两个窗口。
  **理由**：skill 实测 0.59/0.61/0.63 在 8–10 被试上有窗口效应；在 6 被试上是否可复现需实测。
  **下一步**：各跑一次 CSP+LDA。
- **观察**：[0.5,2.5] = 0.4719、[1.0,3.0] = 0.4841，均未超 0.4863 + 1pp。
  **决定**：停止迭代（声明的 6 组上限内、连续 3 组无 >1pp 提升），选定 CSP+LDA + crop [0.5,3.5] 作为最佳 within_subject 配置（eval_2bfba0588ff3）。
  **理由**：折间 std 最小（0.0485）且均值接近最高；继续遍历只会堆噪声。
  **下一步**：cross_subject 协议同配置再评估一次，然后做置换检验。

cross_subject 协议（GroupKFold 按被试分组，测试被试完全不参与训练）：

- 同一 CSP+LDA + crop [0.5,3.5] 输入：平衡准确率 0.4919 ± 0.0301，3 折恰好 0.5，整体接近随机。
- 这与 skill 描述的已知现象一致——"小被试集上通常接近随机，不是失败，把它藏起来才是问题"。

## 3 · 结果

**within_subject 协议**（同一被试内分层 5 折；训练与测试来自同一人，BCI 标准标定场景）：

- 最佳配置 CSP+LDA，crop [0.5, 3.5] s：
  - 平衡准确率均值 0.4863，标准差 0.0485（eval_2bfba0588ff3）。
  - 准确率均值 0.4900；macro-F1 0.4900；Cohen's kappa -0.0197。
  - 混淆矩阵 [[62,66],[62,61]]，对角线接近随机水平。
- 对照组 bandpower+LDA：平衡准确率 0.487 ± 0.1299（eval_c203ad18eaa4），折间 std 明显更大。
- 窗口对照 [0.5,2.5] 0.4719 ± 0.0311；[1.0,3.0] 0.4841 ± 0.1114。

**cross_subject 协议**（按被试分组；测试被试未参与训练，衡量"免标定套用到新使用者"）：

- CSP+LDA，crop [0.5, 3.5] s：平衡准确率 0.4919 ± 0.0301，Cohen's kappa -0.0265（eval_f886dfdb429c）。
- 5 折中 3 折恰好 0.5（完全随机），整体接近随机水平 0.5。
- 与 within_subject 的 0.4863 差异很小，说明该 6 被试集上跨被试泛化与同被试解码都处于随机水平附近。

## 4 · 验证（置换检验）

针对最佳 within_subject 配置（CSP+LDA，crop [0.5,3.5]，cv_folds=5，use_csp=True）做 shuffle_control：

- 因 CSP 单次交叉验证耗时较高，按 skill 建议分 3 批各 10 次置换，seed = 1/2/3，模型/协议/折数完全一致：
  - 批 1（seed=1）：置换均值 0.5285，p = 0.9091。
  - 批 2（seed=2）：置换均值 0.5011，p = 0.7273。
  - 批 3（seed=3）：置换均值 0.4785，p = 0.6364。
- 合并 `shuffle_control_combine`（n = 30，下限 p = 1/(30+1) ≈ 0.0323）：
  - 观测 0.4863，打乱后均值 0.5027（std 0.0404，p95 = 0.5543，max = 0.5973）。
  - 合并 p = 0.7419，**显著高于随机水平的检验未通过**。

结论：观测值 0.4863 低于打乱后分布的均值与 p95，**没有证据表明该配置学到了超越随机的判别信息**。这是"流程泄漏不存在"的诚实结果，而不是"模型失败"——它说明当前 6 被试集在该协议下没有可泛化的信号。

## 5 · 与冻结基线对比

`eeg_ablation` 返回：

- 基线 `baseline_bandpower_lda`（8–30 Hz, crop [0.5,3.5], bandpower(mu,beta)+LDA, within_subject）：0.4331 ± 0.1111。
- Agent 最佳配置（CSP+LDA, crop [0.5,3.5], within_subject）：0.4863 ± 0.0485。
- **delta +0.0532**，`verdict = agent_config_better`。
- 公平性说明：`same_epoch_set = false`——agent 端剔除了 19 个伪迹 epoch（基线未做伪迹剔除），差异中同时包含"换成 CSP"与"剔除 19 个 epoch"两部分的贡献，这是设计意图，需如实说明。

## 6 · 局限

- **被试数仅 6 人**：skill 明确要求 5 人及以上，但 6 人规模下 cross_subject 的 GroupKFold(5) 训练样本过小（每折 50 epochs 左右），泛化检验天然偏弱。
- **个体差异大**：within_subject 各被试准确率从 0.42 到 0.58，折间 std 最高达 0.111，均值被少数高值被试抬升，单被试结果不可外推。
- **多重比较**：本轮试了 4 组配置（bandpower+LDA、CSP+LDA×3 窗口），未做 Bonferroni 校正；报告以"最佳配置"为主，但任何单点数字都应视为探索性结果而非确证。
- **未做的事**：未尝试 SVM/LogReg 模型（skill 未列为优先旋钮，预算受限）；未尝试 `bandpower+asymmetry` 特征（针对对侧偏侧化的专门特征，本数据集 6 被试可能不足以体现）；未做被试 4 单独剔除实验（被试 4 剔除率 17.8%–22.2%，是组内偏高者）。
- **非医疗用途**：本工具输出仅为信号分析参考，不构成医疗诊断。

---

### 数字溯源

本报告所有数字均出自 `eeg_evidence` 返回的 claims（C1–C5 等），eval_handles 列表：
`eval_c203ad18eaa4`（bandpower+LDA within）、`eval_2bfba0588ff3`（CSP+LDA within ★ 最佳）、`eval_554839632965`（CSP+LDA [0.5,2.5] within）、`eval_18f260f7309a`（CSP+LDA [1.0,3.0] within）、`eval_f886dfdb429c`（CSP+LDA cross_subject）、`eval_054afaa644eb`（置换合并）、`eval_65da39cf3e0e`（冻结基线）。
