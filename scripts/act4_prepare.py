"""
act4_prepare.py — 为第四幕的第 N 次运行准备一个零信号孪生体

第四幕每次运行的流程是：

    写产物根指针 → 造该次的孪生体 → 起一条全新 AGH 会话跑 P1 → 取报告

本脚本负责前两步。**在 agent 会话之外的终端里跑**——agent 自己绝不能调用
`eeg_null_twin`，否则它就知道手上是孪生体了。

三条硬要求
----------
1. **每次运行一个独立的产物根**。孪生体写进 `<data>/runs/run-NN/artifacts/v1`，
   并把未加版本后缀的基路径写进洁净环境的 `artifact_root.txt`（洁净环境的
   server 会在 import eeg_cache 之前读它）。这样每次运行的 `eeg_artifacts` 里
   **只有本次的孪生体**，看不到前几次的运行，也看不到主仓库那个含第三幕
   `"scheme":"zero_signal_trial"` 记录的 index.jsonl。

2. **孪生身份台账放私有路径，且在工作区之外**。默认台账
   `%LOCALAPPDATA%\\eeg-agent\\testbed\\manifest.jsonl` 是 shell 可读的，
   所以这里用 `EEG_TESTBED_DIR` 指到 `<data>/ledger`，不让本次的孪生身份落进
   那个默认路径。`--data` 也**不应**放在工作区所在的目录树下——否则 agent
   一句 `ls ..` 就会看到 `runs/run-01..run-10` 与 `ledger/`。

3. **造完立刻自检**：`inspect` 必须与真品除 handle 外逐键相同
   （复跑 check_blinding 的核心断言），否则这一次运行无效。

用法
----
    python scripts/act4_prepare.py --run 01 --env D:/eeg-agent-work/env \\
        --data D:/eeg-agent-data --ledger docs/evidence/act4-20261003/runs.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import eeg_cache as cache  # noqa: E402
import eeg_pipeline as pipe  # noqa: E402
import eeg_testbed as tb  # noqa: E402

DEFAULT_SOURCE_RAW = "raw_057280305171"

# P1 的第四幕变体（P4x）。与 docs/runbook-three-acts.md §2 的 P1 逐字相同，
# 只有第二步开头改成「数据已经取好」并明令不要 eeg_fetch。
P4X_PROMPT = """【P1 · 第一幕】开始第一幕。

点名 eeg-analysis 技能，完成一次完整的 EEG 运动想象解码分析。
这是参赛作品的演示，请把过程做扎实。

【第一步：先规划】
用 todo 工具列出你计划执行的步骤，再开始动手。

【第二步：分析】
数据已经取好了：raw handle 是 {handle}
（EEGMMIDB 被试 1-6 的运动想象数据，已经切分好事件段）。
直接从上面这个 handle 开始，不要调用 eeg_fetch。
判断左右手能否区分。要求：
- 先做质量诊断，根据诊断结论决定预处理方案，不要套用固定参数
- 每调一次配置就汇报指标，并写清「观察 → 决定 → 理由 → 下一步」
- 两种交叉验证协议 within_subject 和 cross_subject 都跑并分别报告
- 做置换检验证明结果不是流程泄漏造成的。注意 p 值下限是 1/(n+1)，
  次数不足会把真实效应误判为不显著；单次调用装不下时按 skill 里的办法
  分批再合并（每批 10 次、不同 seed、模型/协议/折数一致）
- 与冻结基线对比，给出增益并说明来源

【第三步：自查】
分析完成后，用 shell 工具运行项目的测试套件自证工具链正常：
  .venv\\Scripts\\python.exe -m pytest tests\\ -q
并解释三类测试（正常/边界/失败）各自覆盖了什么。

【第四步：异常处置】
过程中如果任何步骤失败，判断它是否可恢复：可恢复就调整后重试，
不可恢复就记录原因并说明用什么替代证据弥补，不要跳过不提。

【第五步：出报告】
用 eeg_evidence 收集所有可引用的数字，然后写中文报告到 docs/report.md，
六个部分：数据概况、方法（含为什么这样选）、结果、验证、与基线对比、局限。
报告里每个数字都必须能在 evidence 的 claims 里找到，并标明用的是哪种协议。
局限部分如实写被试数、个体差异、多重比较等问题。
"""


def _default_source_root() -> Path:
    """主仓库的产物根基路径（**未加 /v1**，cache_root() 会自己追加）。"""
    env = os.environ.get("EEG_ARTIFACT_DIR")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "eeg-agent" / "artifacts"


def _collect(env: Path, evidence_dir: Path, label: str) -> Path | None:
    """把洁净环境里的 `docs/report.md` **移**到证据目录。

    用「移」而不是「拷」有两个好处：
    - 幂等：报告已经归档过，第二次调不会重复；
    - 顺便把工作区清干净——下一次运行开始时 `docs/report.md` 必须是**不存在**的，
      否则那次的 agent 一进工作区就看到上一次的报告，等于把答案摆在桌上。
    """
    src = env / "docs" / "report.md"
    if not src.exists():
        return None
    dst = evidence_dir / label / "report.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst


def main() -> int:
    ap = argparse.ArgumentParser(description="为第四幕第 N 次运行准备孪生体")
    ap.add_argument("--run", default=None, help="运行编号，如 01（seed 即该编号）")
    ap.add_argument("--collect", default=None, metavar="NN",
                    help="只收集 run-NN 的报告，不准备新的运行")
    ap.add_argument("--env", required=True, help="洁净环境目录（act4_make_env.py 的 --dest）")
    ap.add_argument("--data", default=None,
                    help="实验数据根，如 D:/eeg-agent-data。"
                         "**不要放在工作区所在的目录树下**：agent 一句 ls .. 就会看到"
                         "runs/run-01..run-10 与 ledger/，等于告诉它这是十次一组的实验。")
    ap.add_argument("--source-raw", default=DEFAULT_SOURCE_RAW)
    ap.add_argument("--source-root", default=None,
                    help="主仓库产物根基路径；默认取当前环境的默认根")
    ap.add_argument("--ledger", default=None, help="runs.json 路径（默认 <data>/runs.json）")
    ap.add_argument("--wipe", action="store_true", help="该 run 目录已存在时先清空")
    args = ap.parse_args()

    if not args.run and not args.collect:
        print("要么给 --run NN（准备下一次），要么给 --collect NN（只收集报告）。",
              file=sys.stderr)
        return 2

    env = Path(args.env).resolve()
    if not (env / "tools" / "eeg_mcp_server.py").exists():
        print(f"洁净环境不完整：{env}（先跑 act4_make_env.py）", file=sys.stderr)
        return 2

    # ------------------------------------------------ 只收集模式
    if args.collect:
        data = Path(args.data).resolve() if args.data else None
        ledger = Path(args.ledger).resolve() if args.ledger else (
            data / "runs.json" if data else None)
        evidence_dir = ledger.parent if ledger else env / "docs" / "evidence"
        got = _collect(env, evidence_dir, f"run-{args.collect}")
        if got is None:
            print(f"没有找到 report.md（run-{args.collect} 可能没跑，或已经收集过）",
                  file=sys.stderr)
            return 1
        print(f"✓ run-{args.collect} 的报告已归档：{got}")
        return 0

    run = args.run
    seed = int(run)          # run-01 → seed 1
    if args.data is None:
        print("--run 模式需要 --data。", file=sys.stderr)
        return 2
    data = Path(args.data).resolve()
    run_root = data / "runs" / f"run-{run}"
    source_root = Path(args.source_root).resolve() if args.source_root else _default_source_root()
    ledger = Path(args.ledger).resolve() if args.ledger else data / "runs.json"
    evidence_dir = ledger.parent

    # 0) 先把**上一次**的报告收走（顺便清空工作区，见 _collect 注释）
    if seed > 1:
        prev = f"{seed - 1:02d}"
        got = _collect(env, evidence_dir, f"run-{prev}")
        print(f"[收集] run-{prev} 的报告 → {got}" if got
              else f"[收集] 没找到 run-{prev} 的报告（没跑，或已收集过）")
        print()
    # 万一上一次没收集干净，这里再兜一次底：工作区不能留着旧报告
    stale = env / "docs" / "report.md"
    if stale.exists():
        stale.unlink()
        print("[清理] 工作区里残留的 docs/report.md 已删除")

    if run_root.exists():
        if not args.wipe:
            print(f"{run_root} 已存在。加 --wipe 重造，或换一个 --run。", file=sys.stderr)
            return 2
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)

    # 1) 孪生身份台账指到私有路径（默认台账 shell 可读，不能落进去）
    ledger_dir = data / "ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    os.environ["EEG_TESTBED_DIR"] = str(ledger_dir)

    # 2) 造孪生体：源从主仓库产物根读，孪生体写进本次运行自己的产物根
    print(f"源产物   : {args.source_raw}  (root={source_root})")
    print(f"目标根   : {run_root}")
    handle = tb.make_twin(args.source_raw, seed, source_root=source_root,
                          dest_root=run_root)

    truth = tb.twin_truth(handle)
    if truth is None:
        print("✗ 台账里没有这次孪生体的记录——造孪生体失败。", file=sys.stderr)
        return 1

    # 3) 造完立刻自检：inspect 必须与真品除 handle 外逐键相同
    with tb.cache_root_at(source_root):
        _, src_rec = cache.get(args.source_raw)
    with tb.cache_root_at(run_root):
        _, tw_rec = cache.get(handle)

    with tb.cache_root_at(source_root):
        insp_src = pipe.inspect(args.source_raw)
    with tb.cache_root_at(run_root):
        insp_tw = pipe.inspect(handle)

    diffs = {k: (insp_src[k], insp_tw[k]) for k in insp_src
             if k != "handle" and insp_src[k] != insp_tw[k]}
    if diffs or src_rec["meta"] != tw_rec["meta"] or src_rec["params"] != tw_rec["params"]:
        print(f"✗ 自检失败：孪生体与真品有差异 {list(diffs)[:5]}——本次运行无效。",
              file=sys.stderr)
        return 1

    # 4) 写产物根指针（**未加 /v1**：cache_root() 会自己追加）
    #
    # 写两份：
    #   - <env>/artifact_root.txt —— 走 AGH 里注册的洁净环境 server 时读这个
    #   - <repo>/artifact_root.txt —— 走 act4_mcp_shim.py 的「换文件」方案时读这个
    # 原版 server 根本不读 artifact_root.txt，所以多写一份是惰性的、没有副作用。
    (env / "artifact_root.txt").write_text(str(run_root), encoding="utf-8")
    (ROOT / "artifact_root.txt").write_text(str(run_root), encoding="utf-8")

    # 5) 记台账 + 落一份可直接粘贴的提示词
    prompt = P4X_PROMPT.format(handle=handle)
    (run_root / "prompt.txt").write_text(prompt, encoding="utf-8")

    entry = {
        "run": run, "seed": seed, "twin_handle": handle,
        "twin_of": args.source_raw, "run_root": str(run_root),
        "code_version": cache.code_version(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "prepared",
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    runs = json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else []
    runs = [r for r in runs if r["run"] != run] + [entry]
    runs.sort(key=lambda r: r["run"])
    ledger.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")

    print()
    print(f"✓ run-{run} 就绪   孪生体 {handle}")
    print(f"  产物根指针 : {env / 'artifact_root.txt'}  → {run_root}")
    print(f"  台账       : {ledger}")
    print()
    print("=" * 72)
    print(f"↓ 新开一条**无父会话**（工作区 = {env}），把下面整段贴进去 ↓")
    print("=" * 72)
    print(prompt)
    print("=" * 72)
    print("↑ 粘贴到上面这一行为止。跑完在终端执行下面这条收集报告：")
    print()
    print(f"  .venv\\Scripts\\python.exe scripts\\act4_prepare.py --collect {run} "
          f"--env {env}")
    print()
    print(f"  （或者直接开始下一次：--run {seed + 1:02d}，它会自动先收走这次的报告）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
