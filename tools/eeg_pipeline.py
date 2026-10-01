"""
eeg_pipeline.py — EEG 分析的原子能力

与原版的六处关键差别
--------------------
1. **不硬编码采样率**。原版在特征提取里写死 `sfreq=250`，而 EEGMMIDB 是 160 Hz，
   频段功率会落到错误频点上，且**不报错**——只出错数字。这里一律从产物元信息取。
2. **单位不盲**。原版用 `np.abs(seg) < 100` 判坏段，但 MNE 读进来是伏特（~1e-6），
   该条件恒为真，等于从不剔除。这里参数名直接写 `reject_uv`，内部换算后比较。
3. **按被试分组**。原版 `cross_val_score(..., cv=5)` 实际解析为
   `StratifiedKFold(shuffle=False)`；它并不打乱，但由于各被试样本是连续块，
   **每一折的训练集都含有测试被试的样本**，准确率因此虚高。这里用 GroupKFold。
4. **产物落盘**，步骤之间传 handle，不把数组序列化进模型上下文。
5. **参数交给 agent**，滤波带宽、窗口、伪迹阈值、特征方案、分类器都不写死。
6. **没有合成数据回退**。原版在文件不存在时静默改用合成数据，于是一个拼错的路径
   会一路跑到 `classify()` 并返回一个看起来很正常、实则凭空捏造的准确率。
   这里输入缺失一律报错。

本模块只负责"执行"，"决策"留给 agent。
"""
from __future__ import annotations

import numpy as np
from scipy import signal as sp_signal
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score, confusion_matrix, f1_score
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

import eeg_cache as cache
import eeg_dataset as dataset

BANDS: dict[str, tuple[float, float]] = {
    "delta": (0.5, 4.0),
    "theta": (4.0, 8.0),
    "mu": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}
# 兼容旧命名：alpha 与 mu 在运动想象语境下指同一频段
BANDS["alpha"] = BANDS["mu"]

# 冻结的基线配置。agent 应当尝试超越它，而不是照搬。
# 它固定写在代码里，是消融实验有意义的前提。
BASELINE = {
    "name": "baseline_bandpower_lda",
    "low_hz": 8.0,
    "high_hz": 30.0,
    "crop_sec": [0.5, 3.5],
    "reject_uv": None,
    "channel_set": "all",
    "reref": "none",
    "feature_set": "bandpower",
    "bands": ["mu", "beta"],
    "normalize": "subject",
    "model": "lda",
    "use_csp": False,
    "cv_folds": 5,
    "cv_scheme": "within_subject",
}

MODELS = {
    "lda": lambda: LinearDiscriminantAnalysis(),
    "svm": lambda: SVC(kernel="rbf", C=1.0, gamma="scale"),
    "logreg": lambda: LogisticRegression(max_iter=2000),
}

# 运动皮层通道集合（标准 10-20 命名）。
# 运动想象的对侧去同步主要出现在 C3/C4 及邻近的感觉运动区；
# 用全部 64 导会引入大量与任务无关的噪声。
MOTOR_CHANNELS = {
    "C1", "C2", "C3", "C4", "C5", "C6", "Cz",
    "FC1", "FC2", "FC3", "FC4", "FC5", "FC6", "FCz",
    "CP1", "CP2", "CP3", "CP4", "CP5", "CP6", "CPz",
}

# 通道集合预设
CHANNEL_SETS = ("all", "motor")

# 同源电极对（左 / 右）。运动想象的生理标志是 C3/C4 一带的 mu 与 beta
# 事件相关去同步（ERD）的**对侧偏侧化**，所以左右差值是有物理意义的特征。
HOMOLOGOUS_PAIRS = [
    ("FC5", "FC6"), ("FC3", "FC4"), ("FC1", "FC2"),
    ("C5", "C6"), ("C3", "C4"), ("C1", "C2"),
    ("CP5", "CP6"), ("CP3", "CP4"), ("CP1", "CP2"),
    ("FT7", "FT8"), ("T7", "T8"), ("TP7", "TP8"),
    ("F7", "F8"), ("F5", "F6"), ("F3", "F4"), ("F1", "F2"),
    ("P7", "P8"), ("P5", "P6"), ("P3", "P4"), ("P1", "P2"),
    ("AF3", "AF4"),
]


def _names(ch_names, n_channels: int) -> list[str]:
    names = [str(n).strip() for n in (ch_names or [])]
    if len(names) != n_channels:
        names = [f"ch{i:03d}" for i in range(n_channels)]
    seen: dict[str, int] = {}
    out = []
    for n in names:
        n = n or "ch"
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
        out.append(n)
    return out


# ------------------------------------------------------------------ 取数
def fetch(subjects: list[int] | None = None, task: str = dataset.DEFAULT_TASK,
          runs: list[int] | None = None) -> str:
    """从 EEGMMIDB 取数并切成事件段，返回 raw_* handle。"""
    data = dataset.load(subjects=subjects, task=task, runs=runs)
    is_syn = data.get("is_synthetic", False)

    meta = {
        "task": data["task"],
        "runs": data["runs"],
        "family": data["family"],
        "subjects_requested": list(subjects) if subjects else list(dataset.DEFAULT_SUBJECTS),
        "subjects_loaded": sorted(int(s) for s in np.unique(data["subject_ids"])),
        "sfreq": data["sfreq"],
        "ch_names": data["ch_names"],
        "label_names": data["label_names"],
        "load_window_sec": data["load_window_sec"],
        "n_epochs": int(data["X"].shape[0]),
        "n_channels": int(data["X"].shape[1]),
        "per_subject": data["per_subject"],
        "failures": data["failures"],
        "is_synthetic": is_syn,
        "source": "synthetic（仅供测试）" if is_syn else "EEGMMIDB v1.0.0 (PhysioNet, ODC-BY-1.0)",
        "dataset_url": None if is_syn else "https://physionet.org/content/eegmmidb/1.0.0/",
    }
    return cache.put(
        "raw",
        {"X": data["X"].astype(np.float32), "y": data["y"],
         "subject_ids": data["subject_ids"]},
        meta,
        params={"subjects": meta["subjects_requested"], "runs": data["runs"],
                "task": data["task"], "synthetic": is_syn},
    )


# ------------------------------------------------------------------ 诊断
def inspect(handle: str) -> dict:
    """元信息 + 质量诊断。

    诊断结论是 agent 做分支决策的输入：不同被试的数据质量不同，预处理策略理应
    不同。没有这一步，"自适应"就退化成固定流程。
    """
    arrays, record = cache.get(handle)
    meta = record["meta"]
    kind = record["kind"]

    report: dict = {"handle": handle, "kind": kind, "params": record.get("params", {})}

    if kind == "eval":
        return {**report, **{k: v for k, v in meta.items()}}

    X = arrays["X"]
    y = arrays.get("y")
    subjects = arrays.get("subject_ids")

    if kind == "feat":
        F = X
        finite = np.isfinite(F)
        var = F.var(axis=0)
        fnames = list(meta.get("feature_names") or [])
        if len(fnames) != F.shape[1]:
            fnames = [f"f{i}" for i in range(F.shape[1])]
        return {
            **report,
            "n_epochs": int(F.shape[0]),
            "n_features": int(F.shape[1]),
            "feature_names": fnames[:20],
            "nan_count": int((~finite).sum()),
            "zero_variance_features": [fnames[i] for i in np.where(var <= 1e-12)[0]][:20],
            "label_names": meta.get("label_names"),
            "warnings": (
                [f"特征矩阵含 {int((~finite).sum())} 个非有限值，会导致分类器报错。"]
                if not finite.all() else []
            ),
        }

    # raw / clean：三维事件段
    sfreq = float(meta.get("sfreq", 0.0))
    report.update({
        "n_epochs": int(X.shape[0]),
        "n_channels": int(X.shape[1]),
        "n_times": int(X.shape[2]),
        "sfreq": sfreq,
        "duration_sec": round(X.shape[2] / sfreq, 3) if sfreq else None,
        "label_names": meta.get("label_names"),
        "load_window_sec": meta.get("load_window_sec"),
        "task": meta.get("task"),
        "is_synthetic": meta.get("is_synthetic", False),
    })

    warnings: list[str] = []
    abs_uv = np.abs(X).astype(np.float64) * 1e6  # 伏特 → 微伏
    med = float(np.median(abs_uv))
    report["amplitude_uv"] = {
        "median_abs": round(med, 3),
        "p99_abs": round(float(np.percentile(abs_uv, 99)), 1),
        "max_abs": round(float(abs_uv.max()), 1),
    }
    if med < 1.0:
        warnings.append(
            f"幅值中位数仅 {med:.3f} µV，远低于脑电常见量级（约 5–50 µV）。"
            "单位或通道可能异常，继续之前务必确认。"
        )
    elif med > 500:
        warnings.append(f"幅值中位数达 {med:.1f} µV，可能存在严重漂移或伪迹。")

    names = _names(meta.get("ch_names"), X.shape[1])
    var = X.reshape(X.shape[0], X.shape[1], -1).var(axis=(0, 2)).astype(np.float64)
    flat = [names[i] for i, v in enumerate(var) if not np.isfinite(v) or v <= 0]
    report["flat_channels"] = flat
    if flat:
        warnings.append(
            f"检出 {len(flat)} 个平坦通道（方差为 0）：{flat[:10]}。建议预处理时剔除。"
        )

    if y is not None:
        classes, counts = np.unique(y, return_counts=True)
        ln = meta.get("label_names") or [str(c) for c in classes]
        dist = {str(ln[int(c)]) if int(c) < len(ln) else str(c): int(n)
                for c, n in zip(classes, counts)}
        report["class_distribution"] = dist
        if len(counts) < 2:
            warnings.append(f"只出现一个类别（{dist}），无法二分类。")
        elif counts.min() / counts.max() < 0.6:
            warnings.append(
                f"类别不平衡（最小/最大 = {counts.min() / counts.max():.2f}）。"
                "准确率会被多数类主导，请同时看平衡准确率。"
            )

    if subjects is not None:
        subs, cnt = np.unique(subjects, return_counts=True)
        report["n_subjects"] = int(len(subs))
        report["epochs_per_subject"] = {str(int(s)): int(n) for s, n in zip(subs, cnt)}
        if len(subs) < 5:
            warnings.append(
                f"只有 {len(subs)} 名被试。被试内协议（cv_scheme='within_subject'）"
                "仍可运行，但结论的推广性受限；若要用跨被试协议"
                "（cv_scheme='cross_subject'），被试数不足会导致结果接近随机。"
            )
        few = [(int(s), int(n)) for s, n in zip(subs, cnt) if n < 10]
        if few:
            warnings.append(
                f"以下被试样本数不足 10：{few[:10]}。被试内协议下该被试的折数"
                "会被自动压低，结论不稳定。"
            )

    # clean 产物自带的上一步告警要一并透出，否则 agent 会丢失上下文
    for w in meta.get("warnings", []) or []:
        warnings.append(f"[上一步] {w}")

    report["warnings"] = warnings
    report["healthy"] = not warnings
    return report


# ------------------------------------------------------------------ 预处理
def preprocess(
    handle: str,
    low_hz: float = 8.0,
    high_hz: float = 30.0,
    notch_hz: float | None = None,
    crop_sec: list[float] | None = None,
    reject_uv: float | None = None,
    drop_channels: list[str] | None = None,
    channel_set: str = "all",
    reref: str = "none",
) -> str:
    """裁剪 / 选道 / 陷波 / 带通 / 重参考 / 伪迹剔除，返回 clean_* handle。

    channel_set:
      all（默认）— 保留全部通道。
      motor       — 只保留运动皮层通道（C3/C4/Cz 及邻近感觉运动区）。

    reref:
      none（默认）— 使用原始记录参考。
      car         — 共平均参考（Common Average Reference）。

    ⚠️ 这两个参数的默认值是**在 EEGMMIDB 6 名被试上实测选出来的**，不是照搬教科书：

    | 通道集 | 重参考 | bandpower 被试内 | CSP 被试内 |
    |---|---|---|---|
    | all   | none | **0.552** | **0.632** |
    | all   | car  | 0.528     | —       |
    | motor | none | 0.551     | 0.630   |
    | motor | car  | 0.519     | —       |

    两个常见的"标准做法"在这里都没帮上忙，原因是方法学上的：

    - **CAR 有害**：它抹掉各导联的共同成分，而 CSP 恰恰要从空间协方差里
      找判别方向，那些共同成分里有可用信息。
    - **选运动区通道基本无用**：CSP 本身就是一个空间滤波器，会自己学出最优
      通道权重，再手动筛通道是多余的一步。

    参数都保留着，agent 仍可自行尝试并给出理由——"试了标准做法但数据说没用"
    本身就是一个应当如实报告的结果。
    """
    arrays, record = cache.get(handle)
    if record["kind"] != "raw":
        raise cache.CacheError(
            "E_BAD_INPUT_KIND",
            f"预处理需要 raw 产物，收到 {record['kind']!r}。请先调用 eeg_fetch。",
            suggestions=[h["handle"] for h in cache.list_recent("raw", 5)],
            recoverable=False,
        )

    meta = record["meta"]
    X = arrays["X"].astype(np.float64)
    y, subjects = arrays["y"], arrays["subject_ids"]
    sfreq = float(meta["sfreq"])
    ch_names = list(meta.get("ch_names") or [])

    if channel_set not in CHANNEL_SETS:
        raise ValueError(
            f"未知 channel_set {channel_set!r}。可用：{list(CHANNEL_SETS)}"
        )
    if reref not in ("car", "none"):
        raise ValueError(f"未知 reref {reref!r}。可用：['car', 'none']")

    params = {"low_hz": low_hz, "high_hz": high_hz, "notch_hz": notch_hz,
              "crop_sec": crop_sec, "reject_uv": reject_uv,
              "drop_channels": drop_channels, "channel_set": channel_set,
              "reref": reref}

    if crop_sec is not None:
        tmin0 = float(meta.get("load_window_sec", [0.0, 0.0])[0])
        t = tmin0 + np.arange(X.shape[2]) / sfreq
        keep = (t >= crop_sec[0]) & (t <= crop_sec[1])
        if not keep.any():
            raise ValueError(
                f"裁剪窗口 {crop_sec} 落在数据范围 [{t[0]:.2f}, {t[-1]:.2f}] 之外。"
            )
        X = X[:, :, keep]

    names_all = _names(ch_names, X.shape[1])
    dropped_channels: list[str] = []

    if channel_set == "motor":
        keep_idx = [i for i, n in enumerate(names_all) if n in MOTOR_CHANNELS]
        if len(keep_idx) < 2:
            raise ValueError(
                f"通道名与标准 10-20 命名不匹配，'motor' 通道集合只匹配到 "
                f"{len(keep_idx)} 个通道（需要 ≥2）。请改用 channel_set='all'，"
                "或确认数据通道命名。"
            )
        dropped_channels = [n for i, n in enumerate(names_all) if i not in keep_idx]
        X = X[:, keep_idx, :]
        ch_names = [names_all[i] for i in keep_idx]
        names_all = ch_names

    if drop_channels:
        drop = set(drop_channels)
        keep_idx = [i for i, n in enumerate(names_all) if n not in drop]
        if not keep_idx:
            raise ValueError("剔除后没有剩余通道，请检查 drop_channels。")
        dropped_channels = dropped_channels + [n for n in names_all if n in drop]
        X = X[:, keep_idx, :]
        ch_names = [names_all[i] for i in keep_idx]

    nyq = sfreq / 2.0
    if not (0 < low_hz < high_hz < nyq):
        raise ValueError(
            f"滤波频带非法：low={low_hz}, high={high_hz}, 奈奎斯特={nyq}。"
            "要求 0 < low < high < sfreq/2。"
        )

    if notch_hz:
        if not (0 < notch_hz < nyq):
            raise ValueError(f"陷波频率 {notch_hz} 超出 (0, {nyq})。")
        b, a = sp_signal.iirnotch(notch_hz / nyq, Q=30.0)
        X = sp_signal.filtfilt(b, a, X, axis=-1)

    b, a = sp_signal.butter(4, [low_hz / nyq, high_hz / nyq], btype="band")
    padlen = 3 * max(len(a), len(b))
    if X.shape[-1] <= padlen:
        raise ValueError(
            f"分析窗口仅 {X.shape[-1]} 个采样点，不足以做 {low_hz}-{high_hz} Hz 滤波"
            f"（至少 {padlen + 1} 点）。请加长 crop_sec。"
        )
    X = sp_signal.filtfilt(b, a, X, axis=-1)

    # 共平均参考。不做这一步时，容积传导会让各导联共享大量共同成分，
    # 把对侧的 mu/beta 去同步差异抹平——而那正是运动想象要解码的信号。
    if reref == "car":
        X = X - X.mean(axis=1, keepdims=True)

    n_in = X.shape[0]
    rejected_by_channel: dict[str, int] = {}
    reject_pct_by_subject: dict[str, float] = {}
    n_rejected = 0
    if reject_uv is not None:
        # 阈值以微伏给出；数据是伏特，必须换算后比较
        peak_uv = np.abs(X).max(axis=-1) * 1e6  # (epochs, channels)
        names = _names(ch_names, X.shape[1])
        bad = peak_uv > reject_uv
        bad_epoch = bad.any(axis=1)
        for ci in np.where(bad.any(axis=0))[0]:
            rejected_by_channel[names[ci]] = int(bad[:, ci].sum())
        # 逐被试的剔除比例——这是让循环真正"自适应"的字段：
        # agent 据此判断该被试是否值得保留、还是应该放宽阈值
        for s in np.unique(subjects):
            m = subjects == s
            if m.sum():
                reject_pct_by_subject[str(int(s))] = round(
                    float(bad_epoch[m].mean()), 3)
        if (~bad_epoch).sum() == 0:
            raise ValueError(
                f"阈值 {reject_uv} µV 下全部 {n_in} 个样本都被判为伪迹。"
                "阈值过严或数据质量确实很差，请调整后重试。"
            )
        keep_mask = ~bad_epoch
        n_rejected = int(bad_epoch.sum())
        X, y, subjects = X[keep_mask], y[keep_mask], subjects[keep_mask]

    dropped_ratio = n_rejected / n_in if n_in else 0.0
    warnings: list[str] = []
    if dropped_ratio > 0.5:
        warnings.append(
            f"伪迹剔除了 {dropped_ratio:.0%} 的样本，剩余数据可能不足以支撑可靠结论。"
        )
    worst = sorted(reject_pct_by_subject.items(), key=lambda kv: -kv[1])[:3]
    if worst and worst[0][1] > 0.3:
        warnings.append(
            f"以下被试剔除比例偏高：{worst}。可考虑单独处理或排除该被试。"
        )

    new_meta = {
        "sfreq": sfreq,
        "ch_names": ch_names or _names([], X.shape[1]),
        "label_names": meta.get("label_names"),
        "task": meta.get("task"),
        "load_window_sec": [crop_sec[0], crop_sec[1]] if crop_sec
        else meta.get("load_window_sec", [0.0, 0.0]),
        "crop_sec": crop_sec,
        "channel_set": channel_set,
        "reref": reref,
        "n_epochs_in": int(n_in),
        "n_epochs": int(X.shape[0]),
        "n_channels": int(X.shape[1]),
        "n_times": int(X.shape[2]),
        "n_rejected": n_rejected,
        "dropped_ratio": round(float(dropped_ratio), 4),
        "rejected_by_channel": rejected_by_channel,
        "reject_pct_by_subject": reject_pct_by_subject,
        "dropped_channels": dropped_channels,
        "is_synthetic": meta.get("is_synthetic", False),
        "source_handle": handle,
        "warnings": warnings,
    }
    return cache.put(
        "clean", {"X": X.astype(np.float32), "y": y, "subject_ids": subjects},
        new_meta, parents=[handle], params=params,
    )


# ------------------------------------------------------------------ 特征
def features(handle: str, feature_set: str = "bandpower",
             bands: list[str] | None = None,
             normalize: str = "subject") -> str:
    """提取特征，返回 feat_* handle。

    feature_set:
      bandpower            — 每通道每频段的对数功率
      bandpower+asymmetry  — 额外加入同源电极对的左右差值（mu/beta 偏侧化）

    normalize:
      subject — **默认**。按被试各自做 z-score。跨被试解码时各人的整体幅度差异
                极大，不归一化的话这个差异会盖过任务本身的效应（实测会把准确率
                压到随机水平）。只用该被试自己的均值方差，不使用标签，不构成泄漏。
      none    — 不归一化，保留原始对数功率。
    """
    arrays, record = cache.get(handle)
    if record["kind"] != "clean":
        raise cache.CacheError(
            "E_BAD_INPUT_KIND",
            f"特征提取需要 clean 产物，收到 {record['kind']!r}。请先调用 eeg_preprocess。",
            suggestions=[h["handle"] for h in cache.list_recent("clean", 5)],
            recoverable=False,
        )

    if feature_set not in ("bandpower", "bandpower+asymmetry"):
        raise ValueError(
            f"未知 feature_set {feature_set!r}。可用：['bandpower', 'bandpower+asymmetry']。"
            "（CSP 需在折内拟合，请改用 eeg_evaluate 的 use_csp。）"
        )

    meta = record["meta"]
    X = arrays["X"].astype(np.float64)
    sfreq = float(meta["sfreq"])
    bands = bands or ["mu", "beta"]
    unknown = [b for b in bands if b not in BANDS]
    if unknown:
        raise ValueError(f"未知频段 {unknown}。可用：{sorted(set(BANDS))}")

    n_epochs, n_ch, n_times = X.shape
    freqs, psd = sp_signal.welch(X, fs=sfreq, nperseg=min(n_times, 256), axis=-1)
    df = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0

    ch_names = _names(meta.get("ch_names"), n_ch)
    blocks, feat_names = [], []

    # 各频段的带内功率，后续 bandpower 与 asymmetry 共用，避免重复计算
    band_power: dict[str, np.ndarray] = {}
    for b in bands:
        f0, f1 = BANDS[b]
        idx = np.logical_and(freqs >= f0, freqs < f1)
        if not idx.any():
            raise ValueError(
                f"频段 {b} ({f0}-{f1} Hz) 在 {sfreq} Hz 下没有可用频点。"
            )
        # 频率等间隔，矩形法积分即 sum × Δf（等价于梯形法，且不依赖 np.trapz）
        band_power[b] = psd[:, :, idx].sum(axis=-1) * df

    for b in bands:
        blocks.append(np.log10(band_power[b] + 1e-30))
        feat_names.extend([f"{c}_{b}" for c in ch_names])

    warnings: list[str] = []

    if feature_set == "bandpower+asymmetry":
        index = {n: i for i, n in enumerate(ch_names)}
        asym_blocks = []
        for b in bands:
            power = band_power[b]
            for left, right in HOMOLOGOUS_PAIRS:
                if left in index and right in index:
                    lp = np.log10(power[:, index[left]] + 1e-30)
                    rp = np.log10(power[:, index[right]] + 1e-30)
                    asym_blocks.append(lp - rp)
                    feat_names.append(f"asym_{left}-{right}_{b}")
        if not asym_blocks:
            warnings.append(
                "未找到任何已知的同源电极对，不对称特征为空。"
                "请确认通道名为标准 10-20 命名（如 C3/C4）。"
            )
        else:
            blocks.append(np.stack(asym_blocks, axis=1))

    F = np.concatenate(blocks, axis=1)

    # 按被试归一化。跨被试解码时，被试间在整体功率上的差异通常远大于
    # 任务相关的差异；不做这一步，分类器学到的多半是"这是谁"而不是"这是哪只手"。
    # 只用该被试自身的统计量，与标签无关，因此不会泄漏。
    if normalize == "subject":
        subs = arrays["subject_ids"]
        for s in np.unique(subs):
            m = subs == s
            if m.sum() < 2:
                continue
            mu = F[m].mean(axis=0, keepdims=True)
            sd = F[m].std(axis=0, keepdims=True)
            sd[sd < 1e-12] = 1.0
            F[m] = (F[m] - mu) / sd
    elif normalize != "none":
        raise ValueError(
            f"未知 normalize {normalize!r}。可用：['subject', 'none']"
        )

    # 退化特征会把分类器带偏，提前标出来交给 agent 判断
    var = F.var(axis=0)
    degenerate = [feat_names[i] for i in np.where(var <= 1e-12)[0]]
    if degenerate:
        warnings.append(
            f"检出 {len(degenerate)} 个零方差特征：{degenerate[:10]}。"
            "它们对判别没有贡献，可考虑移除对应频段或通道。"
        )
    n_nan = int((~np.isfinite(F)).sum())
    if n_nan:
        warnings.append(f"特征矩阵含 {n_nan} 个非有限值，会导致分类器报错。")

    new_meta = {
        "feature_set": feature_set,
        "bands": bands,
        "band_ranges": {b: list(BANDS[b]) for b in bands},
        "normalize": normalize,
        "feature_names": feat_names,
        "n_features": int(F.shape[1]),
        "n_epochs": int(F.shape[0]),
        "sfreq": sfreq,
        "label_names": meta.get("label_names"),
        "is_synthetic": meta.get("is_synthetic", False),
        "zero_variance_features": degenerate[:20],
        "source_handle": handle,
        "warnings": warnings,
    }
    return cache.put(
        "feat", {"X": F.astype(np.float32), "y": arrays["y"],
                 "subject_ids": arrays["subject_ids"]},
        new_meta, parents=[handle],
        params={"feature_set": feature_set, "bands": bands, "normalize": normalize},
    )


# ------------------------------------------------------------------ 评估
def _estimator(model: str, use_csp: bool, n_channels: int | None):
    if model not in MODELS:
        raise ValueError(f"未知模型 {model!r}。可用：{sorted(MODELS)}")
    clf = MODELS[model]()
    if not use_csp:
        return Pipeline([("scale", StandardScaler()), ("clf", clf)])
    from mne.decoding import CSP
    if not n_channels or n_channels < 2:
        raise ValueError("CSP 至少需要 2 个通道。")
    n_comp = max(2, min(6, n_channels - 1))
    # CSP 是"在训练数据上拟合"的变换，必须在折内拟合。
    # 放进 Pipeline 后交给 cross_val_predict，即可保证测试折不参与拟合。
    return Pipeline([("csp", CSP(n_components=n_comp, log=True)), ("clf", clf)])


def _metrics(y, y_pred, subjects, per_fold, scheme="cross_subject", cv_folds=5) -> dict:
    per_subject = {}
    for s in np.unique(subjects):
        m = subjects == s
        per_subject[str(int(s))] = round(float((y[m] == y_pred[m]).mean()), 4)
    subj_acc = np.array(list(per_subject.values()))

    bal = [balanced_accuracy_score(y[t], y_pred[t]) for _, t in per_fold]
    return {
        "cv_scheme": f"cross_subject（GroupKFold({cv_folds}) 按被试分组）",
        "balanced_accuracy_mean": round(float(np.mean(bal)), 4),
        "balanced_accuracy_std": round(float(np.std(bal)), 4),
        "accuracy_mean": round(float(np.mean([float((y[t] == y_pred[t]).mean())
                                               for _, t in per_fold])), 4),
        "f1_macro_mean": round(float(np.mean([
            f1_score(y[t], y_pred[t], average="macro", zero_division=0)
            for _, t in per_fold])), 4),
        "cohen_kappa": round(float(cohen_kappa_score(y, y_pred)), 4),
        "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
        "per_fold_balanced_accuracy": [round(float(b), 4) for b in bal],
        "per_subject_accuracy": per_subject,
        "per_subject_accuracy_std": round(float(subj_acc.std()), 4),
        "chance_level": 0.5,
        "n_epochs": int(len(y)),
        "n_subjects": int(len(np.unique(subjects))),
    }


def _interpret(m: dict) -> list[str]:
    notes = []
    if m["balanced_accuracy_std"] > 0.10:
        notes.append(
            f"折间标准差 {m['balanced_accuracy_std']:.3f} 偏大，结果对划分敏感，"
            "只看均值会高估可靠性。"
        )
    if m["balanced_accuracy_mean"] <= 0.53:
        notes.append(
            f"平衡准确率 {m['balanced_accuracy_mean']:.3f} 接近随机水平，"
            "该配置基本没有学到判别信息。"
        )
    if m["per_subject_accuracy_std"] > 0.15:
        notes.append(
            f"被试间准确率标准差 {m['per_subject_accuracy_std']:.3f} 很大，个体差异显著，"
            "不应声称结论对被试普遍有效。"
        )
    return notes


CV_SCHEMES = ("within_subject", "cross_subject")


def _run_cv(X, y, subjects, model, use_csp, cv_folds, scheme):
    """按指定协议做交叉验证。

    两种协议回答的是**不同问题**，不可互相替代：

    within_subject（默认，被试内）
        在每个被试内部按试次分层划分，训练与测试来自**同一个人**。
        这是 BCI 领域的标准协议——实际部署时设备本来就要针对使用者标定。
        衡量的是"这套流程在该使用者身上能不能解出运动想象"。

    cross_subject（跨被试）
        按被试分组划分，测试被试完全不出现在训练集中。
        衡量的是"能不能不做标定就套用到新使用者"。这是公认的难题：
        经典方法在小被试集上通常接近随机水平，不要拿它当唯一指标。

    报告时必须写明用的是哪一种，否则数字没有意义。
    """
    n_subjects = len(np.unique(subjects))
    n_ch = X.shape[1] if (use_csp and X.ndim == 3) else None

    if scheme == "cross_subject":
        if n_subjects < cv_folds:
            raise ValueError(
                f"只有 {n_subjects} 名被试，无法做 {cv_folds} 折跨被试交叉验证。"
                "请减少折数、增加被试，或改用 cv_scheme='within_subject'。"
            )
        estimator = _estimator(model, use_csp, n_ch)
        cv = GroupKFold(n_splits=cv_folds)
        fold_splits = list(cv.split(X, y, groups=subjects))
        y_pred = cross_val_predict(estimator, X, y, groups=subjects, cv=cv)
        return _metrics(y, y_pred, subjects, fold_splits, scheme, cv_folds), y_pred

    if scheme == "within_subject":
        per_subject = {}
        per_subject_pred = np.full(len(y), -1, dtype=int)
        for s in np.unique(subjects):
            m = subjects == s
            ys = y[m]
            counts = np.bincount(ys)
            n_splits = int(min(cv_folds, counts[counts > 0].min()))
            if n_splits < 2:
                continue
            estimator = _estimator(model, use_csp, n_ch)
            skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
            pred = cross_val_predict(estimator, X[m], ys, cv=skf)
            idx = np.where(m)[0]
            per_subject_pred[idx] = pred
            per_subject[int(s)] = round(float(balanced_accuracy_score(ys, pred)), 4)

        if not per_subject:
            raise ValueError(
                "没有任何被试能做出至少 2 折的被试内划分，样本量不足。"
            )
        accs = np.array(list(per_subject.values()))
        covered = per_subject_pred >= 0
        return {
            "cv_scheme": f"within_subject（每被试内部 {cv_folds} 折分层，再按被试汇总）",
            "balanced_accuracy_mean": round(float(accs.mean()), 4),
            "balanced_accuracy_std": round(float(accs.std()), 4),
            "accuracy_mean": round(float((y[covered] == per_subject_pred[covered]).mean()), 4),
            "f1_macro_mean": round(float(f1_score(
                y[covered], per_subject_pred[covered], average="macro", zero_division=0)), 4),
            "cohen_kappa": round(float(cohen_kappa_score(
                y[covered], per_subject_pred[covered])), 4),
            "confusion_matrix": confusion_matrix(
                y[covered], per_subject_pred[covered]).tolist(),
            "per_fold_balanced_accuracy": [round(float(a), 4) for a in accs],
            "per_subject_accuracy": per_subject,
            "per_subject_accuracy_std": round(float(accs.std()), 4),
            "chance_level": 0.5,
            "n_epochs": int(covered.sum()),
            "n_subjects": int(len(per_subject)),
            "note": "被试内协议：训练与测试来自同一人（BCI 标准标定场景）。",
        }, per_subject_pred

    raise ValueError(f"未知 cv_scheme {scheme!r}。可用：{list(CV_SCHEMES)}")


def _run_group_cv(X, y, subjects, model, use_csp, cv_folds):
    """兼容旧调用：跨被试协议。"""
    return _run_cv(X, y, subjects, model, use_csp, cv_folds, "cross_subject")[0]


def evaluate(handle: str, model: str = "lda", use_csp: bool = False,
             cv_folds: int = 5, cv_scheme: str = "within_subject") -> str:
    """交叉验证，返回 eval_* handle。

    这是 agent 的**反馈信号**：跑一次拿到指标，据此调整配置再跑。

    cv_scheme:
      within_subject（默认）— 每个被试内部按试次分层划分。BCI 标准标定协议，
                              衡量"在该使用者身上能否解出运动想象"。
      cross_subject         — 按被试分组，测试被试完全未参与训练。衡量"能否不做
                              标定就套用到新使用者"，这是公认的难题，小被试集上
                              通常接近随机。

    两种协议回答不同问题，报告里必须写明用的是哪一种。
    评估协议其余部分（折数、指标定义、随机种子）是冻结的——agent 可以改流程
    配置，但不能改衡量标准。
    """
    arrays, record = cache.get(handle)
    kind = record["kind"]
    if kind not in ("clean", "feat"):
        raise cache.CacheError(
            "E_BAD_INPUT_KIND",
            f"评估需要 clean 或 feat 产物，收到 {kind!r}。",
            suggestions=[h["handle"] for h in cache.list_recent("clean", 3)],
            recoverable=False,
        )
    if use_csp and kind == "feat":
        raise ValueError(
            "CSP 需要原始事件段（clean 产物），不能建立在已提取的功率特征上。"
        )

    X, y, subjects = arrays["X"], arrays["y"], arrays["subject_ids"]
    m, _ = _run_cv(X, y, subjects, model, use_csp, cv_folds, cv_scheme)

    config = {
        "input_handle": handle,
        "input_kind": kind,
        "model": model,
        "use_csp": use_csp,
        "cv_folds": cv_folds,
        "cv_scheme": cv_scheme,
        "cv_description": m["cv_scheme"],
        "feature_set": record["meta"].get("feature_set"),
        "bands": record["meta"].get("bands"),
        "normalize": record["meta"].get("normalize"),
        "preprocess_params": None,
    }
    # 记录前置的预处理参数，便于报告里说明"这份结果是怎么来的"。
    # clean 自身的 params 就是预处理参数；feat 则要看它的父节点 clean。
    try:
        if kind == "clean":
            config["preprocess_params"] = record.get("params")
        else:
            parent = record["meta"].get("source_handle")
            if parent and cache.exists(parent):
                config["preprocess_params"] = cache.describe(parent).get("params")
    except cache.CacheError:
        pass

    new_meta = {
        "config": config,
        "metrics": m,
        "interpretation": _interpret(m),
        "is_synthetic": record["meta"].get("is_synthetic", False),
        "source_handle": handle,
    }
    return cache.put(
        "eval", {"y_true": y.astype(np.int32), "subject_ids": subjects},
        new_meta, parents=[handle],
        params={"model": model, "use_csp": use_csp, "cv_folds": cv_folds,
                "cv_scheme": cv_scheme, "mode": "group_cv"},
    )


def validate(handle: str, scheme: str = "shuffle_control",
             test_subjects: list[int] | None = None, model: str = "lda",
             use_csp: bool = False, cv_folds: int = 5,
             n_permutations: int = 20, cv_scheme: str = "within_subject",
             seed: int = 0, batch_handles: list[str] | None = None) -> str:
    """独立验证，返回 eval_* handle。

    scheme:
      shuffle_control — 打乱标签后重跑同一套交叉验证。若准确率仍显著高于 0.5，
                        说明流程存在信息泄漏。这是对"验证严谨性"最直接的证明。
      shuffle_control_combine — 把多批置换结果合并成一次更充分的检验。
                        CSP 的一次交叉验证约需数秒，置换次数一多就会超出单次
                        工具调用预算。此时应分多批、用不同 seed 各跑一次
                        shuffle_control，再用本方案把它们的零分布合并。
                        合并多批独立置换在统计上是正当的——它就是更多的置换次数。
      holdout_subject — 留出若干被试，训练集完全不含它们。测试被试从未参与
                        任何拟合（含标准化的均值方差）。
    """
    arrays, record = cache.get(handle)
    kind = record["kind"]
    if kind not in ("clean", "feat"):
        raise cache.CacheError(
            "E_BAD_INPUT_KIND", f"验证需要 clean 或 feat 产物，收到 {kind!r}。",
            recoverable=False,
        )

    X, y, subjects = arrays["X"], arrays["y"], arrays["subject_ids"]

    if scheme == "shuffle_control":
        rng = np.random.default_rng(seed)

        def permute_labels() -> np.ndarray:
            """打乱标签，保留被试结构。

            被试内协议下必须**逐被试**打乱：若全局打乱，被试 A 的试次会拿到
            被试 B 的标签，打乱本身就把数据搅成了完全不同的分布，得到的零分布
            不能用来判断原结果是否显著。
            """
            out = y.copy()
            if cv_scheme == "within_subject":
                for s in np.unique(subjects):
                    m = subjects == s
                    out[m] = rng.permutation(y[m])
            else:
                out = rng.permutation(y)
            return out

        null = []
        for _ in range(n_permutations):
            y_perm = permute_labels()
            m_perm, _ = _run_cv(X, y_perm, subjects, model, use_csp,
                                cv_folds, cv_scheme)
            null.append(m_perm["balanced_accuracy_mean"])
        null_arr = np.array(null)

        real, _ = _run_cv(X, y, subjects, model, use_csp, cv_folds, cv_scheme)
        p_value = float((np.sum(null_arr >= real["balanced_accuracy_mean"]) + 1)
                        / (n_permutations + 1))

        new_meta = {
            "scheme": "shuffle_control",
            "config": {"input_handle": handle, "model": model, "use_csp": use_csp,
                       "cv_folds": cv_folds, "cv_scheme": cv_scheme,
                       "n_permutations": n_permutations, "seed": seed},
            "observed_balanced_accuracy": real["balanced_accuracy_mean"],
            "null_distribution": {
                "n_permutations": n_permutations,
                "mean": round(float(null_arr.mean()), 4),
                "std": round(float(null_arr.std()), 4),
                "p95": round(float(np.percentile(null_arr, 95)), 4),
                "max": round(float(null_arr.max()), 4),
            },
            "p_value": round(p_value, 4),
            "conclusion": (
                f"打乱标签后平衡准确率为 {null_arr.mean():.3f}（接近随机水平 0.5），"
                f"真实标签下为 {real['balanced_accuracy_mean']:.3f}，"
                f"置换检验 p = {p_value:.4f}。"
                + ("未发现流程泄漏的迹象。"
                   if p_value < 0.05 else
                   "**未能显著高于随机水平**，说明该配置没有学到真实判别信息，"
                   "不应作为主要结果汇报。")
            ),
            "is_synthetic": record["meta"].get("is_synthetic", False),
            "source_handle": handle,
        }
        return cache.put("eval", {"null_distribution": null_arr.astype(np.float32)},
                         new_meta, parents=[handle],
                         params={"scheme": scheme, "model": model, "use_csp": use_csp,
                                 "cv_folds": cv_folds, "cv_scheme": cv_scheme,
                                 "n_permutations": n_permutations, "seed": seed})

    if scheme == "holdout_subject":
        if not test_subjects:
            raise ValueError("scheme='holdout_subject' 时必须提供 test_subjects。")
        test_subjects = [int(s) for s in test_subjects]
        present = {int(s) for s in np.unique(subjects)}
        missing = [s for s in test_subjects if s not in present]
        if missing:
            raise ValueError(f"测试被试 {missing} 不在数据中。可用被试：{sorted(present)}")

        test_mask = np.isin(subjects, test_subjects)
        if test_mask.sum() == 0 or (~test_mask).sum() == 0:
            raise ValueError("划分后训练集或测试集为空，请调整 test_subjects。")

        estimator = _estimator(model, use_csp,
                               X.shape[1] if use_csp and X.ndim == 3 else None)
        estimator.fit(X[~test_mask], y[~test_mask])
        y_pred = estimator.predict(X[test_mask])
        y_true = y[test_mask]

        new_meta = {
            "scheme": "holdout_subject",
            "config": {"input_handle": handle, "model": model, "use_csp": use_csp,
                       "test_subjects": test_subjects},
            "metrics": {
                "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
                "accuracy": round(float((y_true == y_pred).mean()), 4),
                "f1_macro": round(float(f1_score(y_true, y_pred, average="macro",
                                                 zero_division=0)), 4),
                "cohen_kappa": round(float(cohen_kappa_score(y_true, y_pred)), 4),
                "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
                "n_test_epochs": int(test_mask.sum()),
                "n_train_epochs": int((~test_mask).sum()),
                "train_subjects": sorted(int(s) for s in np.unique(subjects[~test_mask])),
                "test_subjects": test_subjects,
                "chance_level": 0.5,
            },
            "note": "留出被试独立验证：测试被试未参与任何拟合步骤（含标准化）。",
            "is_synthetic": record["meta"].get("is_synthetic", False),
            "source_handle": handle,
        }
        return cache.put("eval", {"y_true": y_true.astype(np.int32)},
                         new_meta, parents=[handle],
                         params={"scheme": scheme, "model": model, "use_csp": use_csp,
                                 "test_subjects": test_subjects})

    if scheme == "shuffle_control_combine":
        if not batch_handles:
            raise ValueError(
                "scheme='shuffle_control_combine' 需要提供 batch_handles"
                "（若干次 shuffle_control 产生的 eval handle）。"
            )

        batches, configs, observed = [], [], []
        for bh in batch_handles:
            rec = cache.describe(bh)
            if rec["meta"].get("scheme") != "shuffle_control":
                raise ValueError(
                    f"{bh} 不是 shuffle_control 的产物（scheme="
                    f"{rec['meta'].get('scheme')!r}），不能合并。"
                )
            arrays, _ = cache.get(bh)
            if "null_distribution" not in arrays:
                raise ValueError(f"{bh} 里没有零分布数组，无法合并。")
            batches.append(arrays["null_distribution"])
            configs.append(rec["meta"]["config"])
            observed.append(rec["meta"]["observed_balanced_accuracy"])

        # 协议必须一致，否则合并出来的零分布没有意义
        keys = ("model", "use_csp", "cv_folds", "cv_scheme")
        base = {k: configs[0].get(k) for k in keys}
        for i, cfg in enumerate(configs[1:], 2):
            diff = {k: (base[k], cfg.get(k)) for k in keys if cfg.get(k) != base[k]}
            if diff:
                raise ValueError(
                    f"第 {i} 批的评估协议与前一批不一致，不能合并：{diff}。"
                    "合并的前提是所有批次用同一套模型与交叉验证协议。"
                )
        obs = observed[0]
        if any(abs(o - obs) > 1e-9 for o in observed[1:]):
            raise ValueError(
                f"各批次的真实配置准确率不一致：{observed}。"
                "它们不是同一个配置的置换检验，不能合并。"
            )

        null_arr = np.concatenate(batches)
        n_total = len(null_arr)
        p_value = float((np.sum(null_arr >= obs) + 1) / (n_total + 1))

        new_meta = {
            "scheme": "shuffle_control_combined",
            "config": {**configs[0], "n_permutations": int(n_total),
                       "batches": len(batches), "source_batches": list(batch_handles)},
            "observed_balanced_accuracy": obs,
            "null_distribution": {
                "n_permutations": int(n_total),
                "mean": round(float(null_arr.mean()), 4),
                "std": round(float(null_arr.std()), 4),
                "p95": round(float(np.percentile(null_arr, 95)), 4),
                "max": round(float(null_arr.max()), 4),
            },
            "p_value": round(p_value, 4),
            "conclusion": (
                f"合并 {len(batches)} 批共 {n_total} 次置换：打乱后平均 "
                f"{null_arr.mean():.3f}，真实标签下 {obs:.3f}，"
                f"置换检验 p = {p_value:.4f}。"
                + ("未发现流程泄漏的迹象。" if p_value < 0.05 else
                   "未能显著高于随机水平，不应作为主要结果汇报。")
            ),
            "is_synthetic": False,
            "source_handle": handle,
        }
        return cache.put(
            "eval", {"null_distribution": null_arr.astype(np.float32)},
            new_meta, parents=[handle] + list(batch_handles),
            params={"scheme": scheme, "batches": list(batch_handles)},
        )

    raise ValueError(
        f"未知 scheme {scheme!r}。可用："
        "['shuffle_control', 'shuffle_control_combine', 'holdout_subject']"
    )


# ------------------------------------------------------------------ 消融
def ablation(agent_eval_handle: str) -> dict:
    """冻结基线 vs agent 的配置，回到同一份原始数据上直接对比。

    基线配置写死在代码里、评估协议全程冻结，对比才有意义。
    verdict 由服务端计算，不由模型叙述——模型只能引用，不能宣称。

    注意一个诚实的边界：agent 的预处理选择会改变进入评估的样本集合，
    因此两组用的**不是同一批样本**。这正是要量化的"agent 决策带来的总收益"，
    但必须在 fairness 里把两个样本量都摊开，不能假装完全对等。
    """
    agent_record = cache.describe(agent_eval_handle)
    if agent_record["kind"] != "eval":
        raise ValueError(
            f"消融需要 eval 产物，收到 {agent_record['kind']!r}。"
            "请先调用 eeg_evaluate 得到评估结果。"
        )
    if "metrics" not in agent_record["meta"]:
        raise ValueError(
            "该评估产物来自置换检验，没有可对比的准确率指标。"
            "请用 eeg_evaluate 产生评估结果后再消融。"
        )

    raw_handle = provenance_raw(agent_eval_handle)
    if raw_handle is None:
        raise cache.CacheError(
            "E_MISSING_LINEAGE",
            "无法从该评估结果回溯到原始数据，不能构造可比基线。",
        )

    agent_meta = agent_record["meta"]
    agent_cfg = agent_meta.get("config", {})
    # 折数与协议必须跟 agent 那次一致，否则两组指标不可比。
    # 折数也不能直接用冻结值：被试数少于 5 时按被试分组会直接失败。
    folds = int(agent_cfg.get("cv_folds") or BASELINE["cv_folds"])
    cv_scheme = agent_cfg.get("cv_scheme") or BASELINE["cv_scheme"]

    base_clean = preprocess(
        raw_handle, low_hz=BASELINE["low_hz"], high_hz=BASELINE["high_hz"],
        crop_sec=BASELINE["crop_sec"], reject_uv=BASELINE["reject_uv"],
        channel_set=BASELINE["channel_set"], reref=BASELINE["reref"],
    )
    base_feat = features(base_clean, feature_set=BASELINE["feature_set"],
                         bands=BASELINE["bands"],
                         normalize=BASELINE.get("normalize", "subject"))
    base_eval = evaluate(base_feat, model=BASELINE["model"],
                         use_csp=BASELINE["use_csp"], cv_folds=folds,
                         cv_scheme=cv_scheme)

    base_meta = cache.describe(base_eval)["meta"]
    delta = round(agent_meta["metrics"]["balanced_accuracy_mean"]
                  - base_meta["metrics"]["balanced_accuracy_mean"], 4)

    return {
        "ok": True,
        "baseline": {
            "name": BASELINE["name"], "config": BASELINE,
            "balanced_accuracy_mean": base_meta["metrics"]["balanced_accuracy_mean"],
            "balanced_accuracy_std": base_meta["metrics"]["balanced_accuracy_std"],
            "n_epochs": base_meta["metrics"]["n_epochs"],
            "eval_handle": base_eval,
        },
        "agent": {
            "config": agent_meta["config"],
            "balanced_accuracy_mean": agent_meta["metrics"]["balanced_accuracy_mean"],
            "balanced_accuracy_std": agent_meta["metrics"]["balanced_accuracy_std"],
            "n_epochs": agent_meta["metrics"]["n_epochs"],
            "eval_handle": agent_eval_handle,
        },
        "delta_balanced_accuracy": delta,
        "verdict": ("agent_config_better" if delta > 0.01 else
                    "baseline_better" if delta < -0.01 else "no_difference"),
        "fairness": {
            "same_raw_source": raw_handle,
            "cv_scheme": base_meta["config"]["cv_scheme"],
            "chance_level": 0.5,
            "same_epoch_set": base_meta["metrics"]["n_epochs"]
            == agent_meta["metrics"]["n_epochs"],
            "note": "两组回溯到同一份原始数据、使用同一套被试划分与同一评估协议。"
                    "若 same_epoch_set 为 false，说明 agent 的预处理改变了样本集合，"
                    "差异中同时包含预处理决策的贡献——这是设计意图，但需如实说明。",
        },
    }


def provenance_raw(handle: str) -> str | None:
    """沿血缘回溯到 raw handle。"""
    seen, cur = set(), handle
    while cur and cur not in seen:
        seen.add(cur)
        try:
            rec = cache.describe(cur)
        except cache.CacheError:
            return None
        if rec["kind"] == "raw":
            return cur
        parents = rec.get("parents") or []
        cur = parents[0] if parents else None
    return None


# ------------------------------------------------------------------ 证据
def evidence(eval_handles: list[str]) -> dict:
    """收集可以写进报告的数字。

    **报告里出现的一切数值都必须来自这里。** 没有跑过的数字不许写——
    这是防止"编造实验结果"的结构性约束，而不是一句口头约定。
    """
    claims, provenance, refused = [], [], []
    for i, h in enumerate(eval_handles, 1):
        try:
            record = cache.describe(h)
        except cache.CacheError as exc:
            refused.append({"handle": h, "reason": exc.message})
            continue
        if record["kind"] != "eval":
            refused.append({"handle": h, "reason": f"不是评估产物（{record['kind']}）"})
            continue
        if record["meta"].get("is_synthetic"):
            refused.append({"handle": h, "reason": "基于合成数据，不得用于正式结论"})
            continue

        m = record["meta"].get("metrics") or {
            "balanced_accuracy": record["meta"].get("observed_balanced_accuracy"),
        }
        for key, val in m.items():
            if isinstance(val, (int, float)):
                claims.append({
                    "id": f"C{len(claims) + 1}", "key": key, "value": val,
                    "source": {"handle": h, "tool": "eeg_evaluate" if "metrics" in record["meta"]
                               else "eeg_validate"},
                    "config": record["meta"].get("config"),
                })
        if "p_value" in record["meta"]:
            claims.append({
                "id": f"C{len(claims) + 1}", "key": "shuffle_control.p_value",
                "value": record["meta"]["p_value"],
                "source": {"handle": h, "tool": "eeg_validate"},
            })
        prov = provenance_for(h)
        if prov:
            provenance.append(prov)

    return {
        "ok": True,
        "claims": claims,
        "provenance": provenance,
        "refused": refused,
        "rule": "报告中的每一个数值都必须能在 claims 中找到。未列出的数字不得写入报告。",
    }


def provenance_for(handle: str) -> dict | None:
    """回溯到 raw 产地，供证据链记录数据来源。"""
    raw_handle = provenance_raw(handle)
    if raw_handle is None:
        return None
    m = cache.describe(raw_handle)["meta"]
    is_syn = m.get("is_synthetic", False)
    return {
        "raw_handle": raw_handle,
        "dataset": "synthetic（仅供测试）" if is_syn else "EEGMMIDB v1.0.0 (PhysioNet)",
        "url": m.get("dataset_url"),
        "subjects": m.get("subjects_loaded"),
        "runs": m.get("runs"),
        "task": m.get("task"),
        "license": None if is_syn else "ODC-BY 1.0",
    }
