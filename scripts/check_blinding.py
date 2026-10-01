"""
check_blinding.py — 盲性验收

在**真实数据**上验证：零信号孪生体与真品在 agent 能看到的每一个地方
都完全一致，并且能通过审计层。

这是整个实验的闸门。**不通过就不能往下做**——如果 agent 能分辨孪生体，
「虚报率」测的就不是「agent 面对零信号时的行为」，而是「agent 识别出
自己在做测试时的行为」，数字全部作废。

用法：
    .venv/Scripts/python.exe scripts/check_blinding.py
    .venv/Scripts/python.exe scripts/check_blinding.py --raw raw_057280305171

退出码 0 = 闸门通过；1 = 有泄漏，必须修。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import eeg_cache as cache  # noqa: E402
import eeg_pipeline as pipe  # noqa: E402
import eeg_testbed as tb  # noqa: E402

DEFAULT_RAW = "raw_057280305171"

# agent 能看到的每一个字符串里，都不许出现这些词
LEAK_WORDS = ("twin", "null", "permut", "shuffl", "孪生", "零信号", "打乱", "置换")


class Report:
    def __init__(self) -> None:
        self.checks: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, name: str, detail: str = "") -> bool:
        self.checks.append((bool(ok), name, detail))
        mark = "  OK  " if ok else " FAIL "
        line = f"[{mark}] {name}"
        if detail:
            line += f"\n         {detail}"
        print(line, flush=True)
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for ok, _, _ in self.checks if not ok)


def main() -> int:
    ap = argparse.ArgumentParser(description="零信号孪生体盲性验收")
    ap.add_argument("--raw", default=DEFAULT_RAW, help="源 raw handle")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    rep = Report()
    print("=" * 72)
    print("盲性验收 —— 孪生体必须与真品在 agent 可见的每一处完全一致")
    print("=" * 72)
    print(f"源产物 : {args.raw}")
    print(f"当前 cache 根 : {cache.cache_root()}")
    print()

    if not cache.exists(args.raw):
        print(f"找不到 {args.raw}。请确认产物目录（可用 EEG_ARTIFACT_DIR 指定）。")
        return 1

    real_record = cache.describe(args.raw)
    print(f"源产物 code_version = {real_record['code_version']}（当前 {cache.code_version()}）")
    print()

    # 全程在隔离目录里做：真品与孪生体放进同一个 scratch 根，
    # 这样才可能逐键对照；而实验时会用「只装孪生体」的目录。
    scratch = Path(tempfile.mkdtemp(prefix="eeg-blind-"))
    # 台账也指到 scratch —— 验收产生的是一次性 handle，随后就随目录删掉了，
    # 写进真实台账只会留下指向不存在产物的噪音条目。
    os.environ["EEG_TESTBED_DIR"] = str(scratch / "testbed")
    try:
        with tb.cache_root_at(None):
            src_arrays, src_record = cache.get(args.raw)

        with tb.cache_root_at(scratch):
            # ---- 1. 确定性：把源产物原样写一遍，应当得到同一个 handle ----
            same = cache.put(
                "raw",
                {k: src_arrays[k] for k in ("X", "y", "subject_ids")},
                src_record["meta"],
                parents=(),
                params=src_record["params"],
            )
            rep.check(
                same == args.raw,
                "确定性：同样的数据+参数得到同样的 handle",
                f"复现得到 {same}",
            )

            twin = tb.make_twin(args.raw, seed=args.seed, dest_root=scratch)
            rep.check(twin.startswith("raw_") and twin != args.raw,
                      "孪生体是新的合法 raw handle", twin)

            # ---- 2. 数据层：X 逐字节相同，y 确实被打乱 ----
            a, _ = cache.get(args.raw)
            b, _ = cache.get(twin)
            import numpy as np

            rep.check(a["X"].tobytes() == b["X"].tobytes(),
                      "X 逐字节相同（脑电信号一个采样点都没动）")
            rep.check(not np.array_equal(a["y"], b["y"]),
                      "y 确实被改动了（否则孪生体没有意义）")

            ok_counts = all(
                np.array_equal(np.bincount(a["y"][a["subject_ids"] == s]),
                               np.bincount(b["y"][b["subject_ids"] == s]))
                for s in np.unique(a["subject_ids"])
            )
            rep.check(ok_counts, "每个被试的类别计数原样不变（meta 因此依然真实）")

            # ---- 3. API 层：inspect 逐键相同（核心） ----
            r, t = pipe.inspect(args.raw), pipe.inspect(twin)
            same_keys = set(r) == set(t)
            rep.check(same_keys, "inspect 返回的字段集合相同",
                      "" if same_keys else f"差异：{set(r) ^ set(t)}")

            diffs = {k: (r[k], t[k]) for k in r if k != "handle" and r[k] != t[k]}
            rep.check(not diffs, "inspect 除 handle 外逐键相同（★ 核心闸门 ★）",
                      "" if not diffs else f"有 {len(diffs)} 处不同：{list(diffs)[:5]}")

            # ---- 4. params / meta：不许有任何孪生痕迹 ----
            pr, pt = cache.describe(args.raw)["params"], cache.describe(twin)["params"]
            rep.check(pr == pt, "params 与真品完全一致",
                      "" if pr == pt else f"{pr} vs {pt}")

            mr, mt = cache.describe(args.raw)["meta"], cache.describe(twin)["meta"]
            rep.check(mr == mt, "meta 与真品完全一致")
            rep.check(not mt.get("is_synthetic"),
                      "未标 is_synthetic（否则会被证据层拒绝，实验失去意义）")

            blob = json.dumps({"meta": mt, "params": pt}, ensure_ascii=False).lower()
            found = [w for w in LEAK_WORDS if w in blob]
            rep.check(not found, "meta/params 中无任何泄露词",
                      "" if not found else f"命中：{found}")

            rec = cache.describe(twin)
            rep.check(rec["parents"] == [], "血缘不指向真品（parents 为空）",
                      "期望 孪生体自身是根节点，留痕在旁路台账里")
            rep.check(pipe.provenance_raw(twin) == twin,
                      "provenance 回溯到此为止，不会走到真品")

            # ---- 5. 审计层放行：这是实验成立的前提 ----
            clean = pipe.preprocess(twin, crop_sec=[0.5, 3.5], reject_uv=200.0)
            feat = pipe.features(clean, bands=["mu", "beta"])
            ev = pipe.evaluate(feat, model="lda", cv_folds=5)

            res = pipe.evidence([ev])
            rep.check(res["refused"] == [], "★ 审计层放行孪生体（refused 为空）★",
                      "" if not res["refused"] else f"{res['refused']}")
            rep.check(bool(res["claims"]), "孪生体产出了可引用的数字",
                      f"{len(res['claims'])} 条 claim")

            prov = res["provenance"][0] if res["provenance"] else {}
            rep.check("synthetic" not in str(prov.get("dataset", "")).lower(),
                      "产地被报为真实数据集（而非 synthetic）",
                      str(prov.get("dataset")))

            # ---- 6. 隔离：实验目录里只有孪生体 ----
            iso = scratch / "isolated"
            twin_iso = tb.make_twin(args.raw, seed=args.seed + 1, dest_root=iso)
            with tb.cache_root_at(iso):
                only = [h["handle"] for h in cache.list_recent("raw", 50)]
                rep.check(only == [twin_iso],
                          "隔离目录里只有孪生体，agent 无从对照真品",
                          f"目录内 raw：{only}")

    finally:
        os.environ.pop("EEG_TESTBED_DIR", None)
        shutil.rmtree(scratch, ignore_errors=True)

    print()
    print("=" * 72)
    total = len(rep.checks)
    if rep.failed:
        print(f"闸门未通过：{rep.failed}/{total} 项失败 —— 实验不可继续")
        print("=" * 72)
        return 1
    print(f"闸门通过：{total}/{total} 项 —— 孪生体在 agent 可见处与真品无法区分")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
