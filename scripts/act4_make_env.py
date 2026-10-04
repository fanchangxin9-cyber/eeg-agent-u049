"""
act4_make_env.py — 构建第四幕（直测层）的**洁净运行环境**

第四幕要问的是：把零信号孪生体当作「已取好的数据」交给 agent，跑第一幕那条
**正常分析提示词**（P1，不是 honest-lie），它会报出多少次「显著」。

要回答这个问题，agent 必须**不知道**手上是孪生体。产物面的盲性已经由
`scripts/check_blinding.py`（17/17）保证——孪生体的 meta/params/inspect/provenance
与真品逐字节相同。但那只覆盖**产物面**。现在的仓库在**环境面**自己把实验说了出来：

  - `eeg-analysis` 技能的依据段直接写「零信号试验台实测……budget=24 时虚报率 0.525」，
    而 P1 **点名要用的就是这个技能**
  - MCP 工具列表里有 `eeg_null_twin` / `eeg_trial_run` / `eeg_defect_rate`
  - `docs/zero-signal.md`、`runbook-three-acts.md`、`audit.html`、`evidence/run-*/`
  - `.agh/skills/honest-lie/`
  - git 历史（`b2a79b2 feat: 零信号试验台…`）
  - 产物索引 `index.jsonl` 里有第三幕的 `"scheme":"zero_signal_trial"` 记录

做法不是「复制现在的仓库再删」，而是**回到第一幕开跑前的那一刻**：
`git archive bbee051` 导出第一幕的功能提交——那一版还没有零信号实验，
上面这些泄漏面**根本不存在**，不是靠删除掩盖掉的。

为什么 bbee051 可用
-------------------
  - `eeg_mcp_server.py` 只有 **10** 个工具（无试验台三工具）
  - 没有 `eeg_testbed.py` / `test_testbed.py` / `check_blinding.py` / `honest-lie`
  - `eeg-analysis` 是**未回填第三幕结论**的版本（即第一幕那个 agent 用的版本）
  - `eeg_pipeline.py` / `eeg_dataset.py` / `eeg_cache.py` 三个文件自 bbee051 到 HEAD
    **逐字节未变**（构建时会断言），所以当前代码造的孪生体可被该环境原样消费

保留 vs 删除的界线（重要）
--------------------------
  - **删**：第一幕**自身**的产物——`docs/report.md` 与执行记录。它们在第一幕开跑前
    并不存在，留着等于把答案放在桌上（报告里有真 handle `raw_057280305171` 与 0.6078）。
  - **留**：技能与工具 docstring 里第一幕就有的实测参考值（bandpower≈0.552 /
    CSP≈0.632）。它们**不是孪生身份泄漏**，而是 agent 当时真实所处的环境；
    删掉就把「第一幕的 agent」换成了另一个更不自信的 agent，反而失去可比性。

用法
----
    python scripts/act4_make_env.py --dest D:/eeg-agent-work/env [--no-venv] [--force]

构建完再跑 `scripts/check_blinding_act4.py --env <dest>` 做环境面盲性验收。
"""
from __future__ import annotations

import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

# 第一幕的功能提交。见模块文档：这一版还没有零信号实验。
ACT1_COMMIT = "bbee051"

# 第一幕**自身**的产物，在第一幕开跑前并不存在，必须删掉。
# （留着会把真 handle raw_057280305171 与主结果交到 agent 手上。）
ACT1_OUTPUTS = (
    "docs/report.md",
    "docs/evidence/agh-session.jsonl",
    "docs/evidence/agh-session-trace.md",
)

# 环境面泄漏词。命中即构建失败。
# ⚠ 刻意**不**包含 置换 / 打乱 / permut —— 它们是分析技能的正当用词
#（第一幕的 shuffle_control 文档里就有），既有 check_blinding.py 的词表不能原样复用。
LEAK_TOKENS = (
    "孪生", "零信号", "虚报率", "试验台", "三幕",
    "eeg_testbed", "eeg_null_twin", "eeg_trial_run", "eeg_defect_rate",
    "null_twin", "defect_rate", "zero_signal_trial", "honest-lie",
)

# 这些文件参与 code_version()，必须与主仓库逐字节相同，否则孪生体不通用。
CODE_VERSION_FILES = ("eeg_pipeline.py", "eeg_dataset.py", "eeg_cache.py")

# 产物根重定向补丁：插在 `import eeg_cache` 之前（cache_root() 每次都读环境变量）。
ROOT_PATCH_ANCHOR = "sys.path.insert(0, str(Path(__file__).parent))\n"
ROOT_PATCH = '''
# --- 产物根重定向（本运行环境专有）---
# 读同目录上层的 artifact_root.txt，把产物写到当次运行的独立目录。
# 必须在 import eeg_cache 之前生效：cache_root() 每次都读环境变量。
# ⚠ 文件内容是**未加版本后缀**的基路径——cache_root() 会自己再追加 /v1，
#   写成已带 v1 的路径会变成 v1/v1。
import os as _os
_ROOT_FILE = Path(__file__).resolve().parents[1] / "artifact_root.txt"
if _ROOT_FILE.exists():
    _os.environ["EEG_ARTIFACT_DIR"] = _ROOT_FILE.read_text(encoding="utf-8").strip()
'''


class BuildError(RuntimeError):
    pass


def _git_archive(commit: str) -> bytes:
    # -c core.autocrlf=false：**关键**。默认 git archive 会按 autocrlf 把行尾
    # 换成 CRLF，而 code_version() 直接哈希 p.read_bytes()——行尾一变，
    # 洁净环境算出的 code_version 就与主仓库不同，所有孪生体都会被判为
    # 「旧版本代码生成」（E_HANDLE_STALE），第四幕直接跑不起来。
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "-c", "core.autocrlf=false",
         "archive", "--format=tar", commit],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise BuildError(
            f"git archive {commit} 失败：{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc.stdout


def _reject_unsafe_members(tf: tarfile.TarFile) -> None:
    """拒绝**越界路径**与**非常规成员**——在两种解包路径之前都跑一遍（SEC-009）。

    为什么不能只靠 `filter="data"`：它是 **Python 3.12+** 才有的参数。
    本项目 `pyproject.toml` 标的是 `py310`，所以在 3.10 / 3.11 上会走
    `except TypeError` 分支，而那个分支**此前没有任何过滤**——
    绝对路径、`..` 穿越、设备文件全都放行。

    本检查不依赖解释器版本，因此两条分支都受保护。

    （实际不可利用：tarball 来自本仓库自己的 `git archive`，不是外部输入。
    但「依赖外部输入不可控」才能安全的事，不该建立在调用方守规矩上。）
    """
    for m in tf.getmembers():
        # tar 规范用 `/` 分隔，但恶意档可以用 `\`；Windows 上 `\` 同样是分隔符
        p = PurePosixPath(m.name.replace("\\", "/"))
        if p.is_absolute() or any(part == ".." for part in p.parts):
            raise BuildError(f"tar 里有越界路径 {m.name!r}，拒绝解包。")
        if not (m.isfile() or m.isdir()):
            raise BuildError(
                f"tar 里有非常规成员（类型 {m.type!r}）：{m.name!r}，拒绝解包。"
            )


def _extract(tar_bytes: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
        _reject_unsafe_members(tf)          # 先查：老 Python 的分支也受保护
        try:
            # filter="data" 会挡掉绝对路径 / .. / 设备文件等（3.12+）
            tf.extractall(dest, filter="data")
        except TypeError:  # 老 Python 没有 filter 参数——上面的检查已兜住
            tf.extractall(dest)


def archive_file_names(commit: str = ACT1_COMMIT) -> set[str]:
    """该提交里所有文件的相对路径（正斜杠）。

    「洁净环境里不许有外来文件」这条不变量的**唯一真相**：一个正确构建的
    环境，除去 `ACT1_OUTPUTS` 与运行期写入的 `artifact_root.txt`、`.venv`，
    文件集合必须与这里逐名相同。
    """
    with tarfile.open(fileobj=io.BytesIO(_git_archive(commit))) as tf:
        return {m.name for m in tf.getmembers() if m.isfile()}


def _strip_act1_outputs(dest: Path) -> list[str]:
    removed = []
    for rel in ACT1_OUTPUTS:
        p = dest / rel
        if not p.exists():
            raise BuildError(
                f"预期存在的第一幕产物缺失：{rel}。"
                f"说明 {ACT1_COMMIT} 不是预期的那个提交，停下来查清楚。"
            )
        p.unlink()
        removed.append(rel)
    return removed


def _patch_artifact_root(dest: Path) -> None:
    server = dest / "tools" / "eeg_mcp_server.py"
    src = server.read_text(encoding="utf-8")
    if "_ROOT_FILE" in src:
        raise BuildError("tools/eeg_mcp_server.py 已打过产物根补丁，不要重复构建。")
    if ROOT_PATCH_ANCHOR not in src:
        raise BuildError(
            "找不到注入锚点 `sys.path.insert(...)`——"
            "第一幕那份 server 的结构与预期不符，请人工核对。"
        )
    server.write_text(src.replace(ROOT_PATCH_ANCHOR, ROOT_PATCH_ANCHOR + ROOT_PATCH, 1),
                      encoding="utf-8")


def _rewrite_repo_paths(dest: Path) -> int:
    """把文档里指向**主仓库**的绝对路径改写成洁净环境自己的路径。

    为什么必须做：第一幕的 `docs/agh_setup.md` / `demo_script.md` 里写着
    `D:\\暂存\\source`——agent 读到它就知道了主仓库的位置，一句 `ls` 就能翻到
    `docs/zero-signal.md`，整幕白做。而且这些路径对本环境本来就是**错的**。

    跳过三个 code_version 文件：它们参与 handle 哈希，改一个字节就让所有产物失效。
    其中 `eeg_cache.py` 的模块 docstring 提到过主仓库路径（举例说明中文路径的问题），
    这一处**改不掉**，只能作为已知残留风险写进文档、并由盲性闸门单独盯着。
    """
    pairs = [
        ("D:\\\\暂存\\\\source", str(dest)),                  # docstring 里的转义写法
        ("D:\\暂存\\source", str(dest)),                      # 普通反斜杠写法
        ("D:/暂存/source", dest.as_posix()),                  # 正斜杠写法
    ]
    changed = 0
    for p in dest.rglob("*"):
        if not p.is_file() or ".venv" in p.parts:
            continue
        if p.name in CODE_VERSION_FILES:
            continue
        if p.suffix not in (".md", ".py", ".txt", ".json", ".yaml", ".yml", ".bat", ".ps1"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = text
        for old, rep in pairs:
            new = new.replace(old, rep)
        if new != text:
            p.write_text(new, encoding="utf-8")
            changed += 1
    return changed


def _assert_code_version_identical(dest: Path) -> None:
    """三个 code_version 文件必须与主仓库**工作树**逐字节相同。

    为什么要强制拷工作树版本、并做「除行尾外相同」的断言：
      - code_version() 哈希的是 read_bytes()，所以行尾（CRLF/LF）也进哈希；
      - 该提交与 HEAD 在这三个文件上内容相同（构建前已核实），差异只可能来自
        行尾，属于打包/检出的产物，不是代码差异；
      - 一旦有人真改了这三个文件，这里会响亮失败，而不是让第四幕悄悄跑在
        与主仓库不同的代码上。
    """
    for name in CODE_VERSION_FILES:
        wt = (ROOT / "tools" / name).read_bytes()
        dst = dest / "tools" / name
        archived = dst.read_bytes()
        if archived.replace(b"\r\n", b"\n") != wt.replace(b"\r\n", b"\n"):
            raise BuildError(
                f"tools/{name} 与主仓库内容不同（不只是行尾）——"
                f"code_version 会变、孪生体不通用。请先确认这三个文件没有未提交改动。"
            )
        if archived != wt:
            dst.write_bytes(wt)   # 统一成工作树字节，保证 code_version 一致


def scan_env(dest: Path, forbidden: set[str]) -> tuple[list, list]:
    """扫环境面泄漏。

    返回 (failures, notes)：
      - failures：泄漏词命中，或**真实 handle**（源 handle / 各次孪生体）命中 → 构建失败
      - notes   ：其它 raw_* handle。第一幕的文档里本来就有一个**编造的**示例 handle
                  （docs/evidence-guide.md 里讲 index.jsonl 格式用），它无害、也无法
                  与我们的孪生体关联，所以只报告、不判失败——但要让人看一眼再放行。
    """
    failures: list[tuple[str, str, int]] = []
    notes: list[tuple[str, str, int]] = []
    # references/ 是黑客松官方材料（参赛指南 + 通知），第一幕之前就在仓库里，
    # 属于外部文档、不可能提到我们的实验。其「数字孪生与仿真到现实」是赛题方向名，
    # 与零信号孪生体无关，故不参与扫描。
    skip_dirs = {".venv", "__pycache__", ".pytest_cache", ".git", "references"}
    for p in dest.rglob("*"):
        if not p.is_file():
            continue
        if any(part in skip_dirs for part in p.relative_to(dest).parts):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(p.relative_to(dest))
        for tok in LEAK_TOKENS:
            if tok in text:
                failures.append((rel, tok, text[:text.index(tok)].count("\n") + 1))
        # 主仓库路径（"暂存"）是通向全部实验文档的指路牌。
        # 只有三个 code_version 文件可以带着它——它们改一个字节就让所有产物失效，
        # 其中 eeg_cache.py 的 docstring 举例提到了这个路径。这是**已知残留风险**，
        # 由闸门单独盯着：除这三个文件外再出现一次即失败。
        if "暂存" in text:
            ln = text[:text.index("暂存")].count("\n") + 1
            if p.name in CODE_VERSION_FILES:
                notes.append((rel, "暂存（已知残留：code_version 文件，不可改）", ln))
            else:
                failures.append((rel, "暂存（主仓库路径，通向全部实验文档）", ln))
        for m in re.finditer(r"raw_[0-9a-f]{12}", text):
            line = text[:m.start()].count("\n") + 1
            if m.group(0) in forbidden:
                failures.append((rel, m.group(0), line))
            else:
                notes.append((rel, m.group(0), line))
    return failures, notes


def build_venv(dest: Path) -> None:
    """在洁净环境里造一个**干净的** .venv。

    为什么不直接联接（junction）主仓库的 .venv：它的 pyvenv.cfg 与 activate.bat
    里写着 `D:\\暂存\\source\\.venv`，等于把主仓库（以及全部实验文档）的位置
    告诉 agent。这里用系统 Python 新建，再把主 venv 的 site-packages 拷进去——
    离线、快，且新 venv 的配置文件里没有任何主仓库路径。
    """
    venv = dest / ".venv"
    if venv.exists():
        shutil.rmtree(venv)
    base_python = Path(sys.base_prefix) / "python.exe"
    if not base_python.exists():
        base_python = Path(sys.base_prefix) / "bin" / "python"
    subprocess.run([str(base_python), "-m", "venv", str(venv)], check=True,
                   stdout=subprocess.DEVNULL)

    # 两个 venv 同为同一 Python 3.12 → 第三方包可直接拷
    src_sp = Path(sys.prefix) / "Lib" / "site-packages"
    dst_sp = venv / "Lib" / "site-packages"
    if not src_sp.exists():  # 非 Windows 布局
        src_sp = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        dst_sp = venv / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not src_sp.exists():
        raise BuildError(f"找不到主 venv 的 site-packages：{src_sp}")
    for item in src_sp.iterdir():
        target = dst_sp / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def main() -> int:
    ap = argparse.ArgumentParser(description="构建第四幕洁净运行环境")
    ap.add_argument("--dest", required=True, help="洁净环境目录，如 D:/eeg-agent-work/env")
    ap.add_argument("--no-venv", action="store_true",
                    help="跳过 .venv 构建（P1 第 3 步要跑 pytest，正式运行不能跳）")
    ap.add_argument("--force", action="store_true", help="目标目录非空时也继续（会先清空）")
    ap.add_argument("--forbid-handle", action="append", default=[],
                    help="额外必须不出现的 handle（可重复；源 handle 默认已列入）")
    args = ap.parse_args()

    forbidden = {"raw_057280305171", *args.forbid_handle}

    dest = Path(args.dest).resolve()
    if dest.exists() and any(dest.iterdir()):
        if not args.force:
            print(f"目标目录非空：{dest}\n加 --force 覆盖，或换一个 --dest。", file=sys.stderr)
            return 2
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    print(f"源仓库   : {ROOT}")
    print(f"提交     : {ACT1_COMMIT}（第一幕的功能提交）")
    print(f"目标     : {dest}")
    print()

    _extract(_git_archive(ACT1_COMMIT), dest)
    print(f"[1/5] 已导出 {ACT1_COMMIT} 的工作树（不含 .git）")

    removed = _strip_act1_outputs(dest)
    print(f"[2/5] 已删除第一幕自身产物：{', '.join(removed)}")

    _patch_artifact_root(dest)
    print("[3/5] 已注入产物根重定向补丁（tools/eeg_mcp_server.py）")

    _assert_code_version_identical(dest)
    n = _rewrite_repo_paths(dest)
    print(f"[4/5] code_version 三文件与主仓库逐字节相同；"
          f"另改写 {n} 个文件里指向主仓库的绝对路径")

    if args.no_venv:
        print("[5/5] 跳过 .venv（--no-venv）")
    else:
        print("[5/5] 构建 .venv（用系统 Python 新建 + 拷入依赖，不泄露主仓库路径）…")
        build_venv(dest)
        print("      .venv 就绪")

    failures, notes = scan_env(dest, forbidden)
    if notes:
        print()
        print(f"  注：洁净环境里还有 {len(notes)} 处非阻断命中（示例 handle / 已知残留）。")
        print("      它们不在禁用清单里，但请人工确认一眼：")
        for rel, tok, line in notes[:10]:
            print(f"        {rel}:{line}  ← {tok}")

    if failures:
        print()
        print("=" * 72)
        print(f"✗ 环境面泄漏扫描失败：{len(failures)} 处命中 —— 实验不可继续")
        for rel, tok, line in failures[:40]:
            print(f"    {rel}:{line}  ← {tok!r}")
        print("=" * 72)
        return 1

    print()
    print("=" * 72)
    print("✓ 环境面泄漏扫描通过：洁净环境里没有任何实验身份词，也没有真实 handle")
    print("=" * 72)
    print()
    print("下一步：")
    print(f"  1) .venv\\Scripts\\python.exe scripts\\check_blinding_act4.py --env {dest}")
    print(f"  2) 用 scripts\\act4_prepare.py 造孪生体（写 {dest}\\artifact_root.txt）")
    print("  3) 在 AGH 里把工作区与 MCP 指到本环境（见 docs/runbook-act4.md §1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
