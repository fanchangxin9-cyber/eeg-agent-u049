"""
边界情况测试 —— 指南 §7 要求的三类测试样例之二。

覆盖：单被试、类别不平衡、通道名非标准、极窄频带、工频陷波、
      剔除通道、零伪迹阈值。目标不是"能跑"，而是"在边界上给出正确的诊断
      或明确的拒绝"，而不是静默出错数。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_cache as cache
import eeg_pipeline as pipe


def _make_raw(x, y, subjects, ch_names, sfreq=160.0, is_synthetic=True,
              load_window=(-0.2, 4.0), params=None):
    return cache.put(
        "raw",
        {"X": np.asarray(x, dtype=np.float32), "y": np.asarray(y, dtype=int),
         "subject_ids": np.asarray(subjects, dtype=int)},
        {"sfreq": sfreq, "ch_names": list(ch_names), "label_names": ["a", "b"],
         "task": "synthetic", "load_window_sec": list(load_window),
         "n_epochs": int(len(y)), "n_channels": int(np.asarray(x).shape[1]),
         "runs": [], "family": "synthetic", "subjects_loaded": sorted(set(map(int, subjects))),
         "is_synthetic": is_synthetic, "source": "synthetic", "dataset_url": None},
        params=params or {"test": True},
    )


def test_单被试应给出样本量告警():
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=1, n_trials=20)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"])

    diag = pipe.inspect(raw)
    assert diag["n_subjects"] == 1
    assert diag["healthy"] is False
    assert any("被试" in w for w in diag["warnings"]), diag["warnings"]


def test_类别不平衡应给出告警():
    """多数类占绝对优势时，准确率会被主导，必须提示改看平衡准确率。"""
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10)
    # 人为把多数样本标成同一类
    y = d["y"].copy()
    y[: int(len(y) * 0.85)] = 0
    raw = _make_raw(d["X"], y, d["subject_ids"], d["ch_names"])

    diag = pipe.inspect(raw)
    assert "class_distribution" in diag
    assert any("不平衡" in w for w in diag["warnings"]), diag["warnings"]


def test_非标准通道名应先报错再可降级():
    """通道名不是标准 10-20 时，'motor' 选道必须明确报错，而不是静默用全部通道。

    静默降级很危险：真实数据上命名异常时会悄悄用 64 导跑完，结果无人察觉。
    所以这里刻意失败，并给出可执行的建议；agent 收到后改用 channel_set='all' 即可继续。
    """
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10, n_channels=8)
    names = [f"EEG{i:03d}" for i in range(1, 9)]
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], names)

    with pytest.raises(ValueError, match="motor"):
        pipe.preprocess(raw, crop_sec=[0.5, 3.5], channel_set="motor")

    # 按提示降级后应能继续，且不对称特征因无同源对而为空并给出告警
    clean = pipe.preprocess(raw, crop_sec=[0.5, 3.5], channel_set="all")
    feat = pipe.features(clean, feature_set="bandpower+asymmetry", bands=["mu", "beta"])
    meta = cache.describe(feat)["meta"]

    assert meta["n_features"] == 8 * 2
    assert any("同源电极对" in w for w in meta["warnings"]), meta["warnings"]


def test_运动区选道会削减通道数():
    """标准命名下 'motor' 应只保留运动皮层通道，并记录剔除了哪些。"""
    import eeg_dataset as dataset
    # 17 个运动区名全给上，再额外塞几个非运动区通道
    names = ["C3", "C4", "Cz", "FC3", "FC4", "CP3", "CP4",
             "Fz", "Pz", "Oz", "T7", "T8"]
    d = dataset.synthetic(n_subjects=6, n_trials=10, n_channels=len(names))
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], names)

    clean = pipe.preprocess(raw, crop_sec=[0.5, 3.5], channel_set="motor")
    meta = cache.describe(clean)["meta"]

    assert meta["channel_set"] == "motor"
    assert meta["n_channels"] == 7          # 只留 C3/C4/Cz/FC3/FC4/CP3/CP4
    assert set(meta["dropped_channels"]) == {"Fz", "Pz", "Oz", "T7", "T8"}

    # 默认（all）则一个都不剔
    clean_all = pipe.preprocess(raw, crop_sec=[0.5, 3.5])
    m_all = cache.describe(clean_all)["meta"]
    assert m_all["channel_set"] == "all"
    assert m_all["n_channels"] == len(names)
    assert m_all["reref"] == "none"


def test_重参考会改变信号():
    """CAR 是真实的信号变换，不能是空操作。"""
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=5, n_trials=10, n_channels=8)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"],
                    params={"reref_test": True})

    car = pipe.preprocess(raw, crop_sec=[0.5, 3.5], channel_set="all", reref="car")
    non = pipe.preprocess(raw, crop_sec=[0.5, 3.5], channel_set="all", reref="none")
    Xc, _ = cache.get(car)
    Xn, _ = cache.get(non)

    assert not np.allclose(Xc["X"], Xn["X"]), "CAR 没有改变任何数值"
    # CAR 之后各通道的跨通道均值应接近 0
    assert np.abs(Xc["X"].mean(axis=1)).max() < 1e-9
    # 原始数据不应满足这一点
    assert np.abs(Xn["X"].mean(axis=1)).max() > 0


def test_标准通道名能产生不对称特征():
    """C3/C4 等标准命名下应能构造出左右差值特征。"""
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10, n_channels=8)
    names = ["FC3", "FC4", "C3", "C4", "CP3", "CP4", "C1", "C2"]
    raw = _make_raw(d["X"][:, :8], d["y"], d["subject_ids"], names)

    clean = pipe.preprocess(raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, feature_set="bandpower+asymmetry", bands=["mu", "beta"])
    meta = cache.describe(feat)["meta"]

    asym = [n for n in meta["feature_names"] if n.startswith("asym_")]
    assert len(asym) == 4 * 2  # 4 组配对 × 2 频段
    assert any("C3-C4" in n for n in asym)


def test_选道与手动剔除通道可以叠加使用():
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10, n_channels=6)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"])

    # 6 个通道本身都是运动区通道，所以选道不剔任何东西；
    # 再手动剔掉两个，应剩 4 个
    clean = pipe.preprocess(raw, low_hz=8.0, high_hz=30.0, notch_hz=50.0,
                            crop_sec=[0.5, 3.5], drop_channels=["C3", "C4"])
    meta = cache.describe(clean)["meta"]

    assert meta["n_channels"] == 4
    assert set(meta["dropped_channels"]) == {"C3", "C4"}
    arrays, _ = cache.get(clean)
    assert arrays["X"].shape[1] == 4


def test_陷波频率超出奈奎斯特应报错():
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=5, n_trials=10)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"])

    # 160 Hz 数据，奈奎斯特为 80 Hz
    with pytest.raises(ValueError, match="陷波"):
        pipe.preprocess(raw, notch_hz=120.0)


def test_极窄频带仍然可用():
    """只取 mu 频段这一薄层，不应崩。"""
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"])

    clean = pipe.preprocess(raw, low_hz=9.0, high_hz=12.0, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    assert cache.describe(feat)["meta"]["n_features"] == d["X"].shape[1]


def test_预处理的告警会透传到下游诊断():
    """上一步的告警不能在下一步消失，否则 agent 会丢失上下文。"""
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10)
    raw = _make_raw(d["X"], d["y"], d["subject_ids"], d["ch_names"])

    # 阈值取自滤波后的数据（伪迹判定发生在滤波之后），并卡在偏低分位，
    # 确保剔除比例过半，从而触发"剔除比例过高"告警
    clean0 = pipe.preprocess(raw, low_hz=8.0, high_hz=30.0, crop_sec=[0.5, 3.5])
    arr0, _ = cache.get(clean0)
    peaks = (np.abs(arr0["X"].astype(np.float64)).max(axis=-1) * 1e6).max(axis=1)
    thr = float(np.percentile(peaks, 20))

    clean = pipe.preprocess(raw, low_hz=8.0, high_hz=30.0,
                            crop_sec=[0.5, 3.5], reject_uv=thr)
    cmeta = cache.describe(clean)["meta"]
    assert cmeta["warnings"], "剔除比例过半却没有产生告警"
    assert cmeta["dropped_ratio"] > 0.5

    diag = pipe.inspect(clean)
    assert any(w.startswith("[上一步]") for w in diag["warnings"]), diag["warnings"]
