"""第四幕洁净环境构建里，**tar 解包的安全检查**（SEC-009）。

背景
----
`scripts/act4_make_env.py` 用 `git archive <提交>` 打出 tar，再解包成洁净工作树。
解包走的是：

    try:
        tf.extractall(dest, filter="data")   # Python 3.12+ 才有 filter
    except TypeError:
        tf.extractall(dest)                  # ← 老 Python 走这里，**原本毫无过滤**

`pyproject.toml` 标的是 `py310`，所以 3.10 / 3.11 上真的会走那条无过滤分支。

实际不可利用（tarball 来自本仓库自己的 `git archive`，不是外部输入），
但「只有靠调用方守规矩才安全」不是安全——所以加了一道**不依赖解释器版本**的成员检查。

这一组测试就是拿**构造出来的越界 tar** 去打它。
"""
from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import act4_make_env as mk  # noqa: E402


def _tar(members: list[tuple[str, bytes]]) -> tarfile.TarFile:
    """把 (名字, 内容) 列表打成内存里的 tar，返回已打开的 TarFile。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return tarfile.open(fileobj=buf)


def test_普通成员照常通过():
    """安全检查不能误伤正常归档。"""
    with _tar([("a/b.txt", b"ok"), ("c/d/e.py", b"x = 1\n")]) as tf:
        mk._reject_unsafe_members(tf)      # 不应抛


@pytest.mark.parametrize("name", [
    "/etc/evil.txt",              # POSIX 绝对路径
    "../evil.txt",                # 上位穿越
    "a/../../evil.txt",           # 夹层穿越
    "a/b/../../../evil.txt",      # 更深的穿越
    "..\\..\\evil.txt",           # 反斜杠穿越（Windows 上同样是分隔符）
    "a\\..\\..\\evil.txt",
])
def test_越界路径被拒(name):
    with _tar([(name, b"x")]) as tf, pytest.raises(mk.BuildError, match="越界路径"):
        mk._reject_unsafe_members(tf)


def test_非常规成员被拒():
    """符号链接 / 设备文件 / FIFO 都不是「文件」或「目录」，一律拒绝。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        link = tarfile.TarInfo("a/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    buf.seek(0)
    with tarfile.open(fileobj=buf) as tf, pytest.raises(mk.BuildError, match="非常规成员"):
        mk._reject_unsafe_members(tf)


def test_extract_整体拒绝越界归档(tmp_path):
    """端到端：`_extract()` 面对越界 tar 必须**一个文件都不落**。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("../escaped.txt")
        info.size = 5
        tf.addfile(info, io.BytesIO(b"pwned"))
    dest = tmp_path / "out"
    dest.mkdir()

    with pytest.raises(mk.BuildError):
        mk._extract(buf.getvalue(), dest)

    assert not (tmp_path / "escaped.txt").exists(), "越界文件被写出去了"
    assert list(dest.iterdir()) == [], "越界归档不该在目标目录留下任何东西"
