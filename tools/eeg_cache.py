"""
eeg_cache.py — 产物存储（recipe 寻址）

为什么需要它
------------
AGH 与 MCP 工具之间只应传递**小消息**。64 通道的 EEG 事件段如果序列化成 JSON
在工具间传递，单次调用就是数百 MB。这里把中间产物落到磁盘，工具之间只传一个
短 handle。

为什么不是"内容哈希"
--------------------
handle 由**配方（recipe）**决定，而不是由数组字节决定：

    handle = f"{kind}_{hash(recipe)[:12]}"

    recipe = {schema, code_version, op, parents, params}

好处是确定性——同样的输入和参数必然得到同样的 handle，因此 agent 反复试配置时
命中的缓存能直接复用，且血缘（parents）天然构成可审计的推导树。

`code_version` 不是可选项：如果中途修了预处理里的 bug，而没有把它算进 handle，
那么 agent 拿到的就是**旧代码算出来的产物**，你会对着一个幽灵般的性能回退排查到
半夜。

产物目录默认放在仓库**外面**（%LOCALAPPDATA%）：本仓库路径含中文
（`D:\\暂存\\source`），Python 本身能处理，但 numpy 的 mmap、joblib 的 memmap 以及
部分 MNE/pooch 内部逻辑在非 ASCII 路径下不够可靠，失败形态是一个难以定位的
Windows OSError。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# 破坏性变更时手动 +1，旧产物会因 schema 不匹配而失效
CACHE_SCHEMA = 1

HANDLE_RE = re.compile(r"^(raw|clean|feat|eval)_[0-9a-f]{12}$")

_KIND_LABEL = {
    "raw": "事件段数据",
    "clean": "预处理后的事件段",
    "feat": "特征矩阵",
    "eval": "评估结果",
}


class CacheError(Exception):
    """带结构化错误码与恢复建议的异常。"""

    def __init__(self, code: str, message: str, suggestions: list[str] | None = None,
                 recoverable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggestions = suggestions or []
        self.recoverable = recoverable

    def as_dict(self) -> dict:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "recoverable": self.recoverable,
                "suggestions": self.suggestions,
            },
        }


def cache_root() -> Path:
    """产物目录。默认在仓库之外，可用 EEG_ARTIFACT_DIR 覆盖。"""
    env = os.environ.get("EEG_ARTIFACT_DIR")
    if env:
        root = Path(env)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "eeg-agent" / "artifacts"
    root = root / f"v{CACHE_SCHEMA}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _index_path() -> Path:
    return cache_root() / "index.jsonl"


# ---- 代码版本：让"改了代码但复用旧产物"这件事不可能悄悄发生 ----
_CODE_VERSION: str | None = None


def code_version() -> str:
    global _CODE_VERSION
    if _CODE_VERSION is None:
        h = hashlib.sha256()
        for name in ("eeg_pipeline.py", "eeg_dataset.py", "eeg_cache.py"):
            p = Path(__file__).parent / name
            h.update(name.encode())
            h.update(p.read_bytes() if p.exists() else b"<missing>")
        _CODE_VERSION = h.hexdigest()[:12]
    return _CODE_VERSION


def _canonical(obj: Any) -> Any:
    """把参数规格化，保证等价参数得到同一个哈希。"""
    if isinstance(obj, dict):
        return {str(k): _canonical(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_canonical(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, np.generic):
        return _canonical(obj.item())
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _digest(recipe: dict) -> str:
    blob = json.dumps(_canonical(recipe), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def _fingerprint(payload: dict[str, np.ndarray]) -> str:
    """数组内容指纹。

    只靠 recipe（操作 + 参数 + 上游 handle）寻址是**不安全**的：如果调用方
    传了两组内容不同、但参数相同的数组（例如单元测试里直接构造 raw 数据），
    两者会算出同一个 handle，后写入的会直接命中前者的缓存，结果是静默串数据——
    而且不报错，只出错结果。

    把内容指纹并进 recipe 可以杜绝这种碰撞，同时保留"同数据 + 同参数 → 同 handle"
    的缓存复用能力。

    代价是每次写入要多哈希一遍数组。相对于上游的信号处理，这个开销可以忽略；
    而静默串数据的排查成本极高，不值得为省这点时间冒险。
    """
    h = hashlib.sha256()
    for k in sorted(payload):
        a = np.ascontiguousarray(payload[k])
        h.update(k.encode("utf-8"))
        h.update(str(a.shape).encode("utf-8"))
        h.update(str(a.dtype).encode("utf-8"))
        h.update(a.tobytes())
    return h.hexdigest()[:16]


def put(
    kind: str,
    arrays: dict[str, np.ndarray],
    meta: dict[str, Any],
    parents: Iterable[str] = (),
    params: dict | None = None,
) -> str:
    """写入产物并返回 handle。

    kind    产物类别：raw / clean / feat / eval
    arrays  numpy 数组，以 float32 存 .npy（不压缩：agent 会跑十几轮评估，
            每次压缩几秒不划算，磁盘便宜得多）
    meta    可 JSON 序列化的摘要信息
    parents 上游 handle，参与哈希，构成血缘
    params  本次操作的参数，参与哈希
    """
    if kind not in _KIND_LABEL:
        raise CacheError("E_BAD_KIND", f"未知产物类别 {kind!r}，可用：{sorted(_KIND_LABEL)}",
                         recoverable=False)

    parents = list(parents)
    params = params or {}
    payload = {k: np.asarray(v) for k, v in arrays.items()}
    recipe = {
        "schema": CACHE_SCHEMA,
        "code_version": code_version(),
        "op": kind,
        "parents": parents,
        "params": params,
        "data": _fingerprint(payload),
    }
    handle = f"{kind}_{_digest(recipe)}"

    root = cache_root()
    npz_path = root / f"{handle}.npz"
    json_path = root / f"{handle}.json"

    record = {
        "handle": handle,
        "kind": kind,
        "schema": CACHE_SCHEMA,
        "code_version": recipe["code_version"],
        "parents": parents,
        "params": params,
        "data_fingerprint": recipe["data"],
        "meta": meta,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    if not npz_path.exists():
        # 原子写：AGH 可能并发发工具调用，半写的文件被并发读到会得到垃圾而**不是**报错
        #
        # 必须用 savez 而不是 save：save 会把 dict 当成单个对象数组写成 0 维，
        # 且因 allow_pickle=False 直接报"Object arrays cannot be saved"。
        tmp = root / f".{uuid.uuid4().hex}.tmp.npz"
        with tmp.open("wb") as fh:
            np.savez(fh, **payload)
        os.replace(tmp, npz_path)

    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    # 追加式执行记录。这不只是调试用——它就是指南 §7 要求的
    # 「AGH 执行记录」证据本身，可直接附进提交材料。
    _append_index({
        "ts": record["created_utc"],
        "handle": handle,
        "kind": kind,
        "parents": parents,
        "params": params,
        "shapes": {k: list(np.asarray(v).shape) for k, v in arrays.items()},
        "bytes": int(sum(np.asarray(v).nbytes for v in arrays.values())),
    })
    return handle


def _append_index(entry: dict) -> None:
    try:
        with _index_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 索引写失败不应让主流程失败


def _recent_of_kind(kind: str | None, limit: int = 8) -> list[str]:
    """给错误恢复用：列出最近同类 handle。"""
    path = _index_path()
    if not path.exists():
        return []
    out: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if kind and rec.get("kind") != kind:
            continue
        h = rec.get("handle")
        if h and h not in out:
            out.append(h)
        if len(out) >= limit:
            break
    return out


def _validate(handle: str) -> Path:
    """handle 校验阶梯：格式 → 存在 → schema → 完整性。"""
    if not isinstance(handle, str) or not HANDLE_RE.match(handle):
        raise CacheError(
            "E_INVALID_HANDLE",
            f"handle 格式非法：{handle!r}。应形如 'clean_1a2b3c4d5e6f'。",
            suggestions=[h for h in _recent_of_kind(None)][:8],
            recoverable=False,
        )
    root = cache_root()
    json_path = root / f"{handle}.json"
    npz_path = root / f"{handle}.npz"

    if not json_path.exists() or not npz_path.exists():
        kind = handle.split("_", 1)[0]
        raise CacheError(
            "E_HANDLE_NOT_FOUND",
            f"handle {handle!r} 不存在。它可能已被清理，或来自另一次会话。",
            suggestions=_recent_of_kind(kind),
        )

    record = json.loads(json_path.read_text(encoding="utf-8"))
    if record.get("schema") != CACHE_SCHEMA:
        raise CacheError(
            "E_HANDLE_STALE",
            f"handle {handle!r} 由旧版本缓存格式（schema={record.get('schema')}）生成，"
            f"当前为 {CACHE_SCHEMA}。请重新生成。",
        )
    if record.get("code_version") != code_version():
        raise CacheError(
            "E_HANDLE_STALE",
            f"handle {handle!r} 由旧版本代码（{record.get('code_version')}）生成，"
            f"当前代码为 {code_version()}。结果可能已失效，请重新生成。",
        )
    return json_path


def exists(handle: str) -> bool:
    try:
        _validate(handle)
        return True
    except CacheError:
        return False


def describe(handle: str) -> dict:
    """只读元信息，不加载数组。"""
    return json.loads(_validate(handle).read_text(encoding="utf-8"))


def get(handle: str) -> tuple[dict[str, np.ndarray], dict]:
    """读取数组与记录。"""
    record = describe(handle)
    npz_path = cache_root() / f"{handle}.npz"
    with np.load(npz_path, allow_pickle=False) as npz:
        arrays = {k: npz[k] for k in npz.files}
    return arrays, record


def summary(handle: str) -> dict:
    """给 agent 的精简回执：handle + 摘要，绝不含数组内容。"""
    record = describe(handle)
    return {
        "ok": True,
        "handle": record["handle"],
        "kind": record["kind"],
        "summary": record["meta"],
    }


def list_recent(kind: str | None = None, limit: int = 10) -> list[dict]:
    """列出最近的产物，供 agent 从丢失的 handle 中恢复。"""
    return [{"handle": h, "kind": h.split("_", 1)[0]} for h in _recent_of_kind(kind, limit)]


def index_path() -> Path:
    """执行记录（index.jsonl）路径——提交材料里的「运行证据」。"""
    return _index_path()


def clear() -> int:
    root = cache_root()
    n = 0
    for p in list(root.glob("*.npz")) + list(root.glob("*.json")):
        p.unlink()
        n += 1
    return n


if __name__ == "__main__":
    print(f"cache root   : {cache_root()}")
    print(f"code version : {code_version()}")
    print(f"index        : {index_path()}")
    print(f"entries      : {len(_recent_of_kind(None, 10 ** 6))}", file=sys.stderr)
