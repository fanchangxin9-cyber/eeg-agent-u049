"""标签家族守卫的测试（SEC-003）。

为什么这一组最重要
------------------
`tools/eeg_dataset.py:21` 的模块文档写着一句很重的话：

> **把不同家族混在一起会让标签静默变成错的。**

EEGMMIDB 里 T1/T2 的含义**随 run 家族变化**：

| runs | 家族 | T1 | T2 |
|---|---|---|---|
| 3 / 7 / 11 | hands_execution | 实际左手 | 实际右手 |
| 4 / 8 / 12 | hands_imagery | **想象**左手 | **想象**右手 |
| 5 / 9 / 13 | feet_execution | 实际双手 | 实际双脚 |
| 6 / 10 / 14 | feet_imagery | **想象**双手 | **想象**双脚 |

也就是说：混用家族**不会报错**，只会让标签**静默变成另一个意思**——
这是「数字全真、结论全假」的另一种形态，正是本项目最在意的那类失败。

而在这个测试文件出现之前，守卫它的 `resolve_task` / `family_of_runs`
**一条测试都没有**（全仓库机械统计：两者从未在 `tests/` 中出现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import eeg_dataset as ds


# ---------------------------------------------------------------- 家族表本身
def test_每个_run_只属于一个家族():
    """家族表必须**两两不相交**——这是「混用即错标」这条守卫的结构前提。

    一旦有人往两个家族里写了同一个 run 号，这条会立刻失败。
    """
    seen: dict[int, str] = {}
    for fam, runs in ds._FAMILY.items():
        for r in runs:
            assert r not in seen, f"run {r} 同时属于 {seen[r]} 与 {fam}"
            seen[r] = fam


def test_家族表覆盖任务表():
    """`TASKS` 里每个任务的 family 与 runs 都要与 `_FAMILY` 对得上。"""
    for name, info in ds.TASKS.items():
        fam = info["family"]
        assert fam in ds._FAMILY, f"任务 {name} 的 family {fam!r} 不在 _FAMILY 里"
        assert set(info["runs"]) <= set(ds._FAMILY[fam]), (
            f"任务 {name} 的 runs {info['runs']} 与家族 {fam} 的 "
            f"{ds._FAMILY[fam]} 不一致"
        )


def test_同一个_run_号在不同家族里意味着不同的标签():
    """把「为什么不能混」钉成一条可读的断言。

    run 4 与 run 6 都产出 T1/T2，但 T1 一个是「想象左手」、一个是「想象双手」。
    混在一起 → 标签静默变成错的。
    """
    left_right = ds.TASKS["left_vs_right_imagery"]
    fists_feet = ds.TASKS["fists_vs_feet_imagery"]
    assert left_right["label_names"] != fists_feet["label_names"]
    assert not (set(left_right["runs"]) & set(fists_feet["runs"])), (
        "两个任务的 run 集合不应有交集——否则无法从 run 推断任务"
    )


# ---------------------------------------------------------------- family_of_runs
def test_单一家族能识别():
    assert ds.family_of_runs([4, 8, 12]) == "hands_imagery"
    assert ds.family_of_runs([3]) == "hands_execution"
    assert ds.family_of_runs([6, 10, 14]) == "feet_imagery"


def test_跨家族或未知返回_None():
    assert ds.family_of_runs([4, 6]) is None      # 两个家族各占一个
    assert ds.family_of_runs([3, 4]) is None
    assert ds.family_of_runs([99]) is None        # 不属于任何家族
    assert ds.family_of_runs([]) is None          # 空


# ---------------------------------------------------------------- resolve_task
def test_只给_runs_能解析出任务():
    task, info = ds.resolve_task([4, 8, 12], None)
    assert task == "left_vs_right_imagery"
    assert info["family"] == "hands_imagery"


def test_什么都不给走默认任务():
    task, info = ds.resolve_task(None, None)
    assert task == ds.DEFAULT_TASK
    assert info is ds.TASKS[ds.DEFAULT_TASK]


@pytest.mark.parametrize("runs", [
    [4, 6],           # 想象左右手 + 想象双手/双脚
    [3, 4],           # 实际左右手 + 想象左右手
    [3, 7, 11, 4],    # 整个家族 + 另一家族的一个
    [99],             # 未知 run
    [],               # 空列表
])
def test_跨家族或未知的_runs_必须被拒(runs):
    """这是本文件存在的理由：混用必须**响亮失败**，不能静默继续。"""
    with pytest.raises(ValueError, match="家族"):
        ds.resolve_task(runs, None)


def test_任务名与_runs_不匹配必须被拒():
    """显式点名任务时，runs 也必须属于该任务——否则标签含义同样会错。"""
    with pytest.raises(ValueError, match="请只使用该任务的 run"):
        ds.resolve_task([4, 8, 12], "fists_vs_feet_imagery")


def test_未知任务名必须被拒():
    with pytest.raises(ValueError, match="未知任务"):
        ds.task_info("这个任务不存在")
    with pytest.raises(ValueError, match="未知任务"):
        ds.resolve_task(None, "这个任务不存在")


def test_点名任务且_runs_匹配时通过():
    task, info = ds.resolve_task([4, 8, 12], "left_vs_right_imagery")
    assert task == "left_vs_right_imagery"
    assert info["label_names"] == ["left_fist", "right_fist"]
