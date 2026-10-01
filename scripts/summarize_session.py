"""
summarize_session.py — 把 AGH 会话导出整理成人类可读的调用轨迹

指南 §7 要求提交「可供人工核查的 AGH 执行记录」。JSONL 是原始证据，
但不便于阅读；本脚本从它生成一份 Markdown 轨迹，供评委快速核查。

用法：
  .venv/Scripts/python.exe scripts/summarize_session.py docs/evidence/agh-session.jsonl \
      -o docs/evidence/agh-session-trace.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 只保留这些参数，避免把大段数据铺进文档
KEEP = ("handle", "model", "use_csp", "cv_folds", "cv_scheme", "feature_set",
        "bands", "normalize", "channel_set", "reref", "low_hz", "high_hz",
        "reject_uv", "crop_sec", "scheme", "test_subjects", "n_permutations",
        "seed", "batch_handles", "subjects", "task", "eval_handles",
        "agent_eval_handle")


def _text_of(data) -> str:
    c = data.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(b.get("text", "") for b in c
                       if isinstance(b, dict) and b.get("type") == "text")
    return data.get("text", "") or ""


def _fmt_args(args) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args
    if not isinstance(args, dict):
        return str(args)
    picked = {k: v for k, v in args.items() if k in KEEP}
    return json.dumps(picked, ensure_ascii=False) if picked else "(无参数)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    args = ap.parse_args()

    recs = [json.loads(l) for l in args.path.read_text(encoding="utf-8").splitlines() if l.strip()]

    out: list[str] = []
    out.append("# AGH 执行轨迹\n")
    out.append(f"> 来源：`{args.path.as_posix()}`（{len(recs)} 个事件）\n")
    out.append("本文档由会话账本导出生成，逐条对应一次真实工具调用，可回溯核查。\n")

    n_tool = 0
    for r in recs:
        t = r.get("type")
        d = r.get("data", {}) or {}

        if t in ("user/message", "user/output"):
            txt = _text_of(d).strip()
            if txt and not txt.startswith("[runtime context]"):
                out.append(f"\n## 用户输入\n\n```\n{txt}\n```\n")

        elif t == "tool/call":
            n_tool += 1
            name = str(d.get("name", "?"))
            short = name.replace("mcp_eeg_agent_bce84b6f_", "")
            out.append(f"\n### [{n_tool}] `{short}`\n\n```json\n{_fmt_args(d.get('arguments') or d.get('args'))}\n```\n")

        elif t == "tool/result":
            txt = _text_of(d).strip()
            try:
                obj = json.loads(txt)
                if isinstance(obj, dict) and "error" in obj:
                    err = obj["error"]
                    txt = (f"[错误] {err.get('code')}: {err.get('message')}\n"
                           f"        recoverable={err.get('recoverable')} "
                           f"suggestions={len(err.get('suggestions') or [])} 条")
                else:
                    txt = json.dumps(obj, ensure_ascii=False)[:400]
            except (json.JSONDecodeError, TypeError):
                txt = txt[:400]
            out.append(f"**返回**：\n\n```\n{txt}\n```\n")

    text = "".join(out)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"已生成轨迹：{args.out}（{n_tool} 次工具调用）")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
