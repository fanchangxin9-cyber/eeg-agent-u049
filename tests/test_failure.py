"""
失败路径测试 —— 指南 §7 要求的三类测试样例之三。

覆盖：失效 handle、非法参数、越界窗口、样本不足、产物类型不匹配、
      全部样本被判伪迹。

重点不只是"会报错"，而是**错误必须结构化且可恢复**：带错误码、带原因、
带可行的下一步建议。这样 agent 才能自愈，而不是整体崩掉。
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_cache as cache
import eeg_pipeline as pipe


@pytest.fixture(scope="module")
def small_raw():
    import eeg_dataset as dataset
    d = dataset.synthetic(n_subjects=6, n_trials=10)
    return cache.put(
        "raw",
        {"X": d["X"].astype(np.float32), "y": d["y"], "subject_ids": d["subject_ids"]},
        {"sfreq": d["sfreq"], "ch_names": d["ch_names"], "label_names": d["label_names"],
         "task": "synthetic", "load_window_sec": d["load_window_sec"],
         "n_epochs": int(d["X"].shape[0]), "n_channels": int(d["X"].shape[1]),
         "runs": [], "family": "synthetic", "subjects_loaded": list(range(1, 7)),
         "is_synthetic": True, "source": "synthetic", "dataset_url": None},
        params={"synthetic": True},
    )


# ---------------------------------------------------------- handle 失效
def test_handle_格式非法应被拒绝():
    with pytest.raises(cache.CacheError) as ei:
        cache.describe("not-a-handle")
    assert ei.value.code == "E_INVALID_HANDLE"
    assert ei.value.recoverable is False
    payload = ei.value.as_dict()
    assert payload["ok"] is False
    assert "error" in payload


def test_handle_不存在应给出可恢复建议():
    """关键：错误里要列出最近的同类 handle，agent 才能自愈。"""
    with pytest.raises(cache.CacheError) as ei:
        cache.describe("clean_000000000000")
    assert ei.value.code == "E_HANDLE_NOT_FOUND"
    assert ei.value.recoverable is True
    # 即便当前没有任何 clean 产物，也必须是列表而非 None
    assert isinstance(ei.value.suggestions, list)


def test_丢失_handle_后能通过列表找回():
    with pytest.raises(cache.CacheError):
        cache.describe("clean_000000000000")
    recent = cache.list_recent(None, 5)
    assert isinstance(recent, list)
    assert all("handle" in r and "kind" in r for r in recent)


# ---------------------------------------------------------- 参数非法
def test_滤波频带上下限颠倒应报错(small_raw):
    with pytest.raises(ValueError, match="滤波频带非法"):
        pipe.preprocess(small_raw, low_hz=30.0, high_hz=8.0)


def test_滤波上限超过奈奎斯特应报错(small_raw):
    # 数据为 160 Hz，奈奎斯特 80 Hz
    with pytest.raises(ValueError, match="滤波频带非法"):
        pipe.preprocess(small_raw, low_hz=8.0, high_hz=100.0)


def test_裁剪窗口越界应报错(small_raw):
    with pytest.raises(ValueError, match="之外"):
        pipe.preprocess(small_raw, crop_sec=[10.0, 20.0])


def test_未知频段应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    with pytest.raises(ValueError, match="未知频段"):
        pipe.features(clean, bands=["alpha_wave_9000"])


def test_未知模型应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="未知模型"):
        pipe.evaluate(feat, model="transformer")


def test_剔除全部通道应报错(small_raw):
    names = cache.describe(small_raw)["meta"]["ch_names"]
    with pytest.raises(ValueError, match="没有剩余通道"):
        pipe.preprocess(small_raw, drop_channels=list(names))


# ---------------------------------------------------------- 样本不足
def test_跨被试折数超过被试数应报错(small_raw):
    """跨被试协议下，折数不能超过被试数。"""
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    # 只有 6 名被试
    with pytest.raises(ValueError, match="无法做"):
        pipe.evaluate(feat, cv_folds=20, cv_scheme="cross_subject")


def test_被试内协议不受被试数限制(small_raw):
    """被试内是每个被试内部划分，所以 6 个被试也能做 20 折（自动降到该被试
    试次允许的最大折数），这与跨被试协议的行为差异是刻意的。"""
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    ev = pipe.evaluate(feat, cv_folds=20, cv_scheme="within_subject")
    m = cache.describe(ev)["meta"]["metrics"]
    assert m["balanced_accuracy_mean"] > 0.5
    assert m["n_subjects"] == 6


def test_未知交叉验证协议应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="未知 cv_scheme"):
        pipe.evaluate(feat, cv_folds=3, cv_scheme="leave_one_out")


# ---------------------------------------------------------- 类型不匹配
def test_在_raw_上直接评估应被拒绝(small_raw):
    with pytest.raises(cache.CacheError) as ei:
        pipe.evaluate(small_raw)
    assert ei.value.code == "E_BAD_INPUT_KIND"
    assert "raw" in ei.value.message


def test_在_raw_上直接提特征应被拒绝(small_raw):
    with pytest.raises(cache.CacheError) as ei:
        pipe.features(small_raw)
    assert ei.value.code == "E_BAD_INPUT_KIND"


def test_CSP_不能建立在已提取特征上(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="CSP"):
        pipe.evaluate(feat, use_csp=True)


def test_对置换检验结果做消融应被拒绝(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    ev = pipe.validate(feat, scheme="shuffle_control", cv_folds=3, n_permutations=5)
    with pytest.raises(ValueError, match="没有可对比的准确率"):
        pipe.ablation(ev)


# ---------------------------------------------------------- 数据质量
def test_阈值过严导致全部被剔应报错(small_raw):
    with pytest.raises(ValueError, match="都被判为伪迹"):
        pipe.preprocess(small_raw, crop_sec=[0.5, 3.5], reject_uv=1e-9)


def test_测试被试不存在应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="不在数据中"):
        pipe.validate(feat, scheme="holdout_subject", test_subjects=[999])


def test_留出验证缺少测试被试应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="必须提供 test_subjects"):
        pipe.validate(feat, scheme="holdout_subject")


def test_合并置换时缺少批次应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="batch_handles"):
        pipe.validate(feat, scheme="shuffle_control_combine")


def test_合并协议不一致的批次应被拒绝(small_raw):
    """合并的前提是同一套模型与协议，否则零分布不可比。"""
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    b1 = pipe.validate(feat, scheme="shuffle_control", cv_folds=3,
                       n_permutations=3, model="lda")
    b2 = pipe.validate(feat, scheme="shuffle_control", cv_folds=3,
                       n_permutations=3, model="svm")
    with pytest.raises(ValueError, match="不一致"):
        pipe.validate(feat, scheme="shuffle_control_combine",
                      batch_handles=[b1, b2])


def test_合并非置换产物应被拒绝(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    ev = pipe.evaluate(feat, cv_folds=3, cv_scheme="within_subject")
    with pytest.raises(ValueError, match="不是 shuffle_control"):
        pipe.validate(feat, scheme="shuffle_control_combine",
                      batch_handles=[ev])


def test_未知验证方案应报错(small_raw):
    clean = pipe.preprocess(small_raw, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu"])
    with pytest.raises(ValueError, match="未知 scheme"):
        pipe.validate(feat, scheme="magic")


# ---------------------------------------------------------- 证据工具
def test_证据工具对失效_handle_记入_refused_而非崩溃():
    res = pipe.evidence(["eval_000000000000", "not-a-handle"])
    assert res["ok"] is True
    assert res["claims"] == []
    assert len(res["refused"]) == 2
    assert all("reason" in r for r in res["refused"])
