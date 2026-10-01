"""
check_mcp_stdio.py — 验证 MCP server 能被真正拉起并正常握手

前面只验证过"模块能导入"，那不等于"能作为一个 MCP 进程工作"。
这个脚本以 stdio 方式启动 server，走完整的 MCP 协议：
  初始化 → 列出工具 → 真正调用一个工具 → 触发一个错误分支

用途：在接进 AGH 之前，先确认问题不在我们这一侧。

运行：
  .venv/Scripts/python.exe scripts/check_mcp_stdio.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "tools" / "eeg_mcp_server.py"

# 中文 Windows 的控制台默认是 GBK，打印 ✓ / ✗ 这类字符会直接
# UnicodeEncodeError 崩掉——而崩掉的位置在工具比对**之后**，于是
# "检查通过" 与 "检查脚本自己挂了" 看起来一模一样，很难查。
# 强制切到 UTF-8，output 里的中文与符号才能正常落地。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
PYTHON = sys.executable

EXPECTED = {
    "eeg_fetch", "eeg_inspect", "eeg_preprocess", "eeg_features",
    "eeg_evaluate", "eeg_validate", "eeg_ablation", "eeg_evidence",
    "eeg_artifacts", "eeg_load_synthetic",
    # 零信号试验台（一期新增）
    "eeg_null_twin", "eeg_trial_run", "eeg_defect_rate",
}


def parse(result) -> dict:
    """工具返回的是 JSON 文本，取第一条 text 内容解析。"""
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise RuntimeError(f"工具没有返回文本内容：{result.content!r}")


async def main() -> int:
    print(f"解释器 : {PYTHON}")
    print(f"服务端 : {SERVER}")
    print("-" * 66)

    params = StdioServerParameters(command=PYTHON, args=[str(SERVER)], env=None)

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. 初始化握手
            info = await session.initialize()
            # MCP SDK v2 用 snake_case 字段名（v1 是 serverInfo / protocolVersion）
            si = getattr(info, "server_info", None) or getattr(info, "serverInfo", None)
            pv = getattr(info, "protocol_version", None) or getattr(info, "protocolVersion", "?")
            print(f"[1] 握手成功")
            print(f"    server : {si.name} {si.version}")
            print(f"    协议   : {pv}")

            # 2. 工具目录
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            print(f"[2] 工具数 {len(names)}")
            missing = EXPECTED - names
            extra = names - EXPECTED
            if missing:
                print(f"    ✗ 缺少: {sorted(missing)}")
                return 1
            if extra:
                print(f"    ! 多出: {sorted(extra)}")
            print(f"    与预期一致 ✓")

            # 3. 真正调用一次工具（合成数据，不联网、秒级）
            r = parse(await session.call_tool("eeg_load_synthetic",
                                              {"n_subjects": 4, "n_trials": 10}))
            assert r["ok"] is True, r
            raw = r["handle"]
            print(f"[3] eeg_load_synthetic → {raw}")

            r = parse(await session.call_tool("eeg_inspect", {"handle": raw}))
            print(f"[4] eeg_inspect → n_epochs={r['n_epochs']} "
                  f"n_channels={r['n_channels']} sfreq={r['sfreq']}")
            print(f"    warnings={r['warnings']}")

            # 4. 走通预处理 → 特征 → 评估
            r = parse(await session.call_tool(
                "eeg_preprocess",
                {"handle": raw, "low_hz": 8.0, "high_hz": 30.0,
                 "crop_sec": [0.5, 3.5]}))
            clean = r["handle"]
            print(f"[5] eeg_preprocess → {clean} (n_epochs={r['summary']['n_epochs_out']})")

            r = parse(await session.call_tool(
                "eeg_features",
                {"handle": clean, "feature_set": "bandpower", "bands": ["mu", "beta"]}))
            feat = r["handle"]
            print(f"[6] eeg_features → {feat} (n_features={r['summary']['n_features']})")

            r = parse(await session.call_tool(
                "eeg_evaluate", {"handle": feat, "model": "lda", "cv_folds": 4}))
            m = r["summary"]["metrics"]
            print(f"[7] eeg_evaluate → 平衡准确率 {m['balanced_accuracy_mean']} "
                  f"(随机 {m['chance_level']})")

            # 5. 错误分支：失败必须是结构化的，且带恢复建议
            r = parse(await session.call_tool("eeg_inspect",
                                              {"handle": "clean_000000000000"}))
            assert r["ok"] is False, "失效 handle 竟然没有报错"
            err = r["error"]
            print(f"[8] 错误分支 → code={err['code']} recoverable={err['recoverable']}")
            print(f"    建议列表 {len(err['suggestions'])} 条")
            assert err["recoverable"] is True
            assert err["suggestions"], "恢复建议为空，agent 将无法自愈"

            # 6. 证据工具应拒绝合成数据
            r = parse(await session.call_tool("eeg_evidence",
                                              {"eval_handles": []}))
            assert r["ok"] is True
            print(f"[9] eeg_evidence → claims={len(r['claims'])} "
                  f"refused={len(r['refused'])}")

    print("-" * 66)
    print("全部通过：MCP server 可以作为一个真实的 MCP 进程工作。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
