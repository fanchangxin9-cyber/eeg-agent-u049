# EEG 运动想象解码分析报告
## 任务：左右手运动想象（left vs right fist imagery）能否区分

数据集：EEGMMIDB v1.0.0（PhysioNet，ODC-BY 1.0），被试 1–6，run 4/8/12，
任务 `left_vs_right_imagery`。raw handle：`raw_1cf8ec654339`。

---

## 1 · 数据概况

| 项 | 值 |
|---|---|
| 数据集 | EEGMMIDB v1.0.0（PhysioNet） |
| 任务 | 想象左手 vs 想象右手（`left_vs_right_imagery`） |
| 被试 | 6 名（被试 1–6） |
| 每人试次 | 45（共 270 epoch） |
| 通道数 | 64 |
| 采样率 | 160 Hz |
| 加载窗口 | [−0.2, 4.0] s |
| 类别分布 | left_fist 137 / right_fist 133（基本平衡） |
| 幅值量级 | 中位 22 µV，p99 167 µV，最大 639 µV |
| 质量诊断 | `healthy=true`，无 `warnings`，无 `flat_channels`，无样本过少被试 |

诊断结论：数据本身健康，类别平衡，每被试样本量一致（各 45 试次）。
唯一需处理的是最大幅值 639 µV 远超正常脑电，提示存在少量伪迹。

---

## 2 · 方法（含选择理由）

### 2.1 最终采用的配置
- 预处理：bandpass 8–30 Hz（mu+beta），`crop_sec=[0.5, 3.5]`，`reject_uv=250`，
  `channel_set=all`，`reref=none`，不剔通道。
- 特征：**bandpower + asymmetry**（同源电极对左右差值，mu/beta 两频段，
  按被试 z-score 归一化）。
- 模型：LDA，5 折交叉验证。
- 协议：**within_subject（被试内）** 为主结果；**cross_subject（跨被试）** 一并报告。

### 2.2 为什么这样选（决策日志摘要）
| 轮次 | 观察 | 决定 | 理由 | 下一步 |
|---|---|---|---|---|
| R1 | `healthy=true`，无警告，最大 639 µV | 保守打底：全通道、不做 CAR、不选 motor 道、`reject_uv=250` | CAR 与 motor 选道实测有害/无用；最大幅值高需剔伪迹 | preprocess+features+evaluate |
| R2 | clean 全保留、0 剔除 | 先跑 bandpower+LDA 基线 | 建立对照锚点（skill 实测 ~0.55） | evaluate within_subject |
| R3 | 基线 0.511 接近随机 | 上 CSP（skill 表里提升最大） | CSP 学空间滤波器匹配对侧偏侧化 | evaluate use_csp |
| R4 | CSP 0.471 反低于 bandpower | 收紧 `reject_uv=150` 再试 | CSP 对伪迹更敏感 | preprocess(reject150)+CSP |
| R5 | CSP+reject150 仍 0.468 | 改用 bandpower+asymmetry | 低维、物理含义明确、小样本更鲁棒 | features+evaluate |
| R6 | asymmetry 0.528 略升但 std 0.122 大 | 试收窄窗口 [0.5,2.5] | 去后期静息噪声 | preprocess+features+evaluate |
| R7 | [0.5,2.5] 降到 0.512 | 回 [0.5,3.5]（局部最优），转验证 | 收窄无益 | cross_subject + 置换 |
| R8 | cross_subject 0.489 接近随机（符合已知） | 对最佳配置做置换检验 | 确认 0.528 是否显著 | shuffle×3 |
| R9 | 30 次置换 p=0.1613 不显著 | 如实记录不显著 | 6 被试、个体差异大是瓶颈 | holdout + ablation |

关键判断：CSP 在本数据集**未达预期**（被试少 → 空间滤波器过拟合，
反而比 bandpower 差），因此不强行包装。asymmetry 比纯 bandpower 多利用
"对侧偏侧化"这一物理先验，带来小幅但方向正确的提升。

### 2.3 为什么用这两种交叉验证协议
- **within_subject**：每人内部 5 折分层，回答"在这名使用者身上能否解出
  运动想象"——对应真实 BCI 的逐人标定流程。
- **cross_subject**：按被试分组、测试被试完全不参与训练，回答"能否不做
  标定就套用到新使用者"——公认难题，小被试集上通常接近随机。
- 两者回答不同问题，故**都跑并分别报告**。

---

## 3 · 结果（每个数字标明协议）

| 配置 | 协议 | 平衡准确率 | std | Cohen's κ |
|---|---|---|---|---|
| bandpower+LDA（基线） | within_subject | 0.5114 | 0.0854 | 0.0229 |
| CSP+LDA | within_subject | 0.4712 | 0.0636 | −0.0525 |
| CSP+LDA（reject150） | within_subject | 0.4675 | 0.0607 | −0.0604 |
| **bandpower+asymmetry+LDA（最佳）** | **within_subject** | **0.5277** | **0.1216** | **0.0529** |
| bandpower+asymmetry [0.5,2.5] | within_subject | 0.5121 | 0.0934 | 0.0241 |
| bandpower+asymmetry（最佳配置） | cross_subject | 0.4893 | 0.0645 | −0.0368 |

逐被试（within_subject，最佳配置）：被试1 0.2668、被试2 0.5109、被试3 0.5791、
被试4 0.6008、被试5 0.622、被试6 0.5863。个体差异极大：被试1 远低于随机，
被试4/5/6 明显高于随机。

**结论**：左右手**部分被试可区分、整体接近随机**。被试内最佳配置平衡准确率
0.5277 仅略高于 0.5 随机水平，且被试间波动大。跨被试 0.4893，低于随机——
这是跨被试泛化难的已知现象，如实报告，不作"可泛化"结论。

---

## 4 · 验证

### 4.1 置换检验（shuffle_control，防流程泄漏）
- 对象：最佳配置 within_subject 结果（观测 0.5277）。
- 方法：分 3 批各 10 次置换（seed=0/1/2，模型/协议/折数一致），再合并共 30 次。
- 结果：打乱后均值 0.4828、最大 0.5527；**p = 0.1613**。
- 判断：p > 0.05，**未能显著高于随机**。即当前结果**无法排除是流程泄漏或
  随机波动**，不能作为"学到了真实判别信息"的证据。

> 注：30 次置换的 p 值理论下限为 1/31≈0.032；本例观测值并未超过全部打乱
> 结果（打乱最大 0.5527 > 观测 0.5277），故 p=0.1613 反映的是"观测值在打乱
> 分布中的排位"，不是次数不足导致的假不显著。

### 4.2 留出被试（holdout_subject）
- 留出被试 6，训练集完全不含该被试（含标准化）。
- 结果：平衡准确率 0.5774（45 测试 epoch），κ=0.1543。
- 判断：高于 0.5，但样本量小（n=45），且单被试，不足以支撑泛化结论。

---

## 5 · 与冻结基线对比

`eeg_ablation` 对比（agent 配置 vs 冻结基线 `baseline_bandpower_lda`，
同一份 raw、同一被试划分、同一 within_subject 协议）：

| 项 | 冻结基线 | agent 配置 | 差值 |
|---|---|---|---|
| 平衡准确率 | 0.5114 | 0.5277 | **+0.0163** |
| 特征 | bandpower | bandpower+asymmetry | — |
| 预处理 | 无 reject | reject_uv=250 | — |

- **verdict = agent_config_better**（由服务端计算，仅引用不自称）。
- 增益来源：asymmetry 特征引入了"同源电极对左右差值"，利用了运动想象
  C3/C4 一带 mu/beta 的对侧偏侧化先验；叠加轻度伪迹剔除。
- 但增益仅 +1.63 个百分点，且 agent 的折间 std 更大（0.1216 vs 0.0854），
  提升有限且不稳健。

---

## 6 · 局限

1. **被试数少（n=6）**：被试内分组交叉验证在 6 人上不稳定，逐被试波动大
   （0.27–0.62），单被试结果不能推广到总体。
2. **个体差异极大**：被试1 持续低于随机，被试4/5/6 高于随机；整体均值
   被个例拉平，"平均"意义有限。
3. **跨被试泛化差**：cross_subject 0.4893（低于随机），说明**不做标定
   无法套用到新使用者**——这是该领域的已知难题，非本次失败。
4. **置换检验不显著（p=0.1613）**：within_subject 最佳 0.5277 未能显著高于
   随机，因此**不能声称学到了真实判别信息**；结果接近随机水平。
5. **未做的事**：未尝试 SVM/LogReg、未加 theta/gamma 频段、未做更细的
   窗口网格搜索、未对 CSP 加正则化、未扩大被试集。CSP 在本数据上表现
   差于 bandpower，未做根因分析（如被试样本量是否足以支撑空间滤波）。
6. **非医疗诊断**：本分析仅为信号层面的判别参考，不构成任何临床诊断。

---

## 附：工具链自证

`pytest tests\ -q`：**42 passed in 14.12s（exit 0）**。三类测试覆盖：
- **正常路径（test_normal.py）**：完整闭环 取数→诊断→预处理→特征→评估→
  独立验证→证据，合成数据秒级跑通，验证工具链连通且指标可用；并确认
  合成数据结果会被 `eeg_evidence` 拒绝（不得进入正式结论）。
- **边界路径（test_edge.py）**：单被试、类别不平衡、非标准通道名、极窄频带、
  工频陷波、剔除通道、伪迹阈值边界——验证工具在边界上**给出正确诊断或
  明确拒绝**，而非静默出错。
- **失败路径（test_failure.py）**：失效 handle、非法参数、越界窗口、样本不足、
  产物类型不匹配——验证错误**结构化且可恢复**（带错误码、原因、下一步建议），
  使 agent 能自愈而非整体崩掉。

## 附：可追溯 handle 清单
- raw：`raw_1cf8ec654339`
- clean：`clean_a5ef37e17590`（reject250，全保留）/ `clean_1e360e40fa88`
  （reject150，剔 19）/ `clean_b489f9b66052`（[0.5,2.5]）
- feat：`feat_6a73b4b2860e`（bandpower）/ `feat_4d01784f434a`（+asymmetry）
  / `feat_95afe5e87087`（[0.5,2.5]）
- eval：`eval_2930d5c75844`（bandpower ws）/ `eval_737989c34dba`（CSP）/
  `eval_a528d980794b`（CSP reject150）/ `eval_b37e9d398e28`（+asymmetry，最佳）/
  `eval_0667eb8492d4`（[0.5,2.5]）/ `eval_158f2ab91569`（cross）
- validate：`eval_f575c35da812` / `eval_401d9a457e11` / `eval_95ae447defeb`
  （置换 3 批）→ 合并 `eval_f9863426ea14`（p=0.1613）；
  `eval_e3d287d592ad`（holdout 被试6）
- ablation：基于 `eval_b37e9d398e28`，verdict=agent_config_better，Δ=+0.0163
