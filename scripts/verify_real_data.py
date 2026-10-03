"""
verify_real_data.py — 在真实 EEGMMIDB 数据上跑一遍完整闭环

用途：
  1. 确认流水线在真实数据上确实能跑通（而不是只在合成数据上能跑）
  2. 收集提交材料所需的实际指标

运行：
  .venv/Scripts/python.exe scripts/verify_real_data.py --subjects 1 2 3 4 5 6

首次运行会从 PhysioNet 下载数据（约 7.5 MB/被试，实测约 11 分钟/被试）。
输出会被打印到 stdout，请**如实**复制到 docs/evidence-guide.md。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_cache as cache
import eeg_pipeline as pipe


def show(title: str, obj) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6])
    ap.add_argument("--task", default="left_vs_right_imagery")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--permutations", type=int, default=20)
    args = ap.parse_args()

    print(f"产物目录: {cache.cache_root()}")
    print(f"执行记录: {cache.index_path()}")

    # ---- 1. 取数 ----
    raw = pipe.fetch(subjects=args.subjects, task=args.task)
    rmeta = cache.describe(raw)["meta"]
    show("1. fetch", {
        "handle": raw, "source": rmeta["source"],
        "subjects_loaded": rmeta["subjects_loaded"],
        "n_epochs": rmeta["n_epochs"], "n_channels": rmeta["n_channels"],
        "sfreq": rmeta["sfreq"], "label_names": rmeta["label_names"],
        "failures": rmeta["failures"],
    })
    if rmeta.get("is_synthetic"):
        print("！！ 拿到的是合成数据，本次运行不能作为结果证据。")
        return 1

    # ---- 2. 诊断 ----
    diag = pipe.inspect(raw)
    show("2. inspect（决策依据）", {k: v for k, v in diag.items()
                                    if k != "epochs_per_subject"})
    n_subj = len(rmeta["subjects_loaded"])

    # ---- 3. 配置扫描 × 两种协议 ----
    clean = pipe.preprocess(raw, low_hz=8.0, high_hz=30.0,
                            crop_sec=[0.5, 3.5], reject_uv=150.0)

    configs = [
        ("bandpower mu,beta", "bandpower", ["mu", "beta"]),
        ("bandpower mu,beta,theta", "bandpower", ["mu", "beta", "theta"]),
        ("bandpower+asym mu,beta", "bandpower+asymmetry", ["mu", "beta"]),
    ]

    print(f"\n{'配置':<28} {'被试内':>9} {'跨被试':>9}   (被试数 {n_subj})")
    print("-" * 72)

    results: dict[tuple, tuple[str, dict]] = {}
    for name, fs, bands in configs:
        feat = pipe.features(clean, feature_set=fs, bands=bands, normalize="subject")
        row = []
        for scheme in ("within_subject", "cross_subject"):
            try:
                ev = pipe.evaluate(feat, model="lda", cv_folds=args.folds,
                                   cv_scheme=scheme)
            except ValueError as exc:
                row.append(f"({exc})"[:9])
                continue
            m = cache.describe(ev)["meta"]["metrics"]
            row.append(f"{m['balanced_accuracy_mean']:.4f}")
            results[(name, scheme)] = (ev, m)
        print(f"{name:<28} {row[0]:>9} {row[1] if len(row) > 1 else '-':>9}")

    # 被试内最好的一组作为主配置
    within = [(k, v) for k, v in results.items() if k[1] == "within_subject"]
    if not within:
        print("\n！！ 没有任何配置能完成被试内评估。")
        return 1
    best_key, (best_eval, best_m) = max(within, key=lambda kv: kv[1][1]["balanced_accuracy_mean"])
    print(f"\n主配置: {best_key[0]}（被试内）")

    show("3. 主配置明细", {
        "eval_handle": best_eval,
        "cv_scheme": best_m["cv_scheme"],
        "balanced_accuracy_mean": best_m["balanced_accuracy_mean"],
        "balanced_accuracy_std": best_m["balanced_accuracy_std"],
        "cohen_kappa": best_m["cohen_kappa"],
        "confusion_matrix": best_m["confusion_matrix"],
        "per_subject_accuracy": best_m["per_subject_accuracy"],
        "n_epochs": best_m["n_epochs"], "n_subjects": best_m["n_subjects"],
        "chance_level": best_m["chance_level"],
    })

    # ---- 4. 独立验证（协议必须与主配置一致）----
    # 重新取回对应的特征产物
    best_feat = cache.describe(best_eval)["meta"]["config"]["input_handle"]
    v = pipe.validate(best_feat, scheme="shuffle_control", model="lda",
                      cv_folds=args.folds, n_permutations=args.permutations,
                      cv_scheme="within_subject")
    vm = cache.describe(v)["meta"]
    show("4. 置换检验（防泄漏）", {
        "observed_balanced_accuracy": vm["observed_balanced_accuracy"],
        "null_distribution": vm["null_distribution"],
        "p_value": vm["p_value"],
        "conclusion": vm["conclusion"],
    })

    # ---- 5. 消融 ----
    if "cross_subject" in best_key[1]:
        abl = None
    else:
        try:
            abl = pipe.ablation(best_eval)
        except Exception as exc:  # 兜底：消融失败不应让整体校验崩掉
            abl = {"error": f"{type(exc).__name__}: {exc}"}
    show("5. 与冻结基线对比", abl)

    # ---- 6. 证据 ----
    evd = pipe.evidence([best_eval, v])
    show("6. 可写入报告的证据", {
        "n_claims": len(evd["claims"]),
        "claims": evd["claims"][:12],
        "provenance": evd["provenance"],
        "refused": evd["refused"],
    })

    show("7. 总结", {
        "best_eval_handle": best_eval,
        "best_config": best_key[0],
        "cv_scheme": "within_subject",
        "best_balanced_accuracy": best_m["balanced_accuracy_mean"],
        "p_value": vm["p_value"],
        "significant_at_0.05": vm["p_value"] < 0.05,
        "注意": "以上为真实运行输出，可如实填入 docs/evidence-guide.md。"
                "跨被试结果≈随机是已知现象，应如实报告，不要隐藏。",
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
