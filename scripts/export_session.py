"""
export_session.py — 从 AGH 的会话账本直接导出执行记录

为什么需要它：
`agnes export <SESSION_ID>` 在会话较大（约 1500+ 事件）时会以
`DAEMON_CONNECTION_CLOSED` 失败——daemon 在传输过程中关掉了连接。
小会话可以正常导出，说明是规模问题，不是数据损坏。

本脚本绕开 CLI，直接只读打开 `~/.agh/data/sessions.db` 的 `events` 表，
按 AGH 原生格式（每行一个协议信封）重建 JSONL。

用法：
  .venv/Scripts/python.exe scripts/export_session.py <SESSION_ID> -o docs/evidence/agh-session.jsonl
  .venv/Scripts/python.exe scripts/export_session.py --list
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# 与 agnes export --format agnes 一致的信封字段顺序。
# 注意最后两项：SQLite 里存的是下划线命名，CLI 导出时转成驼峰，
# 这里必须转回来，否则重建的文件与原生导出逐字节不一致。
ENVELOPE = (
    ("seq", "seq"), ("ts", "ts"), ("id", "id"), ("type", "type"),
    ("lane", "lane"), ("v", "v"), ("actor", "actor"), ("origin", "origin"),
    ("trust", "trust"), ("register", "register"), ("ignorable", "ignorable"),
    ("surface_op", "surfaceOp"), ("source_event_seqs", "sourceEventSeqs"),
    ("data", "data"),
)


HOME = os.path.expanduser("~")


def db_path() -> Path:
    home = os.environ.get("AGH_HOME") or os.path.join(HOME, ".agh")
    return Path(home) / "data" / "sessions.db"


# ---------------------------------------------------------------- 隐私脱敏
# 与 AGH 自身的默认规则保持一致（packages/base/extensions/privacy/src/redact.ts）。
# 导出记录会交给评委，路径与 PII 不应原样外流。
_SIMPLE_SECRETS = (
    ("aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("github", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")),
    ("sk", re.compile(r"sk-[A-Za-z0-9_-]{16,}")),
)
_PII = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    ("id", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
)
# Agnes 账号标识：事件信封的 `route`/`accountId` 里带 `account-acct-<uuid>`
# 或裸 `acct-<uuid>`。它是账号级标识，不应随公开仓库外流。
# 先替换带前缀的整串，再替换裸串——前者替换后不再含 uuid，不会二次命中。
_ACCOUNT = (
    re.compile(r"account-acct-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    re.compile(r"(?<![0-9A-Za-z-])acct-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
)
_SECRET_JSON = re.compile(r'("secret://[^"\s]+"\s*:\s*")([^"]+)(")')
_SECRET_ASSIGNED = re.compile(r"(secret://[^\s\"'=:]+=)(\"[^\"]+\"|'[^']+'|[^\s,;}]+)")


def _path_pattern(value: str) -> re.Pattern | None:
    """匹配某个绝对路径。

    **必须同时匹配单反斜杠和双反斜杠两种形式**：工具返回值里嵌的是
    JSON 文本，路径在其中是转义过的（`C:\\\\Users\\\\...`），
    而普通字符串里是未转义的（`C:\\Users\\...`）。
    AGH 的原生脱敏也是这么处理的（`(?:\\\\\\\\|\\\\|/)`）。
    """
    value = value.rstrip("\\/")
    if not value or value == "/":
        return None
    windows = bool(re.match(r"^[A-Za-z]:[\\/]", value)) or value.startswith("\\\\")
    if not windows:
        return re.compile(re.escape(value) + r"(?=$|/)")
    parts = re.split(r"[\\/]", value)
    sep = r"(?:\\\\|\\|/)"          # 双反斜杠 | 单反斜杠 | 正斜杠
    body = sep.join(re.escape(p) for p in parts)
    return re.compile(body + r'(?=$|[\\/\s"\',;:)])', re.IGNORECASE)


def _redact_string(s: str, home: str | None) -> str:
    """按 AGH 默认规则对**单个字符串值**脱敏：密钥 → 路径 → PII。

    在解析后的值上做，而不是在序列化后的 JSON 文本上做——
    后者要处理反斜杠转义，既易错又难核对。AGH 本身也是对值做的。
    """
    out = _SECRET_JSON.sub(lambda m: f"{m.group(1)}[REDACTED:secret]{m.group(3)}", s)
    out = _SECRET_ASSIGNED.sub(lambda m: f"{m.group(1)}[REDACTED:secret]", out)
    for kind, pat in _SIMPLE_SECRETS:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    for pat in _ACCOUNT:
        out = pat.sub("[REDACTED:account]", out)

    if home:
        pat = _path_pattern(home)
        if pat:
            out = pat.sub("~", out)
        user = os.path.basename(home.rstrip("\\/"))
        if user:
            out = re.sub(rf"/(?:Users|home)/{re.escape(user)}(?=$|/)", "~", out)
            # 裸用户名。会话账本里它以 actor id（形如 `"id": "<用户名>"`）、
            # PowerShell 的 `机器名\用户名` 等形式出现，且都不是路径，
            # AGH 自带的路径规则盖不到。词边界匹配，避免误伤含该词的普通文本。
            out = re.sub(
                rf"(?<![A-Za-z0-9_-]){re.escape(user)}(?![A-Za-z0-9_-])", "<user>", out
            )

    # 额外需要脱敏的字符串（逗号分隔）。
    # 走环境变量而不是写进代码：这样脚本本身不携带任何敏感词，
    # 可以安全地公开在仓库里。
    for term in filter(None, (t.strip() for t in
                              os.environ.get("AGH_EXPORT_REDACT_EXTRA", "").split(","))):
        out = out.replace(term, "<redacted>")

    for kind, pat in _PII:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    return out


def redact_value(v, home: str | None):
    """递归脱敏：字符串直接处理，容器逐项下探。"""
    if isinstance(v, str):
        return _redact_string(v, home)
    if isinstance(v, list):
        return [redact_value(x, home) for x in v]
    if isinstance(v, dict):
        return {k: redact_value(x, home) for k, x in v.items()}
    return v


def _load(raw):
    """SQLite 里部分是 JSON 文本、部分是 BLOB，统一解成 Python 对象。"""
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        s = raw.strip()
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return s
        return s
    return raw


def list_sessions(con) -> None:
    cur = con.cursor()
    cur.execute(
        "SELECT session_key, COUNT(*), MIN(ts), MAX(ts) FROM events "
        "GROUP BY session_key ORDER BY MAX(ts) DESC"
    )
    print(f"{'会话 ID':<66} {'事件':>6}  {'起':<22} 止")
    for key, n, t0, t1 in cur.fetchall():
        print(f"{key:<66} {n:>6}  {t0:<22} {t1}")


def export(con, session_key: str, out: Path | None, raw: bool = False) -> int:
    cur = con.cursor()
    cur.execute("PRAGMA table_info(events)")
    cols = [r[1] for r in cur.fetchall()]
    cur.execute(
        f"SELECT {', '.join(cols)} FROM events WHERE session_key = ? ORDER BY seq",
        (session_key,),
    )
    rows = cur.fetchall()
    if not rows:
        print(f"没有找到会话 {session_key}。用 --list 查看可用会话。", file=sys.stderr)
        return 1

    lines = []
    for row in rows:
        rec = {c: _load(v) for c, v in zip(cols, row, strict=True)}
        env = {}
        for col, key in ENVELOPE:
            val = rec.get(col)
            if val is not None:
                env[key] = val
        # 默认脱敏，与 agnes export 的口径一致；--raw 可关闭
        if not raw:
            env = redact_value(env, HOME)
        lines.append(json.dumps(env, ensure_ascii=False, separators=(", ", ": ")))

    text = "\n".join(lines) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"已导出 {len(lines)} 个事件 → {out}")
    else:
        sys.stdout.write(text)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id", nargs="?")
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    path = db_path()
    if not path.exists():
        print(f"找不到会话库：{path}", file=sys.stderr)
        return 1

    # 只读打开，绝不写 AGH 的账本
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        if args.list or not args.session_id:
            list_sessions(con)
            return 0
        return export(con, args.session_id, args.out)
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
