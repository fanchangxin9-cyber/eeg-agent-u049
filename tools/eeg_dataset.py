"""
eeg_dataset.py — EEGMMIDB（PhysioNet）加载与事件切分

数据集
------
EEG Motor Movement/Imagery Dataset, v1.0.0
  https://physionet.org/content/eegmmidb/1.0.0/
  109 名被试 · 64 导 EEG · 160 Hz · EDF+ · 单文件约 6–7 MB（3 个 run）
  许可：Open Data Commons Attribution License v1.0（开放数据，无需申请）

为什么不用 DEAP：DEAP 需签 EULA 并用学校邮箱申请，官方建议提前两个月。本赛事
窗口只有两周，EEGMMIDB 可由 MNE 内置加载器直连 PhysioNet 获取。

run 家族（务必区分，T1/T2 在不同家族里含义不同）
------------------------------------------------
  runs 3 / 7 / 11   实际运动：左手 vs 右手      T1=左手  T2=右手
  runs 4 / 8 / 12   想象运动：左手 vs 右手      T1=左手  T2=右手
  runs 5 / 9 / 13   实际运动：双手 vs 双脚      T1=双手  T2=双脚
  runs 6 / 10 / 14  想象运动：双手 vs 双脚      T1=双手  T2=双脚

**把不同家族混在一起会让标签静默变成错的。** 本模块据此做显式校验。
"""
from __future__ import annotations

import os

import numpy as np

EVENT_T1 = 2
EVENT_T2 = 3

# 每个家族内部的 T1/T2 含义
_FAMILY = {
    "hands_execution": [3, 7, 11],
    "hands_imagery": [4, 8, 12],
    "feet_execution": [5, 9, 13],
    "feet_imagery": [6, 10, 14],
}

TASKS: dict[str, dict] = {
    "left_vs_right_imagery": {
        "runs": [4, 8, 12],
        "family": "hands_imagery",
        "codes": {EVENT_T1: 0, EVENT_T2: 1},
        "label_names": ["left_fist", "right_fist"],
        "description": "想象左手 vs 想象右手握拳（运动想象）",
    },
    "fists_vs_feet_imagery": {
        "runs": [6, 10, 14],
        "family": "feet_imagery",
        "codes": {EVENT_T1: 0, EVENT_T2: 1},
        "label_names": ["both_fists", "both_feet"],
        "description": "想象双手 vs 想象双脚（运动想象）",
    },
    "left_vs_right_movement": {
        "runs": [3, 7, 11],
        "family": "hands_execution",
        "codes": {EVENT_T1: 0, EVENT_T2: 1},
        "label_names": ["left_fist", "right_fist"],
        "description": "实际左手 vs 实际右手握拳（真实运动，可作对照任务）",
    },
}

DEFAULT_TASK = "left_vs_right_imagery"

EXPECTED_N_CHANNELS = 64

# 加载时保留较宽窗口，真正的分析窗口交给预处理裁剪，
# 这样 agent 反复试窗口时不必重新下载数据。
LOAD_TMIN = -0.2
LOAD_TMAX = 4.0

DEFAULT_SUBJECTS = list(range(1, 11))

# 合成数据用的通道名。刻意采用标准 10-20 的运动区命名，
# 以便合成数据也能走完整的选道 / 不对称特征路径。
_SYNTH_CHANNELS = [
    "C3", "C4", "Cz", "FC3", "FC4", "CP3", "CP4",
    "C1", "C2", "C5", "C6", "FC1", "FC2", "CP1", "CP2", "FCz", "CPz",
]


def family_of_runs(runs: list[int]) -> str | None:
    """判断一组 run 属于哪个家族；跨家族则返回 None。"""
    fams = {f for f, r in _FAMILY.items() if set(runs) & set(r)}
    return fams.pop() if len(fams) == 1 else None


def task_info(task: str) -> dict:
    if task not in TASKS:
        raise ValueError(f"未知任务 {task!r}。可用任务：{sorted(TASKS)}")
    return TASKS[task]


def resolve_task(runs: list[int] | None, task: str | None) -> tuple[str, dict]:
    """由 runs 或 task 名解析出任务定义，并拒绝跨家族混用。"""
    if task is None:
        if runs is None:
            task = DEFAULT_TASK
        else:
            fam = family_of_runs(list(runs))
            matches = [k for k, v in TASKS.items() if v["family"] == fam]
            if not matches:
                raise ValueError(
                    f"run 列表 {runs} 跨越了多个任务家族或不属于任何已知家族。"
                    f"各家族为：{_FAMILY}。请勿混合，否则 T1/T2 标签含义会冲突。"
                )
            task = matches[0]
    info = task_info(task)
    if runs is not None and set(runs) - set(info["runs"]):
        raise ValueError(
            f"任务 {task!r} 使用 runs {info['runs']}，但你传入了 {sorted(set(runs) - set(info['runs']))}。"
            "请只使用该任务的 run，或显式指定匹配的任务名。"
        )
    return task, info


def _configure_mne_download() -> str:
    """把 EEGMMIDB 的下载路径固定下来，并确保目录存在。

    两件事缺一不可：

    1. `eegbci.load_data` 的 `update_path` 若为默认值，MNE 会**交互式询问**
       是否修改数据目录。stdio MCP server 没有 TTY，这个提示会让进程直接挂住，
       表现成"AGH 启动不了"而不是报错。所以调用处显式传 `update_path=False`。

    2. 但 `update_path=False` 的代价是：**MNE 不会自动创建目录**，目录不存在时
       直接抛 "Download location ... does not exist"。所以这里必须先建好。
    """
    base = os.environ.get("MNE_DATA") or os.path.join(os.path.expanduser("~"), "mne_data")
    target = os.environ.get("MNE_DATASETS_EEGBCI_PATH") or os.path.join(base, "EEGBCI")
    os.makedirs(target, exist_ok=True)
    os.environ["MNE_DATASETS_EEGBCI_PATH"] = target
    return target


def _load_one_subject(subject: int, runs: list[int], retries: int = 3,
                      verbose: bool = False) -> tuple[object, list[str], int]:
    """读取单个被试的若干 run。

    返回 (raw, 本地文件列表, 下载重试次数)。下载失败会退避重试——
    外部能力（网络）失败是真实存在的，这个重试记录本身就是一条可展示的恢复路径。
    """
    import time

    import mne
    from mne.datasets import eegbci
    from mne.io import concatenate_raws, read_raw_edf

    _configure_mne_download()

    fnames = None
    attempts = 0
    last_err: Exception | None = None
    for attempt in range(retries):
        attempts = attempt + 1
        try:
            fnames = eegbci.load_data(subject, runs, update_path=False, verbose=verbose)
            break
        except Exception as exc:  # noqa: BLE001 — 网络类失败统一重试
            last_err = exc
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    if fnames is None:
        raise RuntimeError(
            f"被试 {subject} 的数据下载失败（已重试 {retries} 次）：{last_err}"
        )

    raws = [read_raw_edf(f, preload=True, verbose=verbose) for f in fnames]
    raw = concatenate_raws(raws, verbose=verbose)
    eegbci.standardize(raw)  # 'Fc5.' → 'FC5'

    # EEGMMIDB 是 64 导。数量不符通常意味着版本差异或 stim 通道残留，
    # 一旦带进后续流程会污染通道名与特征矩阵，所以在这里就失败。
    n_ch = len(raw.ch_names)
    if n_ch != EXPECTED_N_CHANNELS:
        raise RuntimeError(
            f"被试 {subject} 的通道数为 {n_ch}，预期 {EXPECTED_N_CHANNELS}。"
            "可能是 MNE 版本差异或 stim 通道残留，需要人工确认后再继续。"
        )

    return raw, list(fnames), attempts


def _epoch_one_subject(raw, codes: dict[int, int], tmin: float, tmax: float):
    """按注释切事件段。返回 X（伏特）、y、通道名、采样率、注释统计。"""
    import mne
    from mne import Epochs, events_from_annotations, pick_types

    # 显式限定 event_id，否则 T0（静息）会被一并切进来，
    # 让任务变成近随机的三分类，看起来像是"模型不行"。
    events, _ = events_from_annotations(
        raw, event_id={"T1": EVENT_T1, "T2": EVENT_T2}, verbose=False
    )
    counts = {int(c): int((events[:, -1] == c).sum()) for c in (EVENT_T1, EVENT_T2)}

    epochs = Epochs(
        raw, events,
        event_id={"T1": EVENT_T1, "T2": EVENT_T2},
        tmin=tmin, tmax=tmax, baseline=None, preload=True, verbose=False,
    )
    pick_idx = pick_types(epochs.info, meg=False, eeg=True, stim=False,
                          eog=False, exclude="bads")
    epochs.pick(pick_idx, verbose=False)

    X = epochs.get_data(copy=True)          # (epochs, channels, times)，单位伏特
    y = np.array([codes[int(c)] for c in epochs.events[:, -1]], dtype=int)

    return X, y, list(epochs.ch_names), float(epochs.info["sfreq"]), counts


def load(subjects: list[int] | None = None, task: str = DEFAULT_TASK,
         runs: list[int] | None = None, verbose: bool = False) -> dict:
    """加载多个被试并拼成一份样本集。

    单个被试失败**不会**中断整体——失败记录在 failures / per_subject 里，
    交由 agent 决定如何处置（跳过、换阈值、还是放弃该任务）。
    """
    task, info = resolve_task(runs, task)
    runs = info["runs"]
    codes = info["codes"]
    subjects = subjects or DEFAULT_SUBJECTS

    Xs, ys, subs = [], [], []
    per_subject: list[dict] = []
    failures: list[dict] = []
    ch_names: list[str] | None = None
    sfreq: float | None = None

    for subj in subjects:
        try:
            raw, _files, attempts = _load_one_subject(subj, runs, verbose=verbose)
            X, y, names, sf, counts = _epoch_one_subject(raw, codes, LOAD_TMIN, LOAD_TMAX)
        except Exception as exc:  # noqa: BLE001 — 逐被试容错是刻意设计
            failures.append({"subject": subj, "error": f"{type(exc).__name__}: {exc}"})
            per_subject.append({"subject": subj, "ok": False, "reason": str(exc)})
            continue

        if X.shape[0] == 0:
            failures.append({"subject": subj, "error": "没有切出任何事件段"})
            per_subject.append({"subject": subj, "ok": False,
                                "reason": "没有切出任何事件段"})
            continue

        if ch_names is None:
            ch_names, sfreq = names, sf
        elif names != ch_names:
            failures.append({"subject": subj, "error": "通道集合与其他被试不一致"})
            per_subject.append({"subject": subj, "ok": False,
                                "reason": f"通道不一致（{len(names)} vs {len(ch_names)}）"})
            continue
        elif abs(sf - sfreq) > 1e-6:
            failures.append({"subject": subj, "error": "采样率与其他被试不一致"})
            per_subject.append({"subject": subj, "ok": False,
                                "reason": f"采样率不一致（{sf} vs {sfreq}）"})
            continue

        Xs.append(X)
        ys.append(y)
        subs.append(np.full(X.shape[0], subj, dtype=int))
        per_subject.append({
            "subject": subj, "ok": True, "n_epochs": int(X.shape[0]),
            "n_t1": counts[EVENT_T1], "n_t2": counts[EVENT_T2],
            "download_attempts": attempts,
        })

    if not Xs:
        raise RuntimeError(
            "所有被试都加载失败。请检查网络（需从 PhysioNet 下载）与被试编号。"
            f"失败明细：{failures}"
        )

    return {
        "X": np.concatenate(Xs, axis=0).astype(np.float32),
        "y": np.concatenate(ys, axis=0),
        "subject_ids": np.concatenate(subs, axis=0),
        "ch_names": ch_names,
        "sfreq": float(sfreq),
        "label_names": info["label_names"],
        "task": task,
        "runs": runs,
        "family": info["family"],
        "load_window_sec": [LOAD_TMIN, LOAD_TMAX],
        "per_subject": per_subject,
        "failures": failures,
    }


def synthetic(n_subjects: int = 8, n_trials: int = 20, sfreq: float = 160.0,
              n_channels: int = 8, duration: float = 4.2, seed: int = 42) -> dict:
    """合成数据。

    **仅供单元测试与故障演练，不得用于任何结果汇报。**
    产物的 meta 里带 is_synthetic=True，`eeg_evidence` 会拒绝引用它，
    因此它不可能悄悄进入正式结论。
    """
    rng = np.random.default_rng(seed)
    n_times = int(sfreq * duration)
    t_axis = np.arange(n_times) / sfreq

    Xs, ys, subs = [], [], []
    for subj in range(1, n_subjects + 1):
        for _ in range(n_trials):
            label = int(rng.integers(0, 2))
            trial = np.zeros((n_channels, n_times))
            a_amp, b_amp = (1.0, 0.2) if label == 0 else (0.3, 1.2)
            for ch in range(n_channels):
                trial[ch] += a_amp * np.sin(2 * np.pi * 10 * t_axis + rng.random())
                trial[ch] += b_amp * np.sin(2 * np.pi * 20 * t_axis + rng.random())
                trial[ch] += 0.3 * rng.standard_normal(n_times)
            # 缩放到真实脑电的幅值量级（中位约 10 µV）。
            # 若沿用 1e-6 会得到 ~0.7 µV，触发"幅值远低于常见量级"的诊断告警，
            # 让测试数据看起来像坏数据。
            Xs.append((trial * 1.5e-5).astype(np.float32))
            ys.append(label)
            subs.append(subj)

    if n_channels > len(_SYNTH_CHANNELS):
        raise ValueError(
            f"合成数据最多支持 {len(_SYNTH_CHANNELS)} 个运动区通道，收到 {n_channels}。"
        )

    return {
        "X": np.stack(Xs),
        "y": np.array(ys, dtype=int),
        "subject_ids": np.array(subs, dtype=int),
        # 用真实运动区通道名，而不是 EEG001 这种占位名。
        # 这样合成数据走的是和真实数据一样的选道路径，测试才有意义。
        "ch_names": _SYNTH_CHANNELS[:n_channels],
        "sfreq": float(sfreq),
        "label_names": ["left_fist", "right_fist"],
        "task": "synthetic",
        "runs": [],
        "family": "synthetic",
        "load_window_sec": [LOAD_TMIN, LOAD_TMAX],
        "per_subject": [{"subject": s, "ok": True} for s in range(1, n_subjects + 1)],
        "failures": [],
        "is_synthetic": True,
    }
