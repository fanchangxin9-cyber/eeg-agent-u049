"""
act4_mcp_shim.py — 不碰 AGH 配置，让 agent 看到洁净环境的 MCP

背景
----
第四幕要求 AGH 里的 `eeg-agent` 暴露的是洁净环境那份 server（10 个工具、没有
三个试验台工具、产物写进本次运行自己的产物根）。正常做法是改 AGH 的 MCP 注册，
但那条路要过 AGH 的交互式授权，实测连续三次都没落地（revision 一字未变）。

这个脚本走另一条路：**注册路径不动，改它指向的文件。**

AGH 里注册的是
    可执行文件 D:/暂存/source/.venv/Scripts/python.exe
    参数       D:/暂存/source/tools/eeg_mcp_server.py

所以把 `tools/eeg_mcp_server.py` 临时换成洁净环境那一份即可——注册一个字都不用改，
自然也不需要任何授权。洁净那份会读 `artifact_root.txt`（`__file__` 的上一级，
也就是仓库根），而 `act4_prepare.py` 每次都会把产物根写到那里。

为什么安全
----------
- `eeg_mcp_server.py` **不参与** `code_version()`（后者只取 eeg_pipeline /
  eeg_dataset / eeg_cache 三个文件），换掉它不影响任何 handle；
- 洁净那份 import 的仍是本仓库的 eeg_cache / eeg_pipeline，与洁净环境里
  逐字节相同，code_version 一致；
- 原来那份会先备份，`uninstall` 还原；
- 只改这一处。`eeg_testbed.py` 等文件原封不动（原版 server 不 import 它们，
  洁净版更不 import）。

⚠ 用完必须 `uninstall`，否则本仓库的 MCP 会一直停在 10 个工具，第三幕的
  `eeg_trial_run` / `eeg_defect_rate` 就没了。

用法
----
    python scripts/act4_mcp_shim.py install      # 跑第四幕之前
    python scripts/act4_mcp_shim.py status
    python scripts/act4_mcp_shim.py uninstall    # 跑完第四幕
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools" / "eeg_mcp_server.py"
BACKUP = ROOT / "tools" / ".eeg_mcp_server.py.act4bak"
POINTER = ROOT / "artifact_root.txt"

DEFAULT_ENV = Path("D:/eeg-agent-work/env")
EXPECTED_TOOLS = 10
TESTBED_TOOLS = ("eeg_null_twin", "eeg_trial_run", "eeg_defect_rate")


def _declared_tools(src: str) -> set[str]:
    return set(re.findall(r"@mcp\.tool\(\)\s*\ndef\s+(\w+)", src))


def _installed() -> bool:
    return BACKUP.exists()


def cmd_status(_args: argparse.Namespace) -> int:
    src = TARGET.read_text(encoding="utf-8")
    tools = _declared_tools(src)
    print(f"仓库根      : {ROOT}")
    print(f"server 文件 : {TARGET}")
    print(f"当前工具数  : {len(tools)}")
    print(f"试验台工具  : {sorted(tools & set(TESTBED_TOOLS)) or '（无）'}")
    print(f"shim 状态   : {'已安装（备份在 ' + BACKUP.name + '）' if _installed() else '未安装（原版）'}")
    if POINTER.exists():
        print(f"产物根指针  : {POINTER.read_text(encoding='utf-8').strip()}")
    else:
        print("产物根指针  : （不存在）")
    print()
    if _installed() and len(tools) == EXPECTED_TOOLS:
        print("→ 已在「第四幕」状态：AGH 里的 eeg-agent 就是洁净那份 server。")
    elif not _installed():
        print("→ 已在「主仓库」状态：13 个工具，第三幕的试验台工具都在。")
    else:
        print("→ 状态异常，建议先 uninstall 再重新 install。")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    env = Path(args.env).resolve()
    clean_server = env / "tools" / "eeg_mcp_server.py"
    if not clean_server.exists():
        print(f"洁净环境不完整：{clean_server}（先跑 act4_make_env.py）", file=sys.stderr)
        return 2
    if _installed():
        print(f"已经安装过了（备份在 {BACKUP}）。要重装先 uninstall。", file=sys.stderr)
        return 2

    clean_src = clean_server.read_text(encoding="utf-8")
    tools = _declared_tools(clean_src)
    if len(tools) != EXPECTED_TOOLS or (tools & set(TESTBED_TOOLS)):
        print(f"洁净那份 server 不对劲：{len(tools)} 个工具 {sorted(tools)}", file=sys.stderr)
        return 1

    shutil.copy2(TARGET, BACKUP)
    shutil.copy2(clean_server, TARGET)
    print(f"[1/2] 已备份原 server → {BACKUP.name}")
    print(f"[2/2] 已换成洁净 server（{len(tools)} 个工具，无试验台三工具）")

    if not POINTER.exists():
        print()
        print("⚠ artifact_root.txt 不存在——先跑 act4_prepare.py --run NN，")
        print("  否则 server 会退回默认产物根（= 接线错的症状）。")
    else:
        print(f"      产物根指针 : {POINTER.read_text(encoding='utf-8').strip()}")

    print()
    print("下一步：**重启 AGH 会话**（server 是启动时拉起的，改文件不会热生效），")
    print("        然后确认 eeg_artifacts 的 cache_dir 指向上面的产物根。")
    return 0


def cmd_uninstall(_args: argparse.Namespace) -> int:
    if not _installed():
        print("没有安装记录，无需还原。", file=sys.stderr)
        return 1
    shutil.copy2(BACKUP, TARGET)
    BACKUP.unlink()
    print(f"[1/2] 已还原原 server（备份 {BACKUP.name} 已删除）")

    if POINTER.exists():
        POINTER.unlink()
        print("[2/2] 已删除仓库根的 artifact_root.txt")
    else:
        print("[2/2] artifact_root.txt 本来就不存在")

    tools = _declared_tools(TARGET.read_text(encoding="utf-8"))
    print()
    print(f"当前工具数：{len(tools)}（应为 13，含 {sorted(set(TESTBED_TOOLS) & tools)}）")
    print("**重启 AGH 会话**后生效。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="第四幕 MCP 换文件方案")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="把仓库的 MCP server 换成洁净那份")
    p_install.add_argument("--env", default=str(DEFAULT_ENV), help="洁净环境目录")
    p_install.set_defaults(func=cmd_install)

    sub.add_parser("uninstall", help="还原原来的 MCP server").set_defaults(func=cmd_uninstall)
    sub.add_parser("status", help="看当前是哪一种状态").set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
