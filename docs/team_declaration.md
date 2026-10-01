# 成员分工与独立完成声明

## 一、成员信息（提交时填写）

| 姓名 | 学校 / 专业 | 组别 | 分工 |
|---|---|---|---|
| 刘云飞（队长） | 南通理工学院 · 电子信息工程专业 | 本科生 | 全部任务：Agent 闭环设计、EEG 分析工具开发、MCP server、演示视频录制、报告文案、路演 PPT、测试样例与异常分支验证 |

> 本队为 **1 人队**（仅队长刘云飞 1 人，无队员）。指南允许队伍 1–3 人；跨学历组队将统一划入硕博组，本届本队组别为本科生组。
> **队伍名称：瘤神**。
>
> **学号等身份信息不在公开仓库中给出**，仅填入提交用的声明文件（参赛指南 §12：
> 获奖代码库开源时「个人信息…不得公开」）。评审需要核验在校身份时，请以提交的
> 正式声明为准。

## 二、独立完成声明

本作品由上述成员在赛事期间（**2026 年 9 月 24 日 – 2026 年 10 月 15 日**）
独立完成。

高校教师可以提供面向所有学生的通用知识交流和赛事规则说明，但未代替参赛学生
完成项目开发。作品的关键实现与验证方法可在路演与问答环节说明。

### 使用第三方素材的情况

指南要求如实说明来源、**授权情况**和使用方式。逐项列明如下：

| 素材 | 来源 | 授权情况 | 使用方式 |
|---|---|---|---|
| EEGMMIDB v1.0.0 | https://physionet.org/content/eegmmidb/1.0.0/ | Open Data Commons Attribution License v1.0（开放数据，无需申请） | 作为唯一实验数据源；不随仓库分发，由 `mne.datasets.eegbci` 按需下载 |
| Agnes Harness (AGH) | https://github.com/AgnesAI-Labs/agnes-harness | 见其仓库 LICENSE | 作为智能体运行与执行底座 |
| MNE-Python | https://mne.tools/ | BSD-3-Clause | EDF 读取、CSP 变换 |
| scikit-learn | https://scikit-learn.org/ | BSD-3-Clause | 分类器、分组交叉验证、评估指标 |
| SciPy | https://scipy.org/ | BSD-3-Clause | 滤波、Welch 功率谱 |
| NumPy | https://numpy.org/ | BSD-3-Clause | 数组计算 |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk | MIT | 把分析能力暴露为 MCP 工具 |

**未使用**其他第三方代码、数据、图片、3D 资产或未声明的素材。

> 若后续引入任何新素材，必须回到本表补一行，并说明授权情况。
> 隐瞒来源属于取消资格情形。

### 关于实验数据

本作品报告中出现的全部指标均由 `tools/` 下的代码在 EEGMMIDB 真实数据上运行
得出，可在 `docs/evidence-guide.md` 记录的路径下复现。

**未使用合成数据产生任何进入报告的数字。** 仓库中的合成数据（`eeg_load_synthetic`）
仅用于单元测试和工具链自检，其产物在元信息中标记 `is_synthetic=True`，
`eeg_evidence` 会自动拒绝引用它们。

## 三、签名

（提交时手签）

- _______________
