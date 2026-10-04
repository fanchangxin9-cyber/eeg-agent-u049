"""第四幕**环境面**闸门的两条新逻辑（2026-10-04 加）的测试。

为什么值得单测：闸门是「验证别人」的工具，它自己错了没人会发现——
除非有人拿一份**已知有问题**的输入去跑它。这一组用的就是 10-03 那批
真实出错的数据形状。

覆盖两条：

1. **会话键中性**：AGH 会把 `sessionKey` 原样注入 agent 的 `[runtime context]`，
   而它**不在任何文件里**（harness 运行时注入），文件核对永远看不见。
   10-03 那批用的是 `act4-run-<NN>-try<k>`，等于每次都告诉 agent「你是 act4 的第 N 次」。
2. **会话键唯一**：不给 key 时 daemon 返回**工作区级**同一条会话，各 run 会互相
   继承历史、不再独立——这正是 10-03 那批作废重跑的原因。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_blinding_act4 import SESSION_KEY_BLOCKLIST, _session_keys  # noqa: E402


def _write_log(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "runner.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                 encoding="utf-8")
    return p


def _dirty(keys: list[str]) -> list[str]:
    """复算 main() 里那条判据，返回含身份词的键。"""
    return [k for k in keys if any(t in k.lower() for t in SESSION_KEY_BLOCKLIST)]


def test_旧批次的会话键会被抓出(tmp_path):
    """10-03 那批的真实形状：键名里带 act4 与序号。"""
    log = _write_log(tmp_path, [
        {"run": "06", "session_id": "act4-run-06-try1"},
        {"run": "07", "session_id": "act4-run-07-try1"},
    ])
    keys = [k for _, k in _session_keys(log)]
    assert keys == ["act4-run-06-try1", "act4-run-07-try1"]
    assert _dirty(keys), "含 act4 的会话键必须被判为不中性"


def test_中性随机键通过(tmp_path):
    """第二批的形状：不透明随机 id，唯一、零信息。"""
    log = _write_log(tmp_path, [
        {"run": "01", "session_id": "s-56357bbb-1608-483c-85d6-fe2f7ac62cf5"},
        {"run": "02", "session_id": "s-d1e3fdc3-34ef-45f6-9661-b6ba2062ef9f"},
    ])
    keys = [k for _, k in _session_keys(log)]
    assert not _dirty(keys)
    assert len(set(keys)) == len(keys), "两条会话键应当不同"


def test_工作区级共用键被判为重复(tmp_path):
    """run-01 那次的真实形状：多条 run 落在同一条工作区级会话上。"""
    log = _write_log(tmp_path, [
        {"run": "01", "session_id": "agnes:local:local-dev:cli:workspace:371d6599c45339a7"},
        {"run": "02", "session_id": "agnes:local:local-dev:cli:workspace:371d6599c45339a7"},
    ])
    keys = [k for _, k in _session_keys(log)]
    assert len(set(keys)) < len(keys), "重复的会话键必须被判为不唯一"


def test_坏行被跳过而不是崩掉(tmp_path):
    """runner.jsonl 是追加写的，中间可能有半截行——不能因此整条闸门崩掉。"""
    p = tmp_path / "runner.jsonl"
    p.write_text('{"run": "01", "session_id": "s-aaa"}\n'
                 '{"run": "02", "session_id":\n'          # 半截行
                 '{"run": "03"}\n'                        # 没有 session_id
                 '{"run": "04", "session_id": "s-bbb"}\n', encoding="utf-8")
    keys = [k for _, k in _session_keys(p)]
    assert keys == ["s-aaa", "s-bbb"]
