# AGH 接入配置

把本项目的 MCP 工具接进 Agnes Harness（AGH），并导出提交所需的执行记录。

> 本文件按 **AGH 实际源码行为**编写（对照 `D:\AI-tools\agnes-harness-main`）。
> AGH 当前是 pre-alpha，接口仍在演进；若与你的版本不符，以仓库内
> `docs/guide/mcp.zh-CN.md` 与 `docs/guide/skills.zh-CN.md` 为准。
>
> ⚠️ 本文件中所有指标数值一律留空，必须来自你自己的实际运行。
> 赛事指南第十三节把「伪造实验数据、运行记录」列为取消资格情形。

---

## 0. 三个必须先知道的事实

这三点决定整个接入方式，先看清楚再动手：

**① Skill 的文件名是 `SKILL.md`，不是 `AGENT.md`。**
AGH 的 Skill 扫描器只认 `目录/SKILL.md`，根目录的 `AGENT.md` **不会被加载**
（本项目已删除该废弃文件）。本项目的 Skill 已放在正确位置：

```
.agh/skills/eeg-analysis/SKILL.md
```

**② Skill 不会自动生效。**
AGH 的文档原话：「不能只因磁盘上存在文件就声称模型已读取」。
必须在 Web 里刷新该工作区、审核 revision、点「启用」，状态到达
`trust=trusted` + `desired=enabled` + `actual=ready` 且存在 `winner` 才算数。
此外，**激活需要在本会话里明确点名**：「对明确提名且唯一匹配的可用 Skill 有预加载路径；
模糊描述不是确定性的激活语法」。

**③ MCP 配置不是 JSON 文件。**
它是受管资源，用 `mcp add` → `trust` → `enable` 三步注册，或直接在 Web 设置里点。
`docs/agh_setup.md` 的历史版本曾给出一个 `mcpServers` JSON 片段，那是错的，已删除。

另外：**AGH 拒绝明文环境变量**，只接受 `--secret-env NAME=secret://...`。
好消息是本项目的 MCP server **完全不调用 Agnes API**（模型调用发生在 AGH 内部，
不在工具里），所以它不需要任何密钥，也就不受这条限制影响。

---

## 1. 启动 AGH

源码已在 `D:\AI-tools\agnes-harness-main`，`node_modules` 与 CLI 构建产物都已就绪
（`packages/cli/dist/local/agnes.mjs`）。

在 **PowerShell** 里从仓库根目录运行：

```powershell
cd D:\AI-tools\agnes-harness-main
.\start-local-windows.ps1
```

该脚本会：检查依赖 → 构建 → 释放端口 4180 → 启动 daemon 与 Web 服务。
它用的是 **端口 4180**（默认端口是 4177，本脚本特意改掉），启动后终端会打印：

```
http://127.0.0.1:4180/
```

浏览器打开这个地址。**保持该终端开着**。

> Windows 注意：AGH 文档声明已有的本地进程验证是在 macOS 上做的，
> Windows 需另行验收。若构建报原生模块相关错误，需要 Visual Studio C++ Build Tools
> 与 Windows SDK。

验证 CLI 可用（另开一个终端）：

```powershell
node packages\cli\dist\local\agnes.mjs mcp list
```

预期输出 `No MCP servers found.` —— 说明能连上 daemon。

---

## 2. 配置模型

AGH **没有预置默认模型**，首次使用会引导你选 Provider。

在 Web 界面进入 Provider 设置，选择 **Agnes AI**（内置 `https://api.agnes-ai.cn/v1`，
可选模型如 `agnes-3.0-flash`、`agnes-2.5-pro`、`agnes-2.5-flash`），填入赛事方发放的
API Key。

> Key 的获取方式：报名成功后加入赛事官方交流群，**参赛编号与模型 Key 会一并发送到
> 队长报名邮箱**。注意查收垃圾邮件。
>
> 不要手写含密钥的 YAML。凭据由配置服务存入凭据后端，公开配置里只留 `secret://` 引用。

---

## 3. 注册 MCP server

### 方式 A：在对话里接入（推荐）

**设置 → MCP 页面是只读的，没有「添加」按钮。** 它只负责审核与启用状态展示。
真正的添加入口在对话里，由 `@agnes/mcp-helper` 插件提供（工具名 `mcp_manage`）。

先建一个会话，**工作目录选 `D:\暂存\source`**（工作区必须是这个目录，否则
`.agh/skills` 里的 Skill 扫不到），然后在对话框里说：

```
帮我接入这个 MCP 服务：
名称：eeg-agent
类型：stdio
可执行文件：D:/暂存/source/.venv/Scripts/python.exe
参数：D:/暂存/source/tools/eeg_mcp_server.py

它不需要任何凭据，也不访问网络上的模型接口。
```

宿主会校验请求并弹出原生授权，同意即可。
**「提交的连接在轮次边界生效」**——加完后可能要再发一条消息才会实际挂上。

随后回到 **设置 → MCP**，列表里会出现 `eeg-agent`，在这里点**启用**。

> **必须用 venv 解释器的绝对路径。** PATH 上的 `python` / `python3` 在这台机器上
> 指向 Microsoft Store 的转发器，不是真解释器。
>
> 可执行文件不能是 shell（`sh`/`bash`/`cmd`/`powershell` 等都会被拒），
> 也不允许 `--arg -c` 这类绕行。`python.exe` 没问题。
>
> 本项目不需要任何凭据：模型调用发生在 AGH 内部，MCP 工具只做本地信号处理。
> 因此不涉及 AGH 的 SecretRef 限制（AGH 拒绝明文 `--env`，只接受
> `--secret-env NAME=secret://...`）。

### 方式 B：命令行（需要交互式终端）

**必须在真实的 PowerShell 窗口里跑**——AGH 对写操作强制交互确认，
确认函数在 `stdin.isTTY !== true` 时直接返回 false，且**没有跳过标志**
（源码注释写明「未回答的提示绝不当作同意」）。在无 TTY 的环境里跑会得到
`operation cancelled`。

```powershell
cd D:\AI-tools\agnes-harness-main

# 添加（此时默认停用）
node packages\cli\dist\local\agnes.mjs mcp add eeg-agent --name eeg-agent `
  --stdio "D:/暂存/source/.venv/Scripts/python.exe" `
  --arg "D:/暂存/source/tools/eeg_mcp_server.py"

# 读取当前 revision
node packages\cli\dist\local\agnes.mjs mcp get eeg-agent

# 用上一步拿到的 REVISION 审核信任
node packages\cli\dist\local\agnes.mjs mcp trust eeg-agent --expected-revision REVISION

# 再读一次 revision（写操作会改 revision，不能复用旧值）
node packages\cli\dist\local\agnes.mjs mcp get eeg-agent

# 启用
node packages\cli\dist\local\agnes.mjs mcp enable eeg-agent --expected-revision REVISION
```

每一步都会弹出确认提示，输入 `y`。

### 验证

```powershell
node packages\cli\dist\local\agnes.mjs mcp status eeg-agent
node packages\cli\dist\local\agnes.mjs mcp tools eeg-agent
```

`mcp tools` 应列出 **13 个**工具：

| 工具 | 作用 |
|---|---|
| `eeg_fetch` | 从 EEGMMIDB 取数并切分事件段 |
| `eeg_inspect` | 元信息 + 质量诊断 |
| `eeg_preprocess` | 滤波 / 裁剪 / 伪迹剔除 |
| `eeg_features` | 特征提取 |
| `eeg_evaluate` | 按被试分组交叉验证（反馈信号） |
| `eeg_validate` | 置换检验 / 留出被试独立验证 |
| `eeg_ablation` | 与冻结基线对比 |
| `eeg_evidence` | 收集可写入报告的数字 |
| `eeg_artifacts` | 列出现有产物（handle 失效时恢复用） |
| `eeg_load_synthetic` | 合成数据，**仅供工具链自检** |
| `eeg_null_twin` | **零信号孪生体**：真实数据 + 打乱标签（非合成数据） |
| `eeg_trial_run` | 在零信号数据上跑一次搜索试验，判定是否「发现显著效应」 |
| `eeg_defect_rate` | 把若干次试验汇总成**虚报率** |

> 后三个属于零信号试验台，配套技能是 `.agh/skills/honest-lie/`。
> ⚠️ 它们只给**实验员**用。「测一个不知情的 agent 面对零信号会说什么」
> 那组实验**不能加载这份技能**，否则它会知道数据是零信号的，
> 测的就不再是自然反应——那种情况仍用 `eeg-analysis`。

> 这一步不需要模型账号，可以先把 MCP 连通性验完再去配模型。
> 若 `mcp tools` 报错，先看 `mcp status` 的连接状态与安全错误码，不要急着重装。

---

## 4. 启用 Skill

### 关键：会话的工作区必须是本项目

Skill 从**工作区**的 `.agh/skills` 目录发现。所以创建会话时，工作目录要指向
`D:\暂存\source`，否则 AGH 扫不到 `eeg-analysis`。

### 在 Web 里启用

1. 为该工作区创建会话
2. 进入 **设置 → Skills**，选中对应工作区，点**刷新**
3. 核对来源与内容修订，点**启用**
4. 确认状态：`trust=trusted`、`desired=enabled`、`actual=ready`，且有 `winner`

命令行同样可用（需交互式终端）：

```powershell
node packages\cli\dist\local\agnes.mjs resources list --kind skill
node packages\cli\dist\local\agnes.mjs skills refresh --root-key workspace-agnes --workspace-id WORKSPACE_ID
node packages\cli\dist\local\agnes.mjs resources get SKILL_RESOURCE_ID
node packages\cli\dist\local\agnes.mjs skills trust SKILL_RESOURCE_ID REVISION trusted
node packages\cli\dist\local\agnes.mjs resources enable SKILL_RESOURCE_ID --expected-revision REVISION
```

`WORKSPACE_ID` 是已登记工作区的 64 位十六进制标识，从工作区/资源数据里读，
**不要填路径**。改完代码后记得重新刷新并核对 revision。

### 激活时要点名

在会话里**明确说出 skill 名字**，例如：

> 使用 eeg-analysis，分析 EEGMMIDB 被试 1–10 的运动想象数据……

模糊描述（「帮我分析一下脑电」）不保证命中。

---

## 5. 跑一次完整闭环

在 AGH 会话里输入（这份 prompt 与 `docs/demo_script.md` 一致）：

```
使用 eeg-analysis，分析 EEGMMIDB 被试 1-10 的运动想象数据，判断左右手能否区分。

要求：
1. 先看数据质量，根据诊断结论决定预处理方案；
2. 每调一次配置就汇报指标，并说明你依据什么调整；
3. 两种交叉验证协议（within_subject 和 cross_subject）都跑一遍，分别报告；
4. 做一次独立验证，证明结果不是流程泄漏造成的；
5. 和冻结基线对比，说明你的配置带来了多少增益；
6. 最后给中文报告，报告里每个数字都要能追溯到具体的工具调用，
   并标明每条结果用的是哪种协议。

如果中途某个被试加载失败，判断它是否可恢复，可恢复就继续，
不可恢复就跳过并记录原因。
```

> ⚠️ **首次运行会从 PhysioNet 下载数据，实测约 11 分钟/被试（≈11 KB/s）。**
> 演示前务必先把数据下好，不要让视频里现场等下载。

预期调用序列与留空模板见下一节。

---

## 6. 一次完整闭环（模板）

> 下面数值**全部留空**，运行后按实际输出填写。

```
1. eeg_fetch(subjects=[1..10], task="left_vs_right_imagery")
   → handle=raw_xxxxxxxxxxxx, n_epochs=____, failures=____

2. eeg_inspect(handle="raw_xxxxxxxxxxxx")
   → warnings=[____________________]     ← 决策依据来自这里

3. eeg_preprocess(handle=..., low_hz=__, high_hz=__, crop_sec=[_, _], reject_uv=___)
   → handle=clean_xxxxxxxxxxxx, n_rejected=____, reject_pct_by_subject={____}

4. eeg_features(handle="clean_...", feature_set="bandpower", bands=["mu","beta"])
   → handle=feat_xxxxxxxxxxxx, n_features=____

5. eeg_evaluate(handle="feat_...", model="____", cv_folds=__,
                 cv_scheme="within_subject")
   → balanced_accuracy_mean=____, std=____, cohen_kappa=____

   ↻ 视结果回到第 3/4 步调整，重复 2–4 次。
     每次写清「观察 → 决定 → 理由 → 下一步」。

5b. eeg_evaluate(handle="feat_...", cv_scheme="cross_subject")
   → balanced_accuracy_mean=____      ← 接近随机是已知现象，如实记录

6. eeg_validate(handle="feat_...", scheme="shuffle_control",
                cv_scheme=<与第 5 步一致>)
   → null_distribution.mean=____, p_value=____

7. eeg_ablation(agent_eval_handle="eval_xxxxxxxxxxxx")
   → verdict=__________, delta_balanced_accuracy=____
   （基线会自动采用与 agent 相同的协议与折数，保证可比）

8. eeg_evidence(eval_handles=[...])
   → claims=[...]        ← 报告里只允许使用这里的数字

9. Agnes 模型：把 claims 组织成中文报告，每条结果标明协议
```

**第 8 步是硬约束**：`eeg_evidence` 之外的数字不得出现在报告里。
这让「编造数字」在结构上无法发生，而不只是靠自觉。

---

## 7. 导出执行记录（提交材料）

指南 §7 要求提交「可供人工核查的 AGH 执行记录」。

AGH 的会话账本是 SQLite，位于：

```
<AGH_HOME>/data/sessions.db        # 默认 %USERPROFILE%\.agh\data\sessions.db
```

**不要手动删这个文件或 owner / 审计记录来强行重开会话。**

导出方式：

```powershell
# 先列出会话，找到 SESSION_ID
node packages\cli\dist\local\agnes.mjs sessions --json

# 导出为原生 JSONL：每个事件一行，工具调用的参数与结果都在里面
node packages\cli\dist\local\agnes.mjs export SESSION_ID --format agnes -o session.jsonl

# 或导出成可读的时间线 HTML，适合截图/附交
node packages\cli\dist\local\agnes.mjs export SESSION_ID --html -o session.html
```

导出默认会做隐私脱敏（密钥、路径、PII）。需要完整字段时才考虑 `--raw`，
它会打印明文警告。**不要**把含密钥的内容交上去。

Web 侧的会话「轨迹」页也能按轮次查看工具参数与结果、耗时和 token 用量，
可以直接截图。

> 除 AGH 的记录外，本项目自己还有一份机器可读日志 `index.jsonl`
> （见 `docs/evidence-guide.md`），记录了每次工具调用的操作、参数、血缘和输出形状。
> 两份一起提交，互为印证。

---

## 8. 异常分支（演示时可现场触发）

指南 §6 要求「展示至少一次异常、失败或边界情况的处理过程」。任选其一：

| 触发方式 | 期望行为 |
|---|---|
| `eeg_inspect("clean_000000000000")` | 返回 `E_HANDLE_NOT_FOUND` 并**列出最近的可用 handle**，agent 据此继续 |
| `eeg_preprocess(..., crop_sec=[10,20])` | 窗口越界的明确错误，agent 改回合法窗口 |
| `eeg_preprocess(..., reject_uv=1e-9)` | 「全部样本被判为伪迹」，agent 放宽阈值重试 |
| `eeg_evaluate(feat, cv_folds=20)` | 被试数不足，agent 降低折数 |
| `eeg_fetch(subjects=[999])` | 该被试不存在，加载失败但**整体不中断**，明细在返回值里 |
| 断网后 `eeg_fetch(...)` | 下载重试后失败，返回明确错误 |

错误信封统一为：

```json
{"ok": false, "error": {"code": "...", "message": "...",
                        "recoverable": true, "suggestions": ["..."]}}
```

`suggestions` 是让 agent 自愈的关键——没有它，agent 只能停下来问人。

---

## 9. 环境变量（可选）

AGH 不给 stdio MCP 传普通环境变量，但本项目的 MCP server **不依赖任何环境变量**：
`MNE_DATASETS_EEGBCI_PATH` 未设置时会在代码里自动推导并创建目录，
`EEG_ARTIFACT_DIR` 未设置时默认落在 `%LOCALAPPDATA%\eeg-agent\artifacts\v1`。

如果你在 AGH 之外手动跑脚本，可以设：

| 变量 | 作用 |
|---|---|
| `MNE_DATASETS_EEGBCI_PATH` | 数据目录。**必须预先存在**——`update_path=False` 时 MNE 不会替你建目录 |
| `EEG_ARTIFACT_DIR` | 产物缓存目录。默认在仓库外，避免中文路径引发的 Windows OSError |
| `AGH_HOME` | AGH 的 home 根（必须是绝对路径）。Web 与 CLI 要用同一个值才能共享会话 |
| `AGNES_PROFILE` | profile 名，本脚本用 `local-dev` |
