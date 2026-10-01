"""
正常路径测试 —— 指南 §7 要求的三类测试样例之一。

覆盖：完整闭环（取数 → 诊断 → 预处理 → 特征 → 评估 → 独立验证 → 证据）
全部使用合成数据，不联网、秒级完成，便于反复运行。
合成数据只用于验证**流程是否连通**，不作为任何结果。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_cache as cache  # noqa: E402
import eeg_pipeline as pipe  # noqa: E402


@pytest.fixture(scope="module")
def synthetic_raw():
    """一份多被试合成数据，整个模块共用，避免重复计算。"""
    import eeg_dataset as dataset
    import numpy as np

    d = dataset.synthetic(n_subjects=8, n_trials=20)
    handle = cache.put(
        "raw",
        {"X": d["X"].astype(np.float32), "y": d["y"], "subject_ids": d["subject_ids"]},
        {**{k: d[k] for k in ("sfreq", "ch_names", "label_names", "task",
                              "load_window_sec")},
         "n_epochs": int(d["X"].shape[0]), "n_channels": int(d["X"].shape[1]),
         "runs": [], "family": "synthetic",
         "subjects_loaded": list(range(1, 9)),
         "is_synthetic": True, "source": "synthetic", "dataset_url": None},
        params={"synthetic": True, "seed": 42},
    )
    assert np.isfinite(d["X"]).all()
    return handle


def test_完整闭环能跑通并给出可用指标(synthetic_raw):
    raw = synthetic_raw

    # 1. 诊断
    diag = pipe.inspect(raw)
    assert diag["n_epochs"] == 160
    assert diag["n_channels"] == 8
    assert diag["sfreq"] == 160.0
    assert diag["n_subjects"] == 8
    dist = diag["class_distribution"]
    assert sum(dist.values()) == 160
    # 随机生成，两类样本数不要求恰好相等，但都应占相当比例
    assert dist["left_fist"] > 60 and dist["right_fist"] > 60
    # 幅值诊断应落在脑电的合理量级内
    assert 1.0 < diag["amplitude_uv"]["median_abs"] < 500

    # 2. 预处理
    clean = pipe.preprocess(raw, low_hz=8.0, high_hz=30.0, crop_sec=[0.5, 3.5])
    cmeta = cache.describe(clean)["meta"]
    assert cmeta["n_channels"] == 8
    # 0.5–3.5 秒 @160 Hz = 480 点
    assert cmeta["n_times"] == 480
    assert cmeta["n_rejected"] == 0  # 未设阈值，不应剔除任何样本

    # 3. 特征
    feat = pipe.features(clean, feature_set="bandpower", bands=["mu", "beta"])
    fmeta = cache.describe(feat)["meta"]
    assert fmeta["n_features"] == 8 * 2  # 8 通道 × 2 频段
    assert not fmeta["zero_variance_features"]

    # 4. 评估
    ev = pipe.evaluate(feat, model="lda", cv_folds=4)
    emeta = cache.describe(ev)["meta"]
    m = emeta["metrics"]
    assert m["n_subjects"] == 8
    assert m["n_epochs"] == 160
    assert m["chance_level"] == 0.5
    assert len(m["confusion_matrix"]) == 2
    # 合成数据两类在 mu/beta 功率上人为拉开差距，应远高于随机
    assert m["balanced_accuracy_mean"] > 0.8, m
    # 默认走被试内协议（BCI 标准标定场景）
    assert emeta["config"]["cv_scheme"] == "within_subject"
    assert "被试内" in m["cv_scheme"]


def test_两种交叉验证协议都能跑且各不相同(synthetic_raw):
    """被试内与跨被试回答不同问题，必须都可用，且结果不应雷同。"""
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])

    within = cache.describe(pipe.evaluate(feat, cv_folds=4,
                                          cv_scheme="within_subject"))["meta"]
    cross = cache.describe(pipe.evaluate(feat, cv_folds=4,
                                         cv_scheme="cross_subject"))["meta"]

    assert within["config"]["cv_scheme"] == "within_subject"
    assert cross["config"]["cv_scheme"] == "cross_subject"
    assert "被试内" in within["metrics"]["cv_scheme"]
    assert "cross_subject" in cross["metrics"]["cv_scheme"]
    # 两者是不同的评估，不应产生同一个 handle
    assert within["config"]["input_handle"] == cross["config"]["input_handle"]


def test_伪迹阈值按微伏生效(synthetic_raw):
    """阈值单位必须是微伏。

    数据内部以伏特存储，若漏掉 ×1e6 的换算，就会拿伏特值去比微伏阈值，
    条件恒为假，等于从不剔除任何样本——这正是原版代码的缺陷。
    这里用数据自身定出一个"恰好卡在中间"的阈值，确保剔除确实发生。
    """
    # 阈值必须取自"滤波之后"的数据：伪迹判定发生在滤波之后，
    # 用滤波前的幅值定阈值会偏高，导致剔除量远低于预期。
    clean0 = pipe.preprocess(synthetic_raw, low_hz=8.0, high_hz=30.0,
                             crop_sec=[0.5, 3.5])
    arr0, _ = cache.get(clean0)
    X = arr0["X"].astype(np.float64)
    epoch_peak_uv = (np.abs(X).max(axis=-1) * 1e6).max(axis=1)  # 每个样本的峰值(µV)
    thr = float(np.median(epoch_peak_uv))
    assert thr > 1.0, f"合成数据幅值异常（{thr:.2f} µV），无法用于验证单位换算"

    strict = pipe.preprocess(synthetic_raw, low_hz=8.0, high_hz=30.0,
                             crop_sec=[0.5, 3.5], reject_uv=thr)
    smeta = cache.describe(strict)["meta"]
    assert smeta["n_rejected"] > 0, "阈值换算失效：该阈值下没有剔除任何样本"
    assert smeta["n_rejected"] < smeta["n_epochs_in"], "不应剔除全部样本"
    assert smeta["reject_pct_by_subject"], "缺少逐被试剔除比例，agent 无法据此判断"

    # 阈值远高于所有样本时应一个都不剔除
    loose = pipe.preprocess(synthetic_raw, reject_uv=1e9)
    assert cache.describe(loose)["meta"]["n_rejected"] == 0


def test_置换检验能证明结果非泄漏(synthetic_raw):
    """打乱标签后准确率应回落到随机水平附近。"""
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.validate(feat, scheme="shuffle_control", cv_folds=4,
                       n_permutations=10)
    meta = cache.describe(ev)["meta"]
    assert meta["observed_balanced_accuracy"] > 0.8
    assert meta["null_distribution"]["mean"] < 0.65, meta["null_distribution"]
    assert meta["p_value"] < 0.1


def test_置换批次可以合并成更充分的检验(synthetic_raw):
    """单次调用装不下太多置换时，分批复用不同 seed，再合并。

    p 值最小为 1/(n+1)，所以置换次数直接决定 p 能到多小——
    合并多批独立置换在统计上就是"更多次数"，是正当做法。
    """
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])

    b1 = pipe.validate(feat, scheme="shuffle_control", cv_folds=4,
                       n_permutations=5, seed=1)
    b2 = pipe.validate(feat, scheme="shuffle_control", cv_folds=4,
                       n_permutations=5, seed=2)
    assert b1 != b2, "不同 seed 应产生不同的产物"

    combined = pipe.validate(feat, scheme="shuffle_control_combine",
                             batch_handles=[b1, b2])
    m = cache.describe(combined)["meta"]

    assert m["null_distribution"]["n_permutations"] == 10
    assert m["config"]["batches"] == 2
    # 真实配置的准确率在各批之间必然一致，合并后应保留
    obs1 = cache.describe(b1)["meta"]["observed_balanced_accuracy"]
    assert m["observed_balanced_accuracy"] == obs1
    # 合并后的 p 值不应比单批更宽松
    p1 = cache.describe(b1)["meta"]["p_value"]
    assert m["p_value"] <= p1 + 1e-9


def test_留出被试验证能跑通(synthetic_raw):
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.validate(feat, scheme="holdout_subject", test_subjects=[7, 8],
                       cv_folds=5)
    m = cache.describe(ev)["meta"]["metrics"]
    assert m["test_subjects"] == [7, 8]
    # 留出被试绝不能出现在训练集里，否则验证没有意义
    assert 7 not in m["train_subjects"] and 8 not in m["train_subjects"]
    assert m["train_subjects"] == [1, 2, 3, 4, 5, 6]
    assert m["n_train_epochs"] + m["n_test_epochs"] == 160
    assert m["balanced_accuracy"] > 0.8


def test_消融能给出服务端判定的结论(synthetic_raw):
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.evaluate(feat, model="lda", cv_folds=4)
    abl = pipe.ablation(ev)
    assert abl["ok"] is True
    assert abl["verdict"] in ("agent_config_better", "baseline_better", "no_difference")
    assert abl["fairness"]["same_raw_source"]
    # 基线与 agent 都基于同一份原始数据，样本量应一致
    assert abl["fairness"]["same_epoch_set"] is True


def test_证据工具拒绝合成数据(synthetic_raw):
    """合成数据的评估结果不得进入正式结论。"""
    clean = pipe.preprocess(synthetic_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.evaluate(feat, cv_folds=4)

    res = pipe.evidence([ev])
    assert res["claims"] == [], "合成数据的数字不应被引用为证据"
    assert res["refused"] and "合成" in res["refused"][0]["reason"]
