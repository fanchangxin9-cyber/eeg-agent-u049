"""
零信号试验台的测试 —— 指南 §7 要求的三类测试之外的第四类：**盲性**。

这一组测试的重要性高于其他所有测试：如果孪生体与真品在 agent 能看到的
任何地方存在差异，整个「虚报率」实验就是无效的（agent 会识破并改变行为）。

因此 `test_孪生体与真品的诊断输出逐键相同` 是整个项目的闸门。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_cache as cache
import eeg_pipeline as pipe
import eeg_testbed as tb


@pytest.fixture()
def scratch(tmp_path, monkeypatch):
    """把 cache 根与台账都指到临时目录，绝不污染真实产物与真实台账。"""
    monkeypatch.setenv("EEG_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("EEG_TESTBED_DIR", str(tmp_path / "testbed"))
    return tmp_path


@pytest.fixture()
def real_raw(scratch):
    """一份「看起来像真品」的 raw：标签有结构、meta 不带 is_synthetic。

    刻意不用 dataset.synthetic()——那个标了 is_synthetic=True，会被
    eeg_evidence 拒绝，测不了「审计层放行孪生体」这一条。
    """
    rng = np.random.default_rng(7)
    # n_t 必须够长：下游会裁到 [0.5, 3.5]s 再做 4 阶带通，
    # 滤波需要 > 3*max(len(a),len(b)) = 27 个点。700 点 @160Hz ≈ 4.375s，
    # 落在 [-0.2, 4.0] 的加载窗口上，裁剪后剩 480 点。
    n_sub, n_trials, n_ch, n_t = 4, 20, 8, 700
    Xs, ys, subs = [], [], []
    for s in range(1, n_sub + 1):
        for _ in range(n_trials):
            label = int(rng.integers(0, 2))
            trial = rng.standard_normal((n_ch, n_t)) * 1e-5
            # 给真品一点弱标签结构，好让「有多少样本被置换了」可观察
            trial[0] += (1.0 if label else -1.0) * 2e-6
            Xs.append(trial.astype(np.float32))
            ys.append(label)
            subs.append(s)
    meta = {
        "task": "left_vs_right_imagery", "runs": [4, 8, 12], "family": "hands_imagery",
        "subjects_requested": list(range(1, n_sub + 1)),
        "subjects_loaded": list(range(1, n_sub + 1)),
        "sfreq": 160.0, "ch_names": ["C3", "C4", "Cz", "FC3", "FC4", "CP3", "CP4", "Pz"],
        "label_names": ["left_fist", "right_fist"], "load_window_sec": [-0.2, 4.0],
        "n_epochs": int(len(ys)), "n_channels": n_ch,
        "per_subject": [{"subject": s, "ok": True, "n_epochs": n_trials}
                        for s in range(1, n_sub + 1)],
        "failures": [], "is_synthetic": False,
        "source": "EEGMMIDB v1.0.0 (PhysioNet, ODC-BY-1.0)",
        "dataset_url": "https://physionet.org/content/eegmmidb/1.0.0/",
    }
    params = {"subjects": list(range(1, n_sub + 1)), "runs": [4, 8, 12],
              "task": "left_vs_right_imagery", "synthetic": False}
    return cache.put("raw", {"X": np.stack(Xs), "y": np.array(ys),
                             "subject_ids": np.array(subs)},
                     meta, parents=(), params=params)


# ---------------------------------------------------------------- 基本性质
def test_孪生体是合法的_raw_handle(real_raw, scratch):
    h = tb.make_twin(real_raw, seed=1)
    assert h.startswith("raw_")
    assert cache.HANDLE_RE.match(h), h
    assert h != real_raw


def test_孪生体的_X_与真品逐字节相同(real_raw, scratch):
    h = tb.make_twin(real_raw, seed=1)
    a, _ = cache.get(real_raw)
    b, _ = cache.get(h)
    assert np.array_equal(a["X"], b["X"])
    assert np.array_equal(a["subject_ids"], b["subject_ids"])
    assert a["X"].tobytes() == b["X"].tobytes()


def test_标签确实被置换且在置换在被试内(real_raw, scratch):
    h = tb.make_twin(real_raw, seed=1)
    a, _ = cache.get(real_raw)
    b, _ = cache.get(h)
    y, y_twin, subs = a["y"], b["y"], a["subject_ids"]

    assert not np.array_equal(y, y_twin), "标签没有被改动，孪生体无效"
    assert set(np.unique(y_twin)) <= set(np.unique(y)), "打乱不该引入新类别"

    # 关键：每个被试的类别计数必须原样不变
    for s in np.unique(subs):
        m = subs == s
        assert np.array_equal(np.bincount(y[m]), np.bincount(y_twin[m])), \
            f"被试 {s} 的类别计数被改变了——meta 会因此失真"


def test_同_seed_幂等不同_seed_不同(real_raw, scratch):
    assert tb.make_twin(real_raw, seed=1) == tb.make_twin(real_raw, seed=1)
    assert tb.make_twin(real_raw, seed=1) != tb.make_twin(real_raw, seed=2)


# ---------------------------------------------------------------- 闸门
def test_孪生体与真品的诊断输出逐键相同(real_raw, scratch):
    """★ 整个项目的闸门 ★

    agent 通过 eeg_inspect 看到的一切，孪生体与真品必须一模一样。
    任何一处差异都会让 agent 识破实验。
    """
    twin = tb.make_twin(real_raw, seed=1)
    r = pipe.inspect(real_raw)
    t = pipe.inspect(twin)

    assert set(r.keys()) == set(t.keys()), "字段集合不同，agent 可据此识破"
    for k in r:
        if k == "handle":
            continue
        assert r[k] == t[k], f"字段 {k!r} 不同：真品={r[k]!r} 孪生={t[k]!r}"


def test_孪生体_params_与真品完全一致(real_raw, scratch):
    """`eeg_inspect` 会把 params 原样交给 agent，所以这里绝不能有痕迹。"""
    twin = tb.make_twin(real_raw, seed=1)
    pr = cache.describe(real_raw)["params"]
    pt = cache.describe(twin)["params"]
    assert pr == pt
    leak = [k for k in pt if "twin" in k.lower() or "perm" in k.lower()
            or "null" in k.lower() or "seed" in k.lower()]
    assert not leak, f"params 含泄露字段：{leak}"


def test_孪生体_meta_不含任何孪生痕迹(real_raw, scratch):
    twin = tb.make_twin(real_raw, seed=1)
    meta = cache.describe(twin)["meta"]
    mr = cache.describe(real_raw)["meta"]
    assert set(meta.keys()) == set(mr.keys()), "meta 字段集合不同"
    assert meta == mr, "meta 与真品不同"
    assert not meta.get("is_synthetic"), "标成合成数据会被证据层拒绝，实验失去意义"
    blob = json.dumps(meta, ensure_ascii=False).lower()
    for word in ("twin", "null", "permut", "shuffl", "乱", "孪生"):
        assert word not in blob, f"meta 里出现泄露词 {word!r}"


def test_孪生体血缘不指向真品(real_raw, scratch):
    """parents 若指向真品，provenance 会把它暴露出来。"""
    twin = tb.make_twin(real_raw, seed=1)
    rec = cache.describe(twin)
    assert rec["parents"] == []
    assert pipe.provenance_raw(twin) == twin, "孪生体应当自成根节点"


# ---------------------------------------------------------------- 审计层放行
def test_证据工具不拒绝孪生体(real_raw, scratch):
    """★ 实验成立的前提 ★

    孪生体必须能通过审计层。它被放行，才是这个项目要说明的事——
    问题不在「数字是假的」，在「数字是真的，结论仍然是假的」。
    """
    twin = tb.make_twin(real_raw, seed=1)
    clean = pipe.preprocess(twin, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.evaluate(feat, model="lda", cv_folds=4)

    res = pipe.evidence([ev])
    assert res["refused"] == [], f"孪生体被审计层拒绝了：{res['refused']}"
    assert res["claims"], "应当产出可引用的数字"


def test_孪生体的产地被报为真实数据集(real_raw, scratch):
    twin = tb.make_twin(real_raw, seed=1)
    clean = pipe.preprocess(twin, crop_sec=[0.5, 3.5])
    feat = pipe.features(clean, bands=["mu", "beta"])
    ev = pipe.evaluate(feat, model="lda", cv_folds=4)
    prov = pipe.evidence([ev])["provenance"]
    assert prov, "应当有产地信息"
    assert "synthetic" not in prov[0]["dataset"].lower()
    assert prov[0]["dataset"].startswith("EEGMMIDB")


# ---------------------------------------------------------------- 旁路台账
def test_台账记录了孪生身份且不在产物目录里(real_raw, scratch):
    twin = tb.make_twin(real_raw, seed=3, scheme="within_subject")
    rec = tb.twin_truth(twin)
    assert rec is not None
    assert rec["source_raw"] == real_raw
    assert rec["seed"] == 3
    assert rec["scheme"] == "within_subject"
    assert tb.is_twin(twin)
    assert not tb.is_twin(real_raw)

    # 台账必须在产物目录之外——写在 cache 里等于把答案写在考卷上
    man = Path(tb._manifest_path()).resolve()
    art = Path(cache.cache_root()).resolve()
    assert art not in man.parents, f"台账落在产物目录内：{man}"


# ---------------------------------------------------------------- 目录隔离
def test_可以把孪生体隔离到独立目录(real_raw, scratch, tmp_path):
    """实验时真品不进入孪生体所在目录，agent 就没有可对照的 handle。"""
    dest = tmp_path / "isolated"
    twin = tb.make_twin(real_raw, seed=1, dest_root=dest)

    with tb.cache_root_at(dest):
        assert cache.exists(twin)
        assert not cache.exists(real_raw), "真品不应出现在隔离目录里"
        # 隔离目录里只有孪生体，agent 无从对照
        assert [h["handle"] for h in cache.list_recent("raw", 10)] == [twin]


def test_未知_scheme_报错(real_raw, scratch):
    with pytest.raises(ValueError, match="scheme"):
        tb.make_twin(real_raw, seed=1, scheme="nope")


def test_非_raw_产物不能造孪生体(real_raw, scratch):
    clean = pipe.preprocess(real_raw, crop_sec=[0.5, 3.5])
    with pytest.raises(cache.CacheError) as ei:
        tb.make_twin(clean, seed=1)
    assert ei.value.code == "E_BAD_INPUT_KIND"


# ---------------------------------------------------------------- 试验装置的身份
def test_试验台版本与分析链版本相互独立(real_raw, scratch):
    """试验台改版不能动到 handle 配方——否则 docs 里所有 eval_* 会一起失效。

    所以本模块有自己的版本号（进 meta / 缓存 / 汇总闸门），
    而 `cache.code_version()` 只哈希分析链那三个文件。
    """
    v = tb.testbed_code_version()
    assert len(v) == 12 and all(c in "0123456789abcdef" for c in v)
    assert v != cache.code_version(), "两者必须独立，否则等于把试验台塞进了 handle 配方"


def test_混合版本的批次被拒绝(real_raw, scratch):
    """同一组参数在不同实现下给出过不同数字——混在一起的平均值没有意义。

    实测背景：2026-10-01 与 2026-10-02 两批 `budget=24, hill, seed=1..8`
    参数完全相同、观测值不同（中间修过本模块）。
    """
    def t(version, p):
        return {"p_value": p, "observed": 0.56, "rank_of_chosen": 1,
                "testbed_code_version": version}

    # 两版混在一起 → 响亮失败，而不是给出一个数
    with pytest.raises(cache.CacheError) as ei:
        tb.defect_rate([t("aaaaaaaaaaaa", 0.01), t("bbbbbbbbbbbb", 0.5)])
    assert ei.value.code == "E_MIXED_TESTBED_VERSION"

    # 同版放行；老产物（无版本字段 → None）也算同一版，不能因此炸掉
    assert tb.defect_rate([t("aaaaaaaaaaaa", 0.01), t("aaaaaaaaaaaa", 0.5)])["n_significant"] == 1
    assert tb.defect_rate([t(None, 0.01), t(None, 0.5)])["n_significant"] == 1


def test_零分布缓存版本不符即重算(real_raw, scratch):
    """零分布缓存必须带版本：本模块一改，旧分布整份作废，绝不静默复用。"""
    t = tb.Testbed(real_raw, scratch / "tb")
    cfg = dict(tb.CONFIG_POOL[0])
    t.prepare(pool=[cfg])

    first = tb.null_pool(t, cfg, n_perm=3, source_raw=real_raw)
    path = tb._pool_path(t.dir, real_raw)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored[tb._POOL_VERSION_KEY] == tb.testbed_code_version()

    # 把版本改成别的、并把这一条的数值投毒 → 必须重算，不能把毒值当缓存命中
    key = json.dumps(cfg, sort_keys=True)
    stored[tb._POOL_VERSION_KEY] = "deadbeefdead"
    stored[key] = [9.9] * 3
    path.write_text(json.dumps(stored), encoding="utf-8")

    again = tb.null_pool(t, cfg, n_perm=3, source_raw=real_raw)
    assert not np.allclose(again, 9.9), "旧版本的缓存被当成命中——版本闸门失效"
    assert np.allclose(again, first), "重算结果与同版首次计算不一致（应当确定性）"


# ---------------------------------------------------------------- 单次试验（第三幕核心）
#
# 为什么补这一组（SEC-003）：`run_trial` 是第三幕 0.10 / 0.20 / 0.525 与全部
# `eval_*` handle 的**唯一来源**，而在此之前它**一条测试都没有**。
# 这里**刻意不断言具体数值**——那是数据决定的，写死只会变成"改测试让它过"。
# 钉住的是**契约**：返回结构、产物真的落盘、句柄可用、布尔字段自洽。
def test_run_trial_能跑通一次完整试验(real_raw, scratch):
    res = tb.run_trial(real_raw, seed=1, budget=2, n_perm=3)

    assert res["strategy"] == "hill"
    assert res["n_perm"] == 3
    assert 0.0 <= float(res["p_value"]) <= 1.0
    assert isinstance(res["significant"], bool)
    # significant 的定义必须是「p < alpha」，不能自相矛盾
    assert res["significant"] == (float(res["p_value"]) < 0.05)

    # 选中的配置必须来自搜索空间
    assert res["chosen_config"] in tb.CONFIG_POOL
    assert res["rank_of_chosen"] >= 1

    # 产物真的落盘了，而且能被 describe（不是只返回了个字符串）
    rec = cache.describe(res["artifact"])
    assert rec["kind"] == "eval"
    assert rec["meta"]["scheme"] == "zero_signal_trial"
    assert rec["meta"]["testbed_code_version"] == tb.testbed_code_version()

    # 孪生体存在，且不是源产物本身
    assert res["twin_handle"] != real_raw
    assert cache.exists(res["twin_handle"])


def test_run_trial_拒绝孪生体的孪生体(real_raw, scratch):
    """实测教训：把孪生体再传进去会让「被评分的数据」与「报告里写的 handle」对不上。

    必须**响亮失败**，而不是悄悄再置换一次——否则溯源就断了。
    """
    twin = tb.make_twin(real_raw, seed=1)
    with pytest.raises(ValueError, match="已经是零信号孪生体"):
        tb.run_trial(twin, seed=1, budget=1, n_perm=2)


# ---------------------------------------------------------------- handle 校验（SEC-002）
#
# 背景：`_prepared_path()` / `_pool_path()` 会把 handle 拼成**文件名**。
# handle 里出现 `/` 就会逃出试验台目录——修复前 `null_pool(t, cfg,
# source_raw="x/../../evil")` 会拼出 `nullpool_x/../../evil.json`。
# `eeg_cache` 侧有白名单校验，试验台侧此前没有。
BAD_HANDLES = [
    "../evil",             # 直接穿越
    "x/../../evil",        # 前缀 + 穿越（原始漏洞的形状）
    "..\\..\\evil",        # 反斜杠版本（Windows）
    "raw_NOTHEX00000",     # 含非十六进制字符
    "raw_0123456789",      # 只有 10 位
    "raw_0123456789abc",   # 13 位
    "raw_057280305171 ",   # 尾随空格
    "",                    # 空串
]


@pytest.mark.parametrize("bad", BAD_HANDLES)
def test_非法_handle_在拼路径前就被拒(bad, scratch):
    with pytest.raises(cache.CacheError) as ei:
        tb.Testbed(bad, scratch / "tb_bad")
    assert ei.value.code == "E_INVALID_HANDLE"
    assert ei.value.recoverable is False


def test_合法_handle_不被误拒(real_raw, scratch):
    """校验不能误伤——合法 handle 必须照常可用。"""
    t = tb.Testbed(real_raw, scratch / "tb_ok")
    assert t.source_raw == real_raw


def test_穿越_handle_不会落下任何文件(scratch, tmp_path):
    """SEC-002 的回归测试：**证明原漏洞确实被堵上**。

    修复前：`nullpool_x/../../evil.json` 会被写出去。
    修复后：在 mkdir 之前就抛错，试验台目录与逃逸点**都不该出现**。
    """
    book = tmp_path / "book"
    with pytest.raises(cache.CacheError):
        tb.Testbed("x/../../escape", book)
    assert not book.exists(), "校验应发生在 mkdir 之前"
    assert not (tmp_path / "escape.json").exists(), "路径逃出了试验台目录"


def test_null_pool_对显式传入的非法_source_raw_也拒绝(real_raw, scratch):
    """第二道校验：`Testbed` 构造时合法，不代表后来显式传进来的那个也合法。"""
    t = tb.Testbed(real_raw, scratch / "tb_np")
    cfg = dict(tb.CONFIG_POOL[0])
    t.prepare(pool=[cfg])
    with pytest.raises(cache.CacheError) as ei:
        tb.null_pool(t, cfg, n_perm=1, source_raw="../evil")
    assert ei.value.code == "E_INVALID_HANDLE"
