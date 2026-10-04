"""MCP 工具层的信封契约测试（SEC-003）。

为什么补这一组
--------------
`tools/eeg_mcp_server.py` 开头写着：

> stdout 是 JSON-RPC 通道。任何调试输出都必须写 stderr，否则会污染协议，
> 表现为"AGH 连不上工具"而不是报错。

以及：

> 所有工具返回统一信封：
>   成功 {"ok": true, "handle": ..., "summary": {...}}
>   失败 {"ok": false, "error": {"code","message","recoverable","suggestions"}}

这两条**都是契约**，而在此之前 13 个工具函数**一条测试都没有**——
只有 `scripts/check_mcp_stdio.py` 这个手工连通性脚本会触发一次错误分支。

本文件钉住的是**协议契约**，不是具体业务数值：
  1. 任何工具的返回都必须是**可解析的 JSON**（否则 stdio 协议就断了）
  2. 失败一律走**结构化错误信封**，带 code / recoverable / suggestions
  3. 坏格式与"格式对但不存在"要能**区分开**（前者 recoverable=False，后者 True）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_mcp_server as srv


@pytest.fixture(autouse=True)
def scratch(tmp_path, monkeypatch):
    """所有测试都在临时产物根里跑——绝不碰真实产物库。"""
    monkeypatch.setenv("EEG_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("EEG_TESTBED_DIR", str(tmp_path / "testbed"))
    return tmp_path


BAD_FORMAT = "不存在的handle"                 # 连格式都不对
MISSING = "clean_" + "0" * 12                 # 格式合法，但库里没有

# 所有以 handle 为首参的工具
HANDLE_TOOLS = ["eeg_inspect", "eeg_preprocess", "eeg_features",
                "eeg_evaluate", "eeg_validate", "eeg_ablation"]


def _load(out: str) -> dict:
    """每个工具的输出都必须是可解析 JSON——这是 stdio 协议契约。"""
    assert isinstance(out, str), f"工具应返回字符串，实际 {type(out)}"
    return json.loads(out)


# ---------------------------------------------------------------- 错误信封
def test_坏格式_handle_一律返回结构化错误():
    for name in HANDLE_TOOLS:
        j = _load(getattr(srv, name)(BAD_FORMAT))
        assert j["ok"] is False, name
        assert j["error"]["code"] == "E_INVALID_HANDLE", name
        # 格式非法是**不可恢复**的——调用方必须改参数，重试没用
        assert j["error"]["recoverable"] is False, name
        assert isinstance(j["error"]["suggestions"], list), name
        assert j["error"]["message"], name


def test_格式合法但不存在的_handle_返回_HANDLE_NOT_FOUND():
    for name in HANDLE_TOOLS:
        j = _load(getattr(srv, name)(MISSING))
        assert j["ok"] is False, name
        assert j["error"]["code"] == "E_HANDLE_NOT_FOUND", name
        # 找不到是**可恢复**的——skill 要求调用方读 suggestions 自愈
        assert j["error"]["recoverable"] is True, name


def test_两种失败能被区分开():
    """坏格式 vs 不存在，必须是两个不同的 code——否则调用方无法决定是否重试。"""
    a = _load(srv.eeg_inspect(BAD_FORMAT))["error"]
    b = _load(srv.eeg_inspect(MISSING))["error"]
    assert a["code"] != b["code"]
    assert a["recoverable"] is not b["recoverable"]


# ---------------------------------------------------------------- 协议契约
def test_所有工具的返回都是可解析_JSON():
    """哪怕参数烂到底，也不能有 traceback 漏到 stdout 上。

    这一条覆盖「显式返回字符串」的全部 13 个工具。
    """
    calls = [
        ("eeg_fetch", (), {"subjects": [], "task": "不存在的任务"}),
        ("eeg_inspect", (BAD_FORMAT,), {}),
        ("eeg_preprocess", (BAD_FORMAT,), {}),
        ("eeg_features", (BAD_FORMAT,), {}),
        ("eeg_evaluate", (BAD_FORMAT,), {}),
        ("eeg_validate", (BAD_FORMAT,), {}),
        ("eeg_ablation", (BAD_FORMAT,), {}),
        ("eeg_evidence", ([BAD_FORMAT, MISSING],), {}),
        ("eeg_artifacts", (), {"limit": 1}),
        ("eeg_load_synthetic", (), {"n_subjects": 2, "n_trials": 4}),
        ("eeg_null_twin", (BAD_FORMAT, 1), {}),
        ("eeg_trial_run", (BAD_FORMAT, 1), {}),
        ("eeg_defect_rate", ([BAD_FORMAT],), {}),
    ]
    for name, args, kw in calls:
        out = getattr(srv, name)(*args, **kw)
        j = _load(out)
        assert "ok" in j, f"{name} 的返回里没有 ok 字段"


# ---------------------------------------------------------------- 合成数据闸门
def test_合成数据的评估产物被证据工具拒绝():
    """铁律 4：合成数据的任何结果都不得进入结论。

    这条在 skill 里写得最硬，值得一条机械核验。
    """
    raw = _load(srv.eeg_load_synthetic(n_subjects=2, n_trials=10))["handle"]
    clean = _load(srv.eeg_preprocess(raw))["handle"]
    feat = _load(srv.eeg_features(clean))["handle"]
    ev = _load(srv.eeg_evaluate(feat, cv_folds=2))["handle"]

    res = _load(srv.eeg_evidence([ev]))
    assert res["refused"], "合成数据的评估产物必须被 refused"
    assert res["claims"] == [], "合成数据不应产出任何可引用 claim"


def test_评估工具拒绝错误的上游产物类型():
    """`eeg_evaluate` 要 clean/feat，给它 raw 必须结构化拒绝——而不是崩。"""
    raw = _load(srv.eeg_load_synthetic(n_subjects=2, n_trials=4))["handle"]
    j = _load(srv.eeg_evaluate(raw, cv_folds=2))
    assert j["ok"] is False
    assert j["error"]["code"] == "E_BAD_INPUT_KIND"
    assert not j["error"]["recoverable"]


# ---------------------------------------------------------------- 成功返回的**实际**形状
#
# 模块文档（`eeg_mcp_server.py` 顶部，SEC-011）此前写「所有工具返回统一信封」，
# 与实测不符。现在文档里改成一张**实测表**，下面这张表与它逐格对应。
#
# 为什么值得钉住：这是 agent 与工具之间的接口契约，而本项目的研究对象**就是**
# agent 的行为。形状一旦漂移，agent 的输入就变了，两批第四幕证据随之失去可比性。
#
# 表里没有 `eeg_fetch`（要联网下载）与 `eeg_trial_run`（预算大、耗时分钟级）——
# 两者形状与 `eeg_preprocess` / `eeg_load_synthetic` 同类，但**未被本文件覆盖**，如实注明。
SUCCESS_SHAPE: dict[str, tuple[set[str], set[str]]] = {
    # 工具名: (必须存在的顶层键, 必须不存在的顶层键)
    "eeg_load_synthetic": ({"ok", "handle", "summary"}, set()),
    "eeg_preprocess":     ({"ok", "handle", "summary"}, set()),
    "eeg_features":       ({"ok", "handle", "summary"}, set()),
    "eeg_evaluate":       ({"ok", "handle", "summary"}, set()),
    "eeg_validate":       ({"ok", "handle", "summary"}, set()),
    "eeg_null_twin":      ({"ok", "handle", "summary"}, set()),
    "eeg_artifacts":      ({"ok", "summary"}, {"handle"}),          # 不产出新产物 → 无 handle
    "eeg_defect_rate":    ({"ok", "summary"}, {"handle"}),          # 同上
    "eeg_ablation":       ({"ok", "verdict"}, {"handle", "summary"}),
    "eeg_evidence":       ({"ok", "claims"}, {"handle", "summary"}),
    "eeg_inspect":        ({"handle", "healthy"}, {"ok", "summary"}),  # 连 ok 都没有
}


def test_成功返回的形状与本文档一致(scratch):
    """逐格核对 `eeg_mcp_server.py` 顶部那张表。

    谁改了任何一个工具的返回形状，这条会失败——**逼他同步改文档**，
    而不是让文档悄悄过期（SEC-011 就是这么发生的）。
    """
    raw = _load(srv.eeg_load_synthetic(n_subjects=2, n_trials=6))["handle"]
    clean = _load(srv.eeg_preprocess(raw))["handle"]
    feat = _load(srv.eeg_features(clean))["handle"]
    ev = _load(srv.eeg_evaluate(feat, cv_folds=2))["handle"]

    actual = {
        "eeg_load_synthetic": _load(srv.eeg_load_synthetic(n_subjects=2, n_trials=4)),
        "eeg_preprocess":     _load(srv.eeg_preprocess(raw)),
        "eeg_features":       _load(srv.eeg_features(clean)),
        "eeg_evaluate":       _load(srv.eeg_evaluate(feat, cv_folds=2)),
        "eeg_validate":       _load(srv.eeg_validate(feat, n_permutations=2, cv_folds=2)),
        "eeg_null_twin":      _load(srv.eeg_null_twin(raw, 1)),
        "eeg_artifacts":      _load(srv.eeg_artifacts(limit=3)),
        "eeg_defect_rate":    _load(srv.eeg_defect_rate([ev])),
        "eeg_ablation":       _load(srv.eeg_ablation(ev)),
        "eeg_evidence":       _load(srv.eeg_evidence([])),
        "eeg_inspect":        _load(srv.eeg_inspect(raw)),
    }

    assert set(actual) == set(SUCCESS_SHAPE), "表与用例集合对不上，别漏测"
    for name, j in actual.items():
        must, must_not = SUCCESS_SHAPE[name]
        missing = must - set(j)
        present = must_not & set(j)
        assert not missing, f"{name} 缺少顶层键 {sorted(missing)}（形状变了）"
        assert not present, f"{name} 多出顶层键 {sorted(present)}（形状变了）"


def test_坏参数返回_E_BAD_ARGUMENT_而不是崩溃():
    """白名单外的参数值必须被 `_guard` 翻成结构化错误。"""
    raw = _load(srv.eeg_load_synthetic(n_subjects=2, n_trials=4))["handle"]
    j = _load(srv.eeg_preprocess(raw, reref="这个参考不存在"))
    assert j["ok"] is False
    assert j["error"]["code"] == "E_BAD_ARGUMENT"
    assert j["error"]["recoverable"] is False


# ---------------------------------------------------------------- E_INTERNAL 的脱敏（SEC-010）
def test_未预期异常只回类型不回原文(scratch, capsys):
    """`str(exc)` 常带本机绝对路径——它会进 agent 上下文、也可能随会话导出进仓库。

    所以信封里**只给异常类型**，完整信息走 stderr。
    """
    def boom() -> str:
        raise KeyError(r"D:\暂存\source\tools\secret_path.py")

    out = _load(srv._guard(boom))

    assert out["ok"] is False
    assert out["error"]["code"] == "E_INTERNAL"
    assert out["error"]["message"] == "KeyError"
    # 路径绝不能出现在回给调用方的任何字段里
    blob = json.dumps(out, ensure_ascii=False)
    assert "暂存" not in blob and "secret_path" not in blob

    # 但完整信息必须能在 stderr 上找到——否则运维就没法排查了
    err = capsys.readouterr().err
    assert "secret_path" in err, "完整信息应当写到 stderr"
