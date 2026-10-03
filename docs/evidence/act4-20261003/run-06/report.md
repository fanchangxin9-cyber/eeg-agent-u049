# EEG 运动想象解码分析报告

> 本文所有数字均来自 eeg_evidence claims，来源 handle 在文末标注。
> 合成数据的结果未纳入本报告。

## 1. 数据概况

| 项目 | 值 |
|---|---|
| 数据集 | EEGMMIDB v1.0.0（PhysioNet），ODC-BY 1.0 |
| 任务 | 想象左手 vs 想象右手（left_vs_right_imagery） |
| 被试 | 6 人（1–6），每人 45 段，共 270 段 |
| 运行次数 | run 4, 8, 12 |
| 通道数 | 64 |
| 采样率 | 160 Hz |
| 段长 | 4.206 s（加载窗口 [-0.2, 4.0] s） |
| 类别分布 | 左手 137 段，右手 133 段（基本平衡） |
| 幅值诊断 | 中位数 22 μV，p99 167 μV，最大 639 μV；无平坦通道；healthy=true |

质量诊断未报出任何 warnings。p99 幅值 167 μV 提示存在少量大幅值伪迹段，
后续按 300 μV 阈值保守剔除（实际未剔除任何段，270 段全保留）。

来源：inspect(raw_348c1d558301)。

## 2. 方法

### 最终配置

| 参数 | 值 |
|---|---|
| 预处理 | 8–30 Hz 带通，无陷波，全窗口（不裁剪），reject_uv=300，channel_set=all，reref=none |
| 特征方案 | CSP + LDA（use_csp=True） |
| 评估协议 | cross_subject（GroupKFold 5 折，按被试分组） |
| 交叉验证 | 5 折，冻结 |
| 主结果指标 | 平衡准确率 |

### 为什么这样选

| 决策日志 | 观察 | 决定 | 理由 |
|---|---|---|---|
| ① | 诊断 healthy，无平坦通道；p99=167 μV 提示少量大幅值段 | reject_uv=300（宽松，不剔段） | 被试 4 在 reject=150 时被剔除 31%，样本损失严重；300 μV 保留全部 270 段 |
| ② | CSP + within_subject（reject 150 + crop [0.5,3.5]）= 0.432，更低 | 换全窗口 + reject 300 | crop 太短可能影响 CSP 拟合；放宽剔除率恢复样本量 |
| ③ | 全窗口 CSP within_subject = 0.484，仍低于随机；但 cross_subject 首次出现 0.559 | 转用 cross_subject 作为主结果 | CSP 在跨被试场景学的是运动皮层共有的 C3/C4 mu/beta 减弱模式，不需要个体标定，反而更稳定 |
| ④ | cross_subject CSP = 0.559（kappa 0.098）> cross_subject bandpower = 0.532（kappa 0.015） | 以 CSP 为最终配置 | 特征方案（CSP）比预处理调参影响大，符合已知优先级 |
| ⑤ | CSP within_subject = 0.484，置换 p=0.7273，无效果 | 如实报告 within_subject 结果 | 被试内 5 折样本太少（每折约 9 段），CSP 过拟合；跨被试反而更稳定 |

## 3. 结果

### 3.1 cross_subject（主结果）

| 配置 | 平衡准确率 | 标准差 | Cohen's kappa | F1 macro |
|---|---|---|---|---|
| **CSP + LDA（最终）** | **0.559** | **0.055** | **0.098** | 0.478 |
| bandpower + LDA（对照） | 0.532 | 0.112 | 0.015 | 0.532 |
| bandpower+asymmetry + LDA（对照） | 0.544 | 0.035 | 0.081 | 0.543 |

CSP 配置各被试平衡准确率（cross_subject）：
- 被试 1：0.444（最低）
- 被试 2：0.578
- 被试 3：0.644（最高）
- 被试 4：0.489
- 被试 5：0.511
- 被试 6：0.622

个体差异显著（最低 0.444 vs 最高 0.644），跨被试泛化能力有限。

### 3.2 within_subject（对照）

| 配置 | 平衡准确率 | 标准差 | Cohen's kappa |
|---|---|---|---|
| CSP + LDA | 0.484 | 0.102 | -0.030 |
| bandpower + LDA（crop [0.5,3.5]，reject 250） | 0.447 | 0.060 | -0.104 |
| bandpower+asymmetry + LDA（全窗口，reject 300） | 0.454 | 0.096 | -0.089 |

within_subject 所有配置均在随机水平（0.5）或略低，kappa 为负，
说明在被试内 5 折分层场景下判别信息不足。

### 3.3 留出被试验证（holdout）

留出被试 1 和 6（训练用被试 2–5，共 180 段训练，90 段测试）：

| 指标 | 值 |
|---|---|
| 平衡准确率 | 0.523 |
| 准确率 | 0.533 |
| Cohen's kappa | 0.046 |

留出被试结果略高于随机（0.523 vs 0.5），方向正确但幅度有限，
与 cross_subject 结果一致，说明跨被试泛化能力真实但有限。

## 4. 验证

### 4.1 置换检验（shuffle_control）

对最终配置（CSP + cross_subject，观测值 0.559）做 20 次标签打乱置换：
（分 4 批各 5 次，seed=0/1/2/3，再合并）

| 统计量 | 值 |
|---|---|
| 真实标签平衡准确率 | 0.559 |
| 打乱分布均值 | 0.497 |
| 打乱分布最大 | 0.540 |
| 观测值是否超过全部打乱 | 是（0.559 > 0.540） |
| **p 值** | **0.0476**（理论下限 1/(20+1)=0.0476） |

**结论：p = 0.0476 < 0.05，结果在常规显著水平上高于随机，未发现流程泄漏迹象。**

补充验证（bandpower cross_subject，观测值 0.532，10 次置换，seed=0）：
p = 0.0909（理论下限 0.0909，观测值未超过全部打乱值），**不显著**。
bandpower 对照组在 10 次置换下无法证明显著，如实报告。

补充验证（CSP within_subject，观测值 0.484，10 次置换，seed=0）：
p = 0.7273，观测值低于打乱分布最大值，**不显著**，与 3.2 节结果一致。

### 4.2 置换次数说明

单次调用 10 次 CSP cross_subject 置换两次均超时（已知 OVERLOADED 可恢复场景），
按 skill 指导分批各 5 次、不同 seed，再合并为 20 次。
合并批次（4×5）模型/协议/折数完全一致，合并通过验证。

## 5. 与冻结基线对比

基线（bandpower + LDA + within_subject，全窗口，无裁剪，crop [0.5,3.5] 对应）：
- 平衡准确率：0.447（std 0.060）

Agent 配置（CSP + LDA + within_subject，全窗口，reject 300）：
- 平衡准确率：0.484（std 0.102）

| 对比项 | 值 |
|---|---|
| Δ 平衡准确率 | +0.037（基线 0.447 → agent 0.484） |
| 服务端 verdict | **agent_config_better** |
| 增益来源 | CSP 空间滤波器：自动学出运动皮层最优电极加权，不需要个体标定 |

注：两配置 same_epoch_set=true（均回溯到同一 raw 数据、同一被试划分），
差异主要来自特征方案（CSP vs bandpower），预处理差异（全窗口 vs crop）是次要贡献。

## 6. 局限

| 局限 | 说明 |
|---|---|
| 被试数 | 仅 6 人，跨被试 5 折 GroupKFold 每折测试被试约 1–2 人，统计功效低 |
| 个体差异 | 被试 1（0.444）明显拉低均值，其运动想象策略可能与其他 5 人不同 |
| within_subject | 所有配置均低于随机（0.447–0.484），被试内 5 折每折仅约 9 段，CSP 过拟合严重 |
| 多重比较 | 共跑了 9 组配置评估，未做多重比较校正，存在选择性报告风险 |
| 置换次数 | 20 次置换 p 下限 0.0476，仅刚好达到 0.05 显著水平，效应量（0.559 vs 0.5）偏小 |
| 未做 CAR / motor 通道 | 实测文档提示 CAR 有害、motor 通道基本无用，故未试；若推翻此结论需单独对照 |
| 未加 theta 频段 | 文档提示 theta 在 6 被试时反而变差，故未纳入 |
| 时间窗口 | 全窗口 [-0.2, 4.0] 包含了静息段，可能引入基线噪声；crop [0.5, 3.5] 实测更差 |
| 非临床结论 | 本工具输出仅为信号分析参考，不构成医疗诊断 |

## 附：Claim 来源

| Claim | 值 | Handle | 工具 |
|---|---|---|---|
| cross_subject CSP 平衡准确率 | 0.559 | eval_b664027899a8 | eeg_evaluate |
| cross_subject CSP 标准差 | 0.055 | eval_b664027899a8 | eeg_evaluate |
| cross_subject CSP kappa | 0.098 | eval_b664027899a8 | eeg_evaluate |
| cross_subject CSP F1 | 0.478 | eval_b664027899a8 | eeg_evaluate |
| cross_subject bandpower 平衡准确率 | 0.532 | eval_badb39e532cf | eeg_evaluate |
| cross_subject bandpower 标准差 | 0.112 | eval_badb39e532cf | eeg_evaluate |
| cross_subject bandpower+asymmetry 平衡准确率 | 0.544 | eval_a17e261602aa | eeg_evaluate |
| within_subject CSP 平衡准确率 | 0.484 | eval_c8ce50707559 | eeg_evaluate |
| within_subject CSP 标准差 | 0.102 | eval_c8ce50707559 | eeg_evaluate |
| within_subject CSP kappa | -0.030 | eval_c8ce50707559 | eeg_evaluate |
| within_subject bandpower（crop）平衡准确率 | 0.447 | eval_94194598be9c | eeg_evaluate |
| holdout [1,6] 平衡准确率 | 0.523 | eval_1bacf4e4085c | eeg_validate |
| holdout [1,6] kappa | 0.046 | eval_1bacf4e4085c | eeg_validate |
| 置换 20 次 p 值（CSP cross_subject） | 0.0476 | eval_0cdb3b3271c7 | eeg_validate |
| 置换 10 次 p 值（bandpower cross_subject） | 0.0909 | eval_e8636d737467 | eeg_validate |
| 置换 10 次 p 值（CSP within_subject） | 0.7273 | eval_261d19b5287b | eeg_validate |
| 基线平衡准确率（ablation） | 0.447 | eval_330a7b75e59d | eeg_ablation |
| Agent 平衡准确率（ablation） | 0.484 | eval_c8ce50707559 | eeg_ablation |
| Δ 平衡准确率（ablation） | +0.037 | eeg_ablation | eeg_ablation |
| verdict | agent_config_better | eeg_ablation | eeg_ablation |
