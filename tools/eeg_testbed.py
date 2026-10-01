"""
eeg_testbed.py — 零信号试验台

这个模块不参与任何正式结果，它只做一件事：**造出与真实数据在 API 表面
无法区分的「零信号孪生体」**，用来测量这套流程在没有任何信号的数据上，
会产出多少个「显著发现」。

为什么要孪生体
--------------
现有管线里，`eeg_evidence` 会拒绝一切 `is_synthetic=True` 的产物。所以拿
合成数据做这个实验是没意义的——它会在证据层就被拦下。

孪生体走的是另一条路：**数据是真的，标签是假的**。取一份真实的 `raw_*`，
在每个被试内部把标签打乱。脑电信号一个采样点都没动，只是「哪段是左手」
这个信息被抹掉了。于是：

- `is_synthetic` 不能写（写了就被拒，实验就失去意义）
- 它必须是一件**普通产物**，让审计层照常放行

盲性怎么保证
------------
不靠约定，靠**逐字节同构**。三条被代码结构保证的性质：

1. `eeg_cache._fingerprint` 把数组内容指纹并进 recipe。打乱 `y` 后 `X` 不变、
   `y` 变了 → 指纹变 → 自动得到一个新的合法 `raw_*` handle。不需要任何新
   kind、新 handle 规则。
2. `meta` 与 `params` **原样复制**自源产物，所以 `eeg_inspect` 回显的每一个
   字段与真品完全相同。（被试内打乱精确保留每个被试的类别计数，而 meta 里
   与标签有关的字段只有那些计数。）
3. `parents=()`，血缘不指向真品，`provenance_for` 会照常报出 EEGMMIDB。

于是 agent 唯一的差异感知渠道只剩 handle 字符串本身——而它手上没有真品的
handle 可以做对照。

「这是孪生体」这个事实只写在**产物目录之外的旁路清单**里，agent 没有任何
工具能读到它。
"""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

import numpy as np

import eeg_cache as cache

# 打乱方案
SCHEMES = ("within_subject", "within_subject_run")

_MANIFEST_NAME = "manifest.jsonl"


# ------------------------------------------------------------------ 旁路清单
def _bookkeeping_dir() -> Path:
    """试验台自己的簿记目录（表示映射、零分布池）。

    **与产物目录分开**：这里放的是「怎么复用」的索引，不是实验结果本身。
    放得离产物远一点，免得被误当成证据产物。
    """
    override = os.environ.get("EEG_TESTBED_DIR")
    if override:
        root = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "eeg-agent" / "testbed"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path() -> Path:
    """孪生身份的台账。

    **刻意放在产物目录之外**——它不属于 cache，任何 MCP 工具都不会读到它。
    放在 cache 里就等于把答案写在了考卷上。

    `EEG_TESTBED_DIR` 可覆盖（测试与验收脚本用，避免把一次性实验的
    临时 handle 写进真实台账——那些孪生体随后就被删了，留下的条目是噪音）。
    """
    override = os.environ.get("EEG_TESTBED_DIR")
    if override:
        root = Path(override)
    else:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = Path(base) / "eeg-agent" / "testbed"
    root.mkdir(parents=True, exist_ok=True)
    return root / _MANIFEST_NAME


def _read_manifest() -> list[dict]:
    path = _manifest_path()
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _record_manifest(entry: dict) -> None:
    with _manifest_path().open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def twin_truth(handle: str) -> dict | None:
    """查孪生身份。**仅供试验台内部使用**，不要接到任何 MCP 工具上。"""
    for rec in reversed(_read_manifest()):
        if rec.get("handle") == handle:
            return rec
    return None


def is_twin(handle: str) -> bool:
    return twin_truth(handle) is not None


def list_twins() -> list[dict]:
    return _read_manifest()


# ------------------------------------------------------------------ 目录切换
@contextlib.contextmanager
def cache_root_at(root: str | Path | None):
    """临时把 cache 根指到别处。

    为什么不给 `cache.put` 加一个 root 参数：`eeg_cache.py` 参与
    `code_version()` 的哈希，**改它一个字节，仓库里所有既有 handle 立刻失效**，
    包括 `docs/report.md` 引用的全部证据。用环境变量是唯一不碰它的办法
    （`cache.cache_root()` 每次都读环境变量）。
    """
    if root is None:
        yield
        return
    old = os.environ.get("EEG_ARTIFACT_DIR")
    os.environ["EEG_ARTIFACT_DIR"] = str(root)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("EEG_ARTIFACT_DIR", None)
        else:
            os.environ["EEG_ARTIFACT_DIR"] = old


# ------------------------------------------------------------------ 打乱
def permute_within_subject(y: np.ndarray, subject_ids: np.ndarray,
                           rng: np.random.Generator) -> np.ndarray:
    """在**每个被试内部**重排标签。

    必须逐被试打乱，不能全局打乱。全局打乱会让被试 A 的样本拿到被试 B 的
    标签，打乱本身就把数据搅成了完全不同的分布——这也正是
    `eeg_pipeline.py:857-874` 的 `permute_labels()` 采用逐被试打乱的原因。
    孪生体必须与 agent 内部定义的零假设同构，否则测的不是同一个东西。

    被试内打乱还有一个关键副作用：**每个被试的类别计数原样不变**。meta 里
    与标签有关的字段只有这些计数，所以 meta 复制过来依然准确。
    """
    out = y.copy()
    for sub in np.unique(subject_ids):
        m = subject_ids == sub
        out[m] = rng.permutation(y[m])
    return out


# ------------------------------------------------------------------ 造孪生体
def make_twin(source_handle: str, seed: int, *,
              source_root: str | Path | None = None,
              dest_root: str | Path | None = None,
              scheme: str = "within_subject") -> str:
    """从一份真实 `raw_*` 造出零信号孪生体，返回新的 `raw_*` handle。

    source_root 为 None 时用当前 cache 根；dest_root 为 None 时用当前 cache 根。
    两者不同即可把孪生体隔离到独立目录，真品从不进入。

    同一 (source, seed, scheme) 必然得到同一个 handle（配方是确定性的）。
    """
    if scheme not in SCHEMES:
        raise ValueError(f"未知 scheme {scheme!r}。可用：{list(SCHEMES)}")

    with cache_root_at(source_root):
        arrays, record = cache.get(source_handle)

    if record["kind"] != "raw":
        raise cache.CacheError(
            "E_BAD_INPUT_KIND",
            f"造孪生体需要 raw 产物，收到 {record['kind']!r}。",
            recoverable=False,
        )

    X = arrays["X"]
    y = arrays["y"]
    subjects = arrays["subject_ids"]

    rng = np.random.default_rng(seed)
    if scheme == "within_subject":
        y_twin = permute_within_subject(y, subjects, rng)
    else:  # within_subject_run：保守变体，见模块文档
        y_twin = _permute_within_subject_run(y, subjects, record.get("meta", {}), rng)

    # meta 与 params 原样复制 —— 这是盲性的全部秘密所在。
    # 被试内打乱保持每被试类别计数，所以 meta 里每个字段依然真实。
    meta = dict(record["meta"])
    params = dict(record["params"])

    with cache_root_at(dest_root):
        handle = cache.put(
            "raw",
            {"X": X, "y": y_twin.astype(y.dtype), "subject_ids": subjects},
            meta,
            parents=(),          # 不指向真品，血缘不泄露
            params=params,
        )

    _record_manifest({
        "handle": handle,
        "source_raw": source_handle,
        "seed": int(seed),
        "scheme": scheme,
        "n_permuted": int((y != y_twin).sum()),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return handle


def _permute_within_subject_run(y, subjects, meta, rng) -> np.ndarray:
    """敏感性分析用的保守变体：在每个 (被试, run) 块内打乱。

    EEGMMIDB 同一 run 内的试次有会话结构，严格的零假设应当在更小的块内成立。

    注意：需要知道每个试次属于哪个 run 才能切块，而现有 `raw_*` 的 meta 里
    没有逐试次的 run 信息。因此这个变体暂时退化为被试内打乱。
    等到 `fetch` 开始记录 run 归属后再启用。
    """
    return permute_within_subject(y, subjects, rng)


def rewind_labels(handle: str, seed: int, *,
                  source_root: str | Path | None = None,
                  dest_root: str | Path | None = None) -> str:
    """把任意产物的标签换成打乱版，**X 一个字节都不动**。

    为什么需要它 —— 这是让 N=100 做得起的那个优化：

    `preprocess()` 与 `features()` **都不使用标签**（归一化只用
    `subject_ids`）。所以同一份 X 的「清洗后表示」「特征表示」对所有孪生体
    都是同一个东西，只需要算一次；每个孪生体真正独有的，只有标签。

    于是流程变成：
        真数据 → 每个预处理组合算一次 clean/feat（一次性，约 60 s）
        每个孪生 → 对缓存好的表示重贴标签（便宜）→ 直接评估

    没有这一步，每个孪生都要重算一遍全部表示，N=100 会从 2.6 小时涨到
    4 小时以上。

    （正确性：预处理的伪迹剔除掩码只依赖 X，所以「先打乱再剔除」与
    「先剔除再在被试内打乱」等价——两者都只是在保留的试次上做一次被试内
    置换。）
    """
    with cache_root_at(source_root):
        arrays, record = cache.get(handle)

    kind = record["kind"]
    if kind not in ("raw", "clean", "feat"):
        raise cache.CacheError(
            "E_BAD_INPUT_KIND",
            f"重贴标签只支持 raw/clean/feat，收到 {kind!r}。",
            recoverable=False,
        )

    rng = np.random.default_rng(seed)
    y_new = permute_within_subject(arrays["y"], arrays["subject_ids"], rng)

    payload = dict(arrays)
    payload["y"] = y_new.astype(arrays["y"].dtype)

    with cache_root_at(dest_root):
        return cache.put(
            kind, payload, dict(record["meta"]),
            parents=(), params=dict(record["params"]),
        )


# ------------------------------------------------------------------ 搜索空间
def _build_search_space() -> tuple[dict, list[dict]]:
    """从 agent 真实探索过的参数里归纳出的搜索空间。

    这 5 个旋钮是 `index.jsonl` 里真实出现过的（见工具调用记录），
    笛卡尔积 = 3×3×2×2×2 = 72 个配置，与 agent 实际跑的 ~67 次评估同量级。
    """
    space = {
        "crop_sec": [[0.5, 3.5], [1.0, 4.0], [0.0, 4.0]],
        "reject_uv": [None, 150.0, 200.0],
        "channel_set": ["all", "motor"],
        "reref": ["none", "car"],
        "use_csp": [False, True],
    }
    pool = []
    for crop in space["crop_sec"]:
        for rej in space["reject_uv"]:
            for chs in space["channel_set"]:
                for ref in space["reref"]:
                    for csp in space["use_csp"]:
                        pool.append({
                            "crop_sec": list(crop), "reject_uv": rej,
                            "channel_set": chs, "reref": ref, "use_csp": csp,
                            "model": "lda", "cv_folds": 5,
                            "cv_scheme": "within_subject",
                        })
    return space, pool


SEARCH_SPACE, CONFIG_POOL = _build_search_space()


def preprocess_key(cfg: dict) -> str:
    """预处理部分的键——决定需要算几份 clean/feat 表示。"""
    return json.dumps(
        {k: cfg[k] for k in ("crop_sec", "reject_uv", "channel_set", "reref")},
        sort_keys=True,
    )


def distinct_preprocess_keys(pool: list[dict] | None = None) -> list[str]:
    return sorted({preprocess_key(c) for c in (pool or CONFIG_POOL)})


def neighbors(cfg: dict, space: dict | None = None) -> list[dict]:
    """只差一个参数的相邻配置——爬山法用。"""
    space = space or SEARCH_SPACE
    out = []
    for key, values in space.items():
        cur = cfg.get(key)
        for v in values:
            if v != cur:
                n = dict(cfg)
                n[key] = list(v) if isinstance(v, list) else v
                out.append(n)
    return out


# ------------------------------------------------------------------ 试验台
class Testbed:
    """在一组零信号孪生体上跑搜索，统计虚报率。

    分层说明（重要，写清楚免得日后自己糊涂）：

    - **raw 层**的孪生体（`make_twin`）是给真人 agent 用的，它需要是一个
      可以被 `eeg_fetch` 下游照常消费的普通 raw 产物。
    - **表示层**的孪生体（`rewind_labels`）是给程序化搜索用的，它直接从
      预计算好的 clean/feat 表示重贴标签，省掉重算。

    两者用同一个 seed，但置换发生在不同的层（raw 的 N 个试次 vs clean 的
    N−被剔 个试次），所以**不保证逐试次一致**。它们是同一个零假设下的两次
    独立合法抽样，统计上等价——程序化实验只需要这一点。若日后要求两者
    逐试次对齐，需要让 `preprocess` 暴露剔除掩码索引。
    """

    def __init__(self, source_raw: str, root: str | Path | None = None, *,
                 source_root: str | Path | None = None):
        """root=None 表示产物落进**当前 cache 根**（与常规产物同处一地）。

        什么时候该传 root：
        - **agent 当实验员**（跑零信号对照）—— 传 None。它本来就知道自己在
          做什么，不需要隔离；而且产物必须在常规根里，`eeg_evidence` /
          `eeg_defect_rate` 才找得到它们。
        - **agent 当被试**（测它面对零信号的自然反应）—— 由外部把
          `EEG_ARTIFACT_DIR` 整个指到一个**只装孪生体**的目录，真品从不进入，
          它就没有可对照的 handle。这种情况不该由本类处理，见 check_blinding.py。
        """
        self.source_raw = source_raw
        # 传给 cache_root_at 的值：None = 不改环境变量，用当前根
        self._env_root = Path(root) if root is not None else None
        # 自己的簿记文件（表示映射、零分布池）放哪
        self.dir = Path(root) if root is not None else _bookkeeping_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._source_root = source_root
        self._clean: dict[str, str] = {}
        self._feat: dict[str, str] = {}
        self._staged: str | None = None

    # ---------------------------------------------------------- 表示缓存
    def _prepared_path(self) -> Path:
        """把「预处理组合 → 表示 handle」的映射存下来。

        产物是内容寻址的、永不改变，所以这份映射一旦写下就永久有效。
        没有它，每次工具调用都要重算 36 个组合（约 30 秒），agent 跑几十次
        试验就白白多花半小时。
        """
        return self.dir / f"prepared_{self.source_raw}.json"

    def _load_prepared(self) -> bool:
        p = self._prepared_path()
        if not p.exists():
            return False
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return False
        with cache_root_at(self._env_root):
            for k, v in (d.get("clean") or {}).items():
                if not cache.exists(v):
                    return False
                self._clean[k] = v
            for k, v in (d.get("feat") or {}).items():
                if not cache.exists(v):
                    return False
                self._feat[k] = v
        return bool(self._clean)

    def _save_prepared(self) -> None:
        self._prepared_path().write_text(
            json.dumps({"source_raw": self.source_raw, "clean": self._clean,
                        "feat": self._feat},
                       ensure_ascii=False, indent=1),
            encoding="utf-8",
        )

    # ---------------------------------------------------------- 准备
    def stage(self) -> str:
        """把源 raw 复制进本试验台的目录（确定性 → 同一个 handle）。"""
        if self._staged:
            return self._staged
        import eeg_pipeline as pipe  # 延迟导入，避免与 pipeline 循环依赖
        with cache_root_at(self._source_root):
            arrays, record = cache.get(self.source_raw)
        with cache_root_at(self._env_root):
            self._staged = cache.put(
                "raw", {k: arrays[k] for k in ("X", "y", "subject_ids")},
                dict(record["meta"]), parents=(), params=dict(record["params"]),
            )
        if self._staged != self.source_raw:
            raise RuntimeError(
                f"复制源产物得到 {self._staged}，与源 {self.source_raw} 不同——"
                "说明代码版本已变，旧证据失效，必须先查清再继续。"
            )
        return self._staged

    def prepare(self, pool: list[dict] | None = None) -> None:
        """对每个预处理组合算一次 clean/feat 表示。这是唯一的重活，只做一次。"""
        import eeg_pipeline as pipe
        if self._load_prepared():
            return
        raw = self.stage()
        keys = distinct_preprocess_keys(pool)
        by_key = {}
        for cfg in (pool or CONFIG_POOL):
            by_key.setdefault(preprocess_key(cfg), cfg)

        with cache_root_at(self._env_root):
            for k in keys:
                cfg = by_key[k]
                clean = pipe.preprocess(
                    raw, crop_sec=cfg["crop_sec"], reject_uv=cfg["reject_uv"],
                    channel_set=cfg["channel_set"], reref=cfg["reref"],
                )
                self._clean[k] = clean
                self._feat[k] = pipe.features(clean, bands=["mu", "beta"])
        self._save_prepared()

    # ---------------------------------------------------------- 孪生体
    def twin_raw(self, seed: int) -> str:
        """raw 层孪生体 —— 给真人 agent 用。"""
        return make_twin(self.staged_or_source(), seed,
                         source_root=self._env_root, dest_root=self._env_root)

    def staged_or_source(self) -> str:
        return self._staged or self.source_raw

    def _representations(self, seed: int) -> tuple[dict, dict]:
        """把**全部**预计算表示重贴标签。搜索会横扫所有配置，所以需要全套。"""
        if not self._clean:
            raise RuntimeError("请先调用 prepare()")
        clean = {k: rewind_labels(h, seed, source_root=self._env_root, dest_root=self._env_root)
                 for k, h in self._clean.items()}
        feat = {k: rewind_labels(h, seed, source_root=self._env_root, dest_root=self._env_root)
                for k, h in self._feat.items()}
        return clean, feat

    def _representation_for(self, cfg: dict, seed: int) -> tuple[dict, dict]:
        """只重贴**这一个配置所需**的那一份表示。

        置换检验要跑几十次，每次只针对同一个配置。若沿用 `_representations`
        就会把 36 个组合全部重算一遍——10 次置换 × 36 组合 = 360 份产物，
        其中 359 份根本用不到。这是纯浪费，也让产物目录被垃圾淹没。
        """
        k = preprocess_key(cfg)
        return (
            {k: rewind_labels(self._clean[k], seed,
                              source_root=self._env_root, dest_root=self._env_root)},
            {k: rewind_labels(self._feat[k], seed,
                              source_root=self._env_root, dest_root=self._env_root)},
        )

    # ---------------------------------------------------------- 打分
    def score(self, cfg: dict, reps: tuple[dict, dict]) -> float:
        """在给定孪生体的标签下，评估一个配置。返回平衡准确率。"""
        import eeg_pipeline as pipe
        clean, feat = reps
        k = preprocess_key(cfg)
        with cache_root_at(self._env_root):
            if cfg["use_csp"]:
                ev = pipe.evaluate(clean[k], model=cfg["model"], use_csp=True,
                                   cv_folds=cfg["cv_folds"],
                                   cv_scheme=cfg["cv_scheme"])
            else:
                ev = pipe.evaluate(feat[k], model=cfg["model"], use_csp=False,
                                   cv_folds=cfg["cv_folds"],
                                   cv_scheme=cfg["cv_scheme"])
            return cache.describe(ev)["meta"]["metrics"]["balanced_accuracy_mean"]


# ------------------------------------------------------------------ 搜索策略
def _config_key(cfg: dict) -> str:
    return json.dumps(cfg, sort_keys=True)


def search_random(tb_, reps, pool, budget, rng) -> list[tuple[dict, float]]:
    """随机搜索：从池里不重复地抽 budget 个。"""
    idx = rng.choice(len(pool), size=min(budget, len(pool)), replace=False)
    return [(pool[int(i)], tb_.score(pool[int(i)], reps)) for i in idx]


def search_hill(tb_, reps, pool, budget, rng) -> list[tuple[dict, float]]:
    """爬山法：不会推理，但会朝高分方向走。

    ⚠️ 实测更正（16 次试验、配对比较）：在**零信号数据**上爬山法与随机搜索
    无可辨别的差别（mean(hill−random)=+0.0039, t=+0.46）。

    原因是零信号数据上所有配置的期望值都是 0.5、只有方差不同，**不存在
    「烂配置」**——没有结构可供自适应利用。早先「随机搜索天然偏低、只能当
    地板」的说法，前提是「有些配置系统性更差」，那是真实数据才有的性质。

    保留两种策略的价值在于：**两者接近本身就是结论**——偏差不依赖搜索的
    智能性，纯粹来自「取 B 次抽样的最大值」。
    """
    seen: dict[str, float] = {}
    history: list[tuple[dict, float]] = []
    cur = pool[int(rng.integers(len(pool)))]
    cur_score = tb_.score(cur, reps)
    seen[_config_key(cur)] = cur_score
    history.append((cur, cur_score))

    while len(history) < budget:
        cands = [c for c in neighbors(cur) if _config_key(c) not in seen]
        if not cands:
            break
        rng.shuffle(cands)
        improved = False
        for c in cands:
            if len(history) >= budget:
                break
            s = tb_.score(c, reps)
            seen[_config_key(c)] = s
            history.append((c, s))
            if s > cur_score:
                cur, cur_score = c, s
                improved = True
                break
        if not improved:
            # 局部最优：随机重启，否则每次爬山都会卡在同一个坑里
            left = [c for c in pool if _config_key(c) not in seen]
            if not left:
                break
            cur = left[int(rng.integers(len(left)))]
            cur_score = tb_.score(cur, reps)
            seen[_config_key(cur)] = cur_score
            history.append((cur, cur_score))
    return history


SEARCHERS = {"random": search_random, "hill": search_hill}


# ------------------------------------------------------------------ 零分布池
def _pool_path(root: Path, source_raw: str) -> Path:
    return Path(root) / f"nullpool_{source_raw}.json"


def null_pool(tb_: "Testbed", cfg: dict, *, n_perm: int = 30,
              seed_base: int = 500_000, source_raw: str | None = None) -> np.ndarray:
    """某个配置在零信号下的置换零分布。

    **关键性质：这份分布与具体哪个孪生体无关。**
    被置换过的标签再打乱，仍然是均匀置换，所以配置 c 的零分布只依赖
    「数据 X」和「配置 c」，不依赖手上这份标签是哪一次抽样。

    因此它全局只需算一次，然后所有孪生体共用——这正是 N 能取到 100 的原因。
    没有这条性质，每个孪生都要为它选中的配置重算 30 次置换。

    结果落地缓存（产物不可变，映射永久有效）。
    """
    src = source_raw or tb_.source_raw
    path = _pool_path(tb_.dir, src)
    cache_store: dict = {}
    if path.exists():
        try:
            cache_store = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cache_store = {}

    key = json.dumps(cfg, sort_keys=True)
    if key in cache_store and len(cache_store[key]) >= n_perm:
        return np.array(cache_store[key][:n_perm], dtype=float)

    vals = []
    for i in range(n_perm):
        reps = tb_._representation_for(cfg, seed_base + i)   # 只重建该配置需要的那份
        vals.append(tb_.score(cfg, reps))

    cache_store[key] = [round(float(v), 6) for v in vals]
    path.write_text(json.dumps(cache_store, ensure_ascii=False), encoding="utf-8")
    return np.array(vals, dtype=float)


def emulate_p_value(observed: float, pool: np.ndarray) -> float:
    """复现 agent 当年的判定方式：p = (超过观测的置换数 + 1) / (n + 1)。"""
    return float((np.sum(pool >= observed) + 1) / (len(pool) + 1))


# ------------------------------------------------------------------ 单次试验
def run_trial(source_raw: str, seed: int, *, root: str | Path | None = None,
              strategy: str = "hill", budget: int = 24,
              n_perm: int = 30, source_root: str | Path | None = None,
              alpha: float = 0.05) -> dict:
    """在一个零信号孪生体上跑一次完整搜索，返回这次试验的结果。

    复现的是**当年发生在真人 agent 身上的那套流程**：
        搜索 → 选中一个配置 → 在该配置上做置换检验 → 若 p < α 就"发现了显著效应"

    在这里，数据里没有任何信号，所以每一次"发现"都是虚报。
    """
    T = Testbed(source_raw, root, source_root=source_root)
    T.prepare()
    reps = T._representations(seed)
    res = search(T, reps, CONFIG_POOL, budget, strategy, seed=seed)

    pool = null_pool(T, res["chosen_config"], n_perm=n_perm,
                     seed_base=900_000 + seed * 1000, source_raw=source_raw)
    p = emulate_p_value(res["observed"], pool)

    res.update({
        "twin_seed": int(seed),
        "source_raw": source_raw,
        "p_value": round(p, 4),
        "null_mean": round(float(pool.mean()), 4),
        "null_std": round(float(pool.std(ddof=1)), 4),
        "null_max": round(float(pool.max()), 4),
        "n_perm": int(n_perm),
        "significant": bool(p < alpha),
        "alpha": float(alpha),
    })

    # 落成 eval 产物：这样这些数字进入既有证据体系，可被 eeg_evidence 引用，
    # 也能被 eeg_defect_rate 按 handle 汇总。沿用 eval 这个 kind，
    # 因为一次试验本就是一次评估——不新增 kind，避免动 eeg_cache.py。
    twin = make_twin(source_raw, seed, source_root=source_root,
                     dest_root=T._env_root)
    with cache_root_at(T._env_root):
        res["twin_handle"] = twin
        res["artifact"] = cache.put(
            "eval",
            {"null_distribution": pool.astype(np.float32)},
            {
                "scheme": "zero_signal_trial",
                "observed_balanced_accuracy": res["observed"],
                "p_value": res["p_value"],
                "metrics": {"balanced_accuracy_mean": res["observed"],
                            "chance_level": 0.5},
                "config": {"chosen_config": res["chosen_config"],
                           "strategy": strategy, "budget": budget,
                           "twin_seed": int(seed), "n_perm": int(n_perm)},
                "rank_of_chosen": res["rank_of_chosen"],
                "significant": res["significant"],
                "is_synthetic": False,
                "source_handle": twin,
            },
            parents=[twin],
            params={"scheme": "zero_signal_trial", "strategy": strategy,
                    "budget": budget, "seed": int(seed), "n_perm": int(n_perm)},
        )
    return res


# ------------------------------------------------------------------ 汇总
def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """比例的 Wilson 置信区间——小样本下比正态近似可靠。"""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - h) / d, 4), round((c + h) / d, 4))


def defect_rate(trials: list[dict], *, alpha: float = 0.05) -> dict:
    """把若干次试验汇总成虚报率。

    「虚报率」= 在零信号数据上，这套流程报出「显著」的比例。
    所有"发现"都必然是假的——因为根本没有信号可被发现。
    """
    n = len(trials)
    k = sum(1 for t in trials if t["p_value"] < alpha)
    ps = sorted(t["p_value"] for t in trials)
    p = k / n if n else 0.0
    return {
        "n_trials": n,
        "n_significant": k,
        "defect_rate": round(p, 4),
        "wilson_ci95": list(wilson_ci(k, n)),
        "alpha": alpha,
        "p_values": ps,
        "median_p": round(float(np.median(ps)), 4) if ps else None,
        "rank_of_chosen": [t["rank_of_chosen"] for t in trials],
        "observations": [t["observed"] for t in trials],
        "analytical_note": (
            "若所有配置的零分布相同、搜索又是可交换抽样，虚报率的理论值约为 "
            "B/(B+n_perm)——B 为搜索预算。实际值偏离它，说明配置异质或搜索是"
            "自适应的。这个对照用来判断偏差是否只是'选择'造成的。"
        ),
    }


def analytical_baseline(budget: int, n_perm: int) -> float:
    """B/(B+n_perm)：可交换零假设下的虚报率理论值。

    推导：搜索取 B 次抽样的最大值，置换检验拿它与同一分布下的 n_perm 次
    抽样比较。「B 次抽样的最大值超过那 n_perm 次」等价于「全部 B+n_perm 次
    抽样中最大的那次落在前 B 次里」，概率即 B/(B+n_perm)。

    这是**必须有**的一条对照线：若实测值远高于它，说明偏差不只是"选择"，
    还有配置异质或自适应搜索的额外贡献；若接近，则偏差完全可由选择解释。
    """
    return round(budget / (budget + n_perm), 4)


def search(tb_, reps, pool, budget: int, strategy: str = "hill", seed: int = 0):
    if strategy not in SEARCHERS:
        raise ValueError(f"未知 strategy {strategy!r}。可用：{sorted(SEARCHERS)}")
    rng = np.random.default_rng(seed)
    history = SEARCHERS[strategy](tb_, reps, pool, budget, rng)
    best_cfg, best_score = max(history, key=lambda kv: kv[1])
    rank = sorted((s for _, s in history), reverse=True).index(best_score) + 1
    return {
        "strategy": strategy,
        "n_evaluated": len(history),
        "chosen_config": best_cfg,
        "observed": best_score,
        "rank_of_chosen": rank,
        "all_scores": [round(s, 4) for _, s in history],
    }
