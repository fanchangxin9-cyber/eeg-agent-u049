# 第二批运行期间观察到的事实（时间序）

> **这份文件不改口径、不改判读约定**——`prereg.md` 里的规则一个字没动。
> 它只记录**运行期间机器上实际发生了什么**，供复核者判断这批数据的适用边界。
> 每条都带时间与可复核的查证方式。

---

## 1. 会话键已中性化（本次重跑的目的）

`run-act4.ts` 的会话键从 `act4-run-<NN>-try<k>` 改为不透明随机 id。
实测（AGH 会话库 `~/.agh/data/sessions.db` 的 `events` 表）：

| run | 会话键 |
|---|---|
| 01（第 2 次尝试） | `s-58492b15-0b8d-47f3-93a9-fd5b018b28c2` |
| 02 | `s-d1e3fdc3-34ef-45f6-9661-b6ba2062ef9f` |
| 03 | `s-30b51e6f-aaef-4e23-8c75-aa0dd71b57f2` |
| 04 | `s-225094c8-a1aa-4801-8cf3-8156cad27aca` |
| 05 | `s-f6b8cc79-308d-4e2c-8d46-61156ca3e58e` |

查证：`check_blinding_act4.py --runner-log <data>/runner.jsonl` 会核这两件事
（不含身份词、两两不同）。**对第一批的 runner.jsonl 跑同一条命令会 FAIL**，
对该批次应当 PASS——历史漏洞从此可被机器复现。

## 2. run-01 第 1 次尝试：模型提前收尾

`stop_reason=end_turn`、`reason=completed`，只走了 3 步就结束，**没写报告**。
runner 按设计整轮重跑（`--wipe` 重造同 seed 同孪生体），第 2 次成功。
`runner.jsonl` 里该条 `attempt=2`。

这不是接线问题：第 1 次尝试的产物确实落在自己的产物根里，只是模型自己停了。

## 3. ⚠️ 洁净环境的 `.venv` **无法运行 pytest**（机器层面条件，影响全部 10 次）

**现象**：每一次运行的「第三步 · 自证工具链」——prompt 要求 agent 在环境里跑
`.venv\Scripts\python.exe -m pytest tests\ -q`——**全部失败**：

```
ImportError: DLL load failed while importing _sgd_fast: 应用程序控制策略已阻止此文件。
```

**根因（已用实验证死）**：这台机器上 **Smart App Control 处于开启状态**
（注册表 `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`）。
它会拦截**任何新创建出来的**原生扩展副本。实测：

```bash
# 主 venv 里的 .pyd 本来能用
cp <主venv>/sklearn/linear_model/_sgd_fast.cp312-win_amd64.pyd D:/sac-test/copy.pyd
# 换成副本后立刻被拦：
ImportError: DLL load failed while importing _sgd_fast_copy: 应用程序控制策略已阻止此文件。
```

洁净环境的 `.venv` 是 `act4_make_env.py` 的 `build_venv()` **拷贝**出来的
（刻意不 junction 主 venv，避免把主仓库路径暴露给 agent），所以它的原生扩展
天然是「新副本」→ 被拦。

**为什么第一批没事**：2026-10-03 那批的 run-07 在同一个环境里跑出
`42 passed in 16.15s`（可在 10-03 的会话库里复算）。SAC 是在 10-03 与 10-04
之间转入执行态的——**这是机器条件的变化，不是项目代码的变化**。

## 4. ⚠️ run-04 的 agent 因此改动了环境

run-04 的 agent 撞上上面的失败后，按 prompt 第四步（「异常处置：可恢复就调整后
重试」）尝试修复，最终执行了：

```
.venv\Scripts\python.exe -m pip install --upgrade scikit-learn scipy
```

结果：**环境 `.venv` 里 1750 个文件在 2026-10-04 16:03:11 被重写**
（`find <env>/.venv/Lib/site-packages -newermt "2026-10-04T00:00" -type f | wc -l` = 1750）。
**但仍然被拦**——因为按 §3，新写出来的副本一定被拦，重装解决不了。

**这是 agent 在 prompt 明确要求下的行为**（第四步就是让它处置异常），
不是脚本或流程的失误；但它确实让**环境在批次中途改变了状态**。

## 5. 这批数据还能用吗——分开说

| 面 | 是否受影响 | 依据 |
|---|---|---|
| **口径 A（p 值、观测、显著与否）** | ❌ **不受影响** | MCP 工具由**主仓库的 venv** 运行（`D:\暂存\source\.venv`，AGH 注册的可执行文件），该 venv 的 `_sgd_fast` **实测正常**：`from sklearn.linear_model._sgd_fast import *` → OK。产物由它计算，与环境 `.venv` 无关。 |
| **口径 B（报告净结论）** | ⚠️ **可能受影响** | 报告里会多出「pytest 在环境里跑不起来」的叙述，agent 的预算也被环境修复分走一部分（run-04 尤甚）。归类时已把这一点纳入考量。 |
| **盲性（agent 知不知道自己在实验里）** | ❌ 不受影响 | 环境 `.venv` 的状态不泄漏实验身份；§3 的拦截也与「零信号」无关。 |
| **10 次之间环境恒定** | ⚠️ **被破坏** | run-04 起环境 `.venv` 变了。**但只影响 agent 的 shell 自检，不影响产物计算。** |

## 6. 处置与不处置的理由

- **不关闭 SAC**：那是系统级安全设置，本项目不该动它，也不该为跑实验去削弱它。
- **不在批次中途重建环境**：重建会造成「另一次不一致」——比一个**已知且恒定**的
  条件更糟。第一批的教训正是「中途改动让两批不可比」。
- **不重建环境再跑第三批**：SAC 不关，重建出来的环境**照样**被拦，
  换汤不换药。
- **要做的是记下来**：即本文件。复核者应把「环境自检失败」当成这批运行
  的一个**恒定的环境条件**，而不是某一次运行的偶发故障。

## 6b. 补记（2026-10-04 晚）：SAC 的拦截**已自行解除**，本批当时确实被拦

复核 SEC-008 时闸门第 8 项报出「环境自带 .venv **可**正常 import sklearn 原生扩展」——
这与本批运行时的结论相反，于是直接复测：

```
cd D:/eeg-agent-work/env
./.venv/Scripts/python.exe -c "from sklearn.linear_model._sgd_fast import *"   → 成功
./.venv/Scripts/python.exe -m pytest tests/ -q                                 → 42 passed
```

而 **Smart App Control 仍然开着**（`VerifiedAndReputablePolicyState = 1`）；
当初被拦的那类「新复制的 .pyd」现在也能通过应用控制检查
（复测时它报的是 `dynamic module does not define module export function`，
那是**我加载时用错了模块名**，不是被拦）。

**结论**：
- §3–§6 记录的是**运行当时**的事实，**没有错**——那 10 次运行的第三步自检确实全失败，
  run-04 的 agent 也确实为此重写了 1750 个文件。
- 但那个条件是**暂时性的**：SAC 会随时间建立信誉判定，之后不再拦同一批文件。
  （此处**不臆测机制**；只记录「开着、但已不拦」这个可复测的事实。）
- **对本批数据的影响不变**：口径 A 从来不受影响（MCP 由主仓库 venv 运行）。
  这份补记只是防止后来者把「当时被拦」误读成「现在也一定被拦」。
- 复测命令已并入 §7。

## 7. 复核入口

```bash
# 会话键中性（应 PASS；对第一批同一命令应 FAIL）
.venv/Scripts/python.exe scripts/check_blinding_act4.py \
  --env D:/eeg-agent-work/env \
  --ledger docs/evidence/act4-20261004/runs.json \
  --runner-log D:/eeg-agent-data-20261004/runner.jsonl --skip-pytest

# §3 的复现
cp <主venv>/sklearn/linear_model/_sgd_fast.cp312-win_amd64.pyd D:/sac-test/copy.pyd
D:/暂存/source/.venv/Scripts/python.exe -c "import importlib.util as u; s=u.spec_from_file_location('m',r'D:/sac-test/copy.pyd'); m=u.module_from_spec(s); s.loader.exec_module(m)"
#   → ImportError: ... 应用程序控制策略已阻止此文件。

# SAC 状态
powershell -NoProfile -Command "(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy').VerifiedAndReputablePolicyState"
#   → 1（启用）
```
