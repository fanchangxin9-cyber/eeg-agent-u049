"""
eeg_mcp_server.py — 把 EEG 分析能力暴露为 MCP 工具

AGH 通过 stdio 拉起本进程（见 docs/agh_setup.md）。

两条硬规则
----------
1. **stdout 是 JSON-RPC 通道。** 任何调试输出都必须写 stderr，否则会污染协议，
   表现为"AGH 连不上工具"而不是报错。MNE 的日志同样强制 verbose=False。
2. **没有合成数据回退。** 输入缺失一律返回结构化错误。合成数据只经
   `eeg_load_synthetic` 这一个显式入口进入，且产物的 meta 里带
   is_synthetic=True，`eeg_evidence` 会拒绝引用它——因此它不可能悄悄混进结论。

返回值约定（**失败一定统一；成功各有各的形状**）
------------------------------------------------
**失败**——13 个工具全部统一，无一例外：

  {"ok": false, "error": {"code","message","recoverable","suggestions"}}

**成功**——没有单一形状。下表是**实测**出来的顶层键（不是推想）：

| 工具 | 成功时的顶层键 |
|---|---|
| `eeg_fetch` `eeg_preprocess` `eeg_features` `eeg_evaluate` `eeg_validate` `eeg_null_twin` | `ok` `handle` `summary` (+`next_step`/`note`) |
| `eeg_trial_run` `eeg_load_synthetic` | `ok` `handle` `summary` (+`next_step`/`warning`) |
| `eeg_artifacts` | `ok` `summary` `cache_dir` `index` —— **没有 `handle`** |
| `eeg_defect_rate` | `ok` `summary` `note` `refused` —— **没有 `handle`** |
| `eeg_ablation` | `ok` `baseline` `agent` `delta_balanced_accuracy` `fairness` `verdict` |
| `eeg_evidence` | `ok` `claims` `provenance` `refused` `rule` |
| `eeg_inspect` | `handle` `kind` `healthy` `warnings` `flat_channels` `amplitude_uv` … —— **连 `ok` 都没有** |

也就是说，**别假设成功返回里有 `ok` 或 `handle`**——按工具查上表。
（这张表由 `tests/test_mcp_envelope.py::test_成功返回的形状与本文档一致` 逐格核对。）

> ⚠️ **为什么不统一成一种形状**：本项目整个立论建立在「agent 在它熟悉的环境里会怎么做」
> 上，而第四幕两批实测用的就是**现有**这些形状。把 `eeg_inspect` 之类改成信封，
> 会改变 agent 的输入，**两批第四幕证据会因此失去可比性**。
> 所以这里选择**把文档改成如实的**，而不是改行为。（审验编号 SEC-011）
"""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import eeg_cache as cache
import eeg_pipeline as pipe

# MCP SDK 2.x 把 FastMCP 更名为 MCPServer（模块路径也变了）。
# 两代的用法在这里是兼容的，所以两代都支持，避免因为团队装的版本不同而无法启动。
try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # mcp 1.x
    try:
        from mcp.server.fastmcp import FastMCP as _Server
    except ImportError:
        print(
            "找不到 MCP SDK。请先执行：\n"
            "  .venv/Scripts/python.exe -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise

mcp = _Server("eeg-agent")


def _ok(handle: str | None = None, summary: Any = None, **extra) -> str:
    payload = {"ok": True}
    if handle:
        payload["handle"] = handle
    if summary is not None:
        payload["summary"] = summary
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _err(code: str, message: str, suggestions: list[str] | None = None,
         recoverable: bool = True) -> str:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message,
                                "recoverable": recoverable,
                                "suggestions": suggestions or []}},
        ensure_ascii=False, indent=2, default=str,
    )


def _guard(fn: Callable[[], str]) -> str:
    """统一把异常翻译成结构化错误，绝不让 traceback 泄漏到协议通道。"""
    try:
        return fn()
    except cache.CacheError as exc:
        return json.dumps(exc.as_dict(), ensure_ascii=False, indent=2, default=str)
    except FileNotFoundError as exc:
        return _err("E_FILE_NOT_FOUND", str(exc))
    except ValueError as exc:
        return _err("E_BAD_ARGUMENT", str(exc), recoverable=False)
    except MemoryError:
        return _err("E_OUT_OF_MEMORY",
                    "内存不足。请减少被试数量或缩短分析窗口后重试。")
    except Exception as exc:  # 兜底，避免任何异常打断协议
        # **只把异常类型回给调用方**（SEC-010）。
        # `str(exc)` 常带本机绝对路径（FileNotFoundError / OSError 尤其如此），
        # 而它会进入 agent 上下文，也可能随会话导出进仓库（见 scripts/export_session.py
        # 的脱敏表——那里替换家目录与用户名，但替换不掉项目路径）。
        # 完整信息写 stderr：本文件开头已声明「stdout 是 JSON-RPC 通道，
        # 任何调试输出都必须写 stderr」。
        print(f"[eeg-agent] E_INTERNAL {type(exc).__name__}: {exc}", file=sys.stderr)
        return _err("E_INTERNAL", type(exc).__name__,
                    suggestions=[("可用 eeg_artifacts 查看当前已有产物，"
                                  "必要时从上游步骤重新生成。"),
                                 "详细原因已写入 server 的 stderr。"],
                    recoverable=True)


# ------------------------------------------------------------------ 工具
@mcp.tool()
def eeg_fetch(subjects: list[int] | None = None,
              task: str = "left_vs_right_imagery",
              runs: list[int] | None = None) -> str:
    """从 EEGMMIDB（PhysioNet 开放数据）下载并切分 EEG 事件段。

    task 可选：
      left_vs_right_imagery  — 想象左手 vs 想象右手（默认，运动想象）
      fists_vs_feet_imagery  — 想象双手 vs 想象双脚
      left_vs_right_movement — 实际左手 vs 实际右手（对照任务）
    也可直接用 runs 指定，但**不可混用不同家族的 run**，否则 T1/T2 标签会失效。

    subjects 默认 1–10。单个被试失败不会中断整体，失败明细见返回值。
    首次调用会从网络下载数据，需要一些时间。
    """
    def run() -> str:
        handle = pipe.fetch(subjects=subjects, task=task, runs=runs)
        meta = cache.describe(handle)["meta"]
        return _ok(handle, {
            "task": meta["task"],
            "family": meta["family"],
            "source": meta["source"],
            "subjects_loaded": meta["subjects_loaded"],
            "n_epochs": meta["n_epochs"],
            "n_channels": meta["n_channels"],
            "sfreq": meta["sfreq"],
            "load_window_sec": meta["load_window_sec"],
            "label_names": meta["label_names"],
            "per_subject": meta["per_subject"],
        }, failures=meta["failures"],
           next_step="先调用 eeg_inspect 查看数据质量与诊断告警，再决定预处理参数。")
    return _guard(run)


@mcp.tool()
def eeg_inspect(handle: str) -> str:
    """查看某一步产物的元信息与**质量诊断**。

    返回的 warnings 是后续决策的依据：幅值量级异常、平坦通道、类别不平衡、
    被试样本过少等。请根据诊断结论决定预处理策略，而不是套用固定参数。
    """
    return _guard(lambda: json.dumps(pipe.inspect(handle), ensure_ascii=False,
                                     indent=2, default=str))


@mcp.tool()
def eeg_preprocess(handle: str, low_hz: float = 8.0, high_hz: float = 30.0,
                   notch_hz: float | None = None,
                   crop_sec: list[float] | None = None,
                   reject_uv: float | None = None,
                   drop_channels: list[str] | None = None,
                   channel_set: str = "all",
                   reref: str = "none") -> str:
    """裁剪 / 选道 / 陷波 / 带通 / 重参考 / 伪迹剔除，返回 clean_* handle。

    参数说明（都可按诊断结论调整）：
      low_hz/high_hz  带通频带。运动想象的经典频带是 8–30 Hz（mu 与 beta）。
      notch_hz        工频陷波，如 50 或 60。
      crop_sec        分析窗口，相对事件起点的秒数，如 [0.5, 3.5]。
                      数据加载窗口是 [-0.2, 4.0]，可在此范围内任选。
                      **这个参数在实测中影响很大**，值得单独试几组。
      reject_uv       伪迹阈值，单位**微伏**（数据内部是伏特，已做换算）。
                      不给则不做剔除。返回值含 reject_pct_by_subject，
                      便于判断是哪个被试被剔得太多。
      drop_channels   要剔除的通道名，通常来自 eeg_inspect 的 flat_channels。
      channel_set     all（默认）— 保留全部通道。motor — 只保留运动皮层通道。
      reref           none（默认）— 原始记录参考。car — 共平均参考。

    ⚠️ channel_set 与 reref 的默认值是在真实数据上实测选出来的，不是照搬教科书：
    CAR 实测**有害**（0.552→0.528），选运动区通道实测**基本无用**（0.552→0.551）。
    原因是 CSP 本身就是空间滤波器，会自己学出最优权重，手动做空间预处理反而冲突。
    你若想改这两个参数，请先跑一遍对照并说明理由。

    另外注意：**特征方案的选择比预处理调参重要得多**。
    bandpower 实测被试内约 0.55，而 CSP 可达 0.63（且置换检验显著）。
    """
    def run() -> str:
        h = pipe.preprocess(handle, low_hz, high_hz, notch_hz, crop_sec,
                            reject_uv, drop_channels, channel_set, reref)
        m = cache.describe(h)["meta"]
        return _ok(h, {
            "n_epochs_in": m["n_epochs_in"],
            "n_epochs_out": m["n_epochs"],
            "n_rejected": m["n_rejected"],
            "dropped_ratio": m["dropped_ratio"],
            "reject_pct_by_subject": m["reject_pct_by_subject"],
            "rejected_by_channel": m["rejected_by_channel"],
            "n_channels": m["n_channels"],
            "channel_set": m["channel_set"],
            "reref": m["reref"],
            "crop_sec": m["crop_sec"],
            "warnings": m["warnings"],
        }, next_step="接着调用 eeg_features 提取特征，或 eeg_evaluate(use_csp=True) "
                     "直接在事件段上做 CSP 解码。")
    return _guard(run)


@mcp.tool()
def eeg_features(handle: str, feature_set: str = "bandpower",
                 bands: list[str] | None = None,
                 normalize: str = "subject") -> str:
    """从 clean 产物提取特征，返回 feat_* handle。

    feature_set:
      bandpower           — 每通道每频段的对数功率
      bandpower+asymmetry — 额外加入同源电极对的左右差值。运动想象的生理标志是
                            C3/C4 一带 mu/beta 的对侧偏侧化，该特征有明确物理含义。
    bands 常用：["mu", "beta"]（8–13 / 13–30 Hz）；也可加 delta/theta/gamma。
    normalize:
      subject（默认）— 按被试各自 z-score。跨被试解码时各人整体幅度差异极大，
                       不归一化会把准确率压到随机水平。不使用标签，不构成泄漏。
      none          — 不归一化。
    """
    def run() -> str:
        h = pipe.features(handle, feature_set, bands, normalize)
        m = cache.describe(h)["meta"]
        return _ok(h, {
            "feature_set": m["feature_set"],
            "bands": m["bands"],
            "normalize": m["normalize"],
            "n_features": m["n_features"],
            "n_epochs": m["n_epochs"],
            "zero_variance_features": m["zero_variance_features"],
            "warnings": m["warnings"],
        }, next_step="调用 eeg_evaluate 拿到指标。")
    return _guard(run)


@mcp.tool()
def eeg_evaluate(handle: str, model: str = "lda", use_csp: bool = False,
                 cv_folds: int = 5, cv_scheme: str = "within_subject") -> str:
    """交叉验证，返回 eval_* handle 与指标。

    这是你的**反馈信号**：拿到指标后据此调整配置，再跑一次比较。

    model:     lda / svm / logreg
    use_csp:   用 CSP + 分类器（输入必须是 clean 产物，不能是特征矩阵）。
               CSP 在每折内单独拟合，测试折不参与，因此不会泄漏。
    cv_scheme: within_subject（默认）— 每个被试内部按试次划分，训练与测试来自
                 同一个人。这是 BCI 的标准标定协议，衡量"在该使用者身上能否
                 解出运动想象"。
               cross_subject — 按被试分组，测试被试完全未参与训练。衡量"能否不
                 做标定就套用到新使用者"。这是公认的难题，小被试集上通常接近
                 随机水平，不要拿它当唯一指标。

    两种协议回答不同问题，报告里必须写明用的是哪一种。
    评估协议其余部分（折数、指标定义、随机种子）是冻结的。
    """
    def run() -> str:
        h = pipe.evaluate(handle, model, use_csp, cv_folds, cv_scheme)
        m = cache.describe(h)["meta"]
        return _ok(h, {"config": m["config"], "metrics": m["metrics"],
                       "interpretation": m["interpretation"]},
                   note="请写明本次用的是哪种 cv_scheme，并与之前几次比较说明调整依据。")
    return _guard(run)


@mcp.tool()
def eeg_validate(handle: str, scheme: str = "shuffle_control",
                 test_subjects: list[int] | None = None, model: str = "lda",
                 use_csp: bool = False, cv_folds: int = 5,
                 n_permutations: int = 10,
                 cv_scheme: str = "within_subject",
                 seed: int = 0,
                 batch_handles: list[str] | None = None) -> str:
    """独立验证，返回 eval_* handle。

    scheme:
      shuffle_control — 打乱标签重跑同一套交叉验证若干次。若真实标签下的准确率
                        显著高于打乱后的分布，说明结果不是流程泄漏造成的。
      shuffle_control_combine — 合并多批置换，得到更充分的检验。
                        重要：置换次数**直接决定 p 值能达到多小**
                        （p 最小为 1/(n+1)）。若观测值超过了全部打乱结果，
                        单批 10 次只能给出 p=0.0909，而 30 次可以给到 0.032。
                        CSP 的一次交叉验证约需数秒，置换次数一多就会超出单次
                        调用预算（会收到 OVERLOADED / 超时错误）。此时应：
                          1. 分多批各跑一次 shuffle_control，用不同 seed
                             （如 seed=1/2/3，每次 n_permutations=10）
                          2. 再用本方案并传入 batch_handles=[那几批的 handle]
                        各批的模型、协议、折数必须完全一致。
      holdout_subject — 留出指定被试，训练集完全不含它们。需要 test_subjects。

    cv_scheme 必须与你要验证的那次 eeg_evaluate 一致，否则比的是两回事。
    打乱策略会随协议调整：被试内协议下逐被试打乱，跨被试协议下全局打乱。
    """
    def run() -> str:
        h = pipe.validate(handle, scheme, test_subjects, model, use_csp,
                          cv_folds, n_permutations, cv_scheme, seed,
                          batch_handles)
        m = cache.describe(h)["meta"]
        return _ok(h, {k: v for k, v in m.items() if k != "is_synthetic"})
    return _guard(run)


@mcp.tool()
def eeg_ablation(agent_eval_handle: str) -> str:
    """把你的配置与**冻结基线**对比。

    基线写死在代码里：8–30 Hz、bandpower 特征、LDA、共平均参考关闭、
    全部通道，评估协议与折数**自动与你的那次评估保持一致**，保证可比。

    对比由服务端计算，你只能引用结论，不能自行宣称。
    返回 verdict：agent_config_better / no_difference / baseline_better。

    实测参考：bandpower 基线被试内约 0.552；换 CSP 可达 0.632。
    如果你的配置没超过基线，如实报告——那也是一个有效结论。
    """
    return _guard(lambda: json.dumps(pipe.ablation(agent_eval_handle),
                                     ensure_ascii=False, indent=2, default=str))


@mcp.tool()
def eeg_evidence(eval_handles: list[str]) -> str:
    """收集**可以写进报告的数值**。

    规则：最终报告里出现的每一个数字都必须能在返回的 claims 中找到。
    没有跑过的数字不许写——这不是建议，是硬约束。
    基于合成数据的评估会被自动拒绝。
    """
    return _guard(lambda: json.dumps(pipe.evidence(eval_handles),
                                     ensure_ascii=False, indent=2, default=str))


@mcp.tool()
def eeg_artifacts(kind: str | None = None, limit: int = 10) -> str:
    """列出当前已有的产物 handle。

    当某个 handle 失效（E_HANDLE_NOT_FOUND）时，用它找回可用的 handle，
    而不必从头重跑整条流水线。
    """
    return _guard(lambda: _ok(summary=cache.list_recent(kind, limit),
                              cache_dir=str(cache.cache_root()),
                              index=str(cache.index_path())))


@mcp.tool()
def eeg_load_synthetic(n_subjects: int = 8, n_trials: int = 20) -> str:
    """载入**合成数据**，仅用于验证工具链是否连通。

    合成数据不是实验结果，`eeg_evidence` 会拒绝引用它。
    演示与提交材料中不得使用由它产生的任何数字。
    """
    def run() -> str:
        import numpy as np
        import eeg_dataset as dataset
        d = dataset.synthetic(n_subjects=n_subjects, n_trials=n_trials)
        h = cache.put(
            "raw",
            {"X": d["X"].astype(np.float32), "y": d["y"],
             "subject_ids": d["subject_ids"]},
            {**{k: d[k] for k in ("sfreq", "ch_names", "label_names", "task",
                                  "load_window_sec")},
             "n_epochs": int(d["X"].shape[0]), "n_channels": int(d["X"].shape[1]),
             "runs": [], "family": "synthetic", "subjects_loaded": list(range(1, n_subjects + 1)),
             "is_synthetic": True,
             "source": "synthetic（仅供工具链自检，不得用于结论）",
             "dataset_url": None},
            params={"synthetic": True, "n_subjects": n_subjects, "n_trials": n_trials},
        )
        return _ok(h, {"is_synthetic": True, "n_epochs": int(d["X"].shape[0])},
                   warning="合成数据。可用于自检工具链，但结论中不得引用其结果。")
    return _guard(run)


# ------------------------------------------------------- 零信号试验台
# 这三个工具把「零信号对照实验」交回给 agent 自己驱动：
# agent 造孪生体 → 逐个跑搜索 → 汇总虚报率 → 写报告。
# 核心任务在 AGH 里完成，脚本只负责递样本。

def _testbed_root():
    """试验产物的去向。

    返回 None = 落进**当前 cache 根**，与常规产物同处一地。这是刻意的：
    实验员（agent）用它跑零信号对照，产物必须能被 `eeg_evidence` /
    `eeg_defect_rate` 找到，否则数字进不了证据链。
    """
    return None


@mcp.tool()
def eeg_null_twin(source_handle: str, seed: int,
                  scheme: str = "within_subject") -> str:
    """用一份**真实**数据造出「零信号孪生体」：脑电一模一样，标签打乱。

    ⚠️ 这不是合成数据。数据是真的，只是「哪一段是左手」这个信息被抹掉了。
    因此 `eeg_evidence` **会照常放行**它产出的数字——这正是本实验要说明的：
    问题不在数字是假的，在数字是真的而结论仍然是假的。

    孪生体产在独立目录（试验台目录），不会混进正式产物目录。

    注意：孪生体**不携带**任何「我是孪生体」的标记，其 meta/params 与真品
    逐字节相同。身份只记在实验员侧的旁路台账里。
    """
    def run() -> str:
        import eeg_testbed as tb
        # source_root=None 表示「用当前 cache 根」。
        # 不能传 cache.cache_root()——它返回的是已带版本号的路径
        # (.../artifacts/v1)，再当环境变量设进去会被二次追加成 .../v1/v1。
        h = tb.make_twin(source_handle, seed, scheme=scheme,
                         source_root=None, dest_root=_testbed_root())
        return _ok(h, {"twin_of": source_handle, "seed": seed, "scheme": scheme,
                       "note": "真实数据 + 打乱标签。不是合成数据，证据层会放行。"},
                   next_step="用 eeg_trial_run 在这个 handle 上跑搜索，"
                             "或把它当作普通 raw 交给常规分析流程。")
    return _guard(run)


@mcp.tool()
def eeg_trial_run(source_handle: str, seed: int, strategy: str = "hill",
                  budget: int = 24, n_perm: int = 30) -> str:
    """在零信号数据上跑**一次完整搜索试验**，并判定是否「发现显著效应」。

    流程与当年真人 agent 经历的完全一致：
        搜索 budget 个配置 → 选中最好的那个 → 在该配置上做 n_perm 次置换检验
        → 若 p < 0.05 就报告「发现了显著效应」

    这里数据里没有任何信号，所以每一次「显著」都是**虚报**。

    strategy:
      hill   — 爬山法：不会推理，但会朝高分方向走。
      random — 随机搜索：不学习，纯抽样。

    ⚠️ **不要预设哪一种是"正确"的对照。** 早期版本声称随机搜索分数天然偏低、
    只能当地板，已被实测推翻：零信号数据上所有配置的期望值都是 0.5，
    根本不存在「烂配置」，没有结构可供自适应利用。
    16 次试验的配对比较给出 mean(hill − random) = +0.0039，t = +0.46——
    无可辨别的差别。两种都跑、分开汇总，**差别本身（或没有差别）就是结论**。

    ⏱ 耗时：hill + budget=24 约 2–4 分钟（含置换检验）。budget 越大越慢。
    """
    def run() -> str:
        import eeg_testbed as tb
        res = tb.run_trial(source_handle, seed, root=_testbed_root(),
                           strategy=strategy, budget=budget, n_perm=n_perm,
                           source_root=None)   # None = 当前 cache 根，见 eeg_null_twin 注释
        summary = {k: res[k] for k in (
            "strategy", "n_evaluated", "observed", "rank_of_chosen", "p_value",
            "null_mean", "null_max", "n_perm", "significant", "chosen_config")}
        return _ok(res["artifact"], summary,
                   next_step="把返回的 handle 收集起来，跑够若干次后用 eeg_defect_rate 汇总。")
    return _guard(run)


@mcp.tool()
def eeg_defect_rate(trial_handles: list[str], alpha: float = 0.05) -> str:
    """把若干次 `eeg_trial_run` 的结果汇总成**虚报率**。

    虚报率 = 在零信号数据上，这套流程报出「显著」的比例。
    所有"发现"都必然是假的——因为根本没有信号可被发现。

    同时给出理论对照线 B/(B+n_perm)：若所有配置零分布相同且搜索可交换，
    虚报率应当等于它。**实测值高于它，才说明偏差不只是"选择"**，
    还有配置异质或自适应搜索的额外贡献。
    """
    def run() -> str:
        import eeg_testbed as tb
        trials, refused = [], []
        for h in trial_handles:
            try:
                rec = cache.describe(h)
            except cache.CacheError as exc:
                refused.append({"handle": h, "reason": exc.message})
                continue
            meta = rec["meta"]
            if meta.get("scheme") != "zero_signal_trial":
                refused.append({"handle": h,
                                "reason": "不是零信号试验产物"
                                          f"（scheme={meta.get('scheme')!r}）"})
                continue
            cfg = meta.get("config", {})
            trials.append({
                "p_value": meta["p_value"],
                "observed": meta["observed_balanced_accuracy"],
                "rank_of_chosen": meta.get("rank_of_chosen"),
                "strategy": cfg.get("strategy"),
                "budget": cfg.get("budget"),
                "n_perm": cfg.get("n_perm"),
                # 试验装置的身份。defect_rate 会拒绝混合版本——同一组参数在
                # 不同实现下给出过不同数字，混在一起的平均值没有意义。
                "testbed_code_version": meta.get("testbed_code_version"),
            })

        if not trials:
            return _ok(summary={"n_trials": 0}, refused=refused,
                       note="没有可汇总的试验。先调用 eeg_trial_run。")

        out = tb.defect_rate(trials, alpha=alpha)
        budgets = {t["budget"] for t in trials}
        perms = {t["n_perm"] for t in trials}
        if len(budgets) == 1 and len(perms) == 1:
            out["analytical_baseline"] = tb.analytical_baseline(
                int(budgets.pop()), int(perms.pop()))
        strategies = sorted({t["strategy"] for t in trials})
        out["strategies"] = strategies
        return _ok(summary=out, refused=refused,
                   rule="虚报率的每一个输入都来自 eeg_trial_run 的产物，"
                        "可逐个回溯；未跑过的数字不许写进报告。")
    return _guard(run)


if __name__ == "__main__":
    print(f"[eeg-agent] 启动 MCP server；产物目录 {cache.cache_root()}", file=sys.stderr)
    print(f"[eeg-agent] 执行记录 {cache.index_path()}", file=sys.stderr)
    mcp.run()
