from __future__ import annotations

import random
from pathlib import Path

from petcore.config import Config
from petcore.contracts.content import AnimationSpec
from petcore.engine.catalog import GraphCatalog
from petcore.engine.enums import AnimatType, GraphType
from petcore.engine.head_pat import (
    HEAD_PAT_ALL_MODE,
    HEAD_PAT_CUSTOM_MODE,
    HEAD_PAT_DEFAULT_MODE,
    HeadPatTracker,
    choose_head_pat_spec,
    head_pat_specs,
)


def _spec(name: str, graph: GraphType, animat: AnimatType = AnimatType.SINGLE) -> AnimationSpec:
    return AnimationSpec(name=name, graph=graph, animat=animat)


def _gesture(tracker: HeadPatTracker, points: list[tuple[float, float]], times: list[float]) -> bool:
    result = False
    for point, now in zip(points, times, strict=True):
        result = tracker.update(point, inside_head=True, now=now, eligible=True) or result
    return result


def test_head_pat_straight_motion_does_not_trigger() -> None:
    tracker = HeadPatTracker()
    assert not _gesture(
        tracker,
        [(10, 10), (15, 10), (20, 10), (25, 10), (30, 10)],
        [0.0, 0.1, 0.2, 0.3, 0.4],
    )


def test_head_pat_back_and_forth_triggers_after_distance_and_reversal() -> None:
    tracker = HeadPatTracker()
    assert _gesture(
        tracker,
        [(10, 10), (17, 10), (10, 10), (17, 10)],
        [0.0, 0.1, 0.2, 0.3],
    )


def test_head_pat_requires_minimum_distance() -> None:
    tracker = HeadPatTracker()
    assert not _gesture(
        tracker,
        [(10, 10), (13, 10), (10, 10), (13, 10)],
        [0.0, 0.1, 0.2, 0.3],
    )


def test_head_pat_leaving_head_resets_path() -> None:
    tracker = HeadPatTracker()
    tracker.update((10, 10), inside_head=True, now=0.0, eligible=True)
    tracker.update((17, 10), inside_head=True, now=0.1, eligible=True)
    assert not tracker.update((17, 10), inside_head=False, now=0.2, eligible=True)
    assert not tracker.update((10, 10), inside_head=True, now=0.3, eligible=True)
    assert not tracker.update((17, 10), inside_head=True, now=0.4, eligible=True)


def test_head_pat_cooldown_and_path_age_are_injected_time_based() -> None:
    tracker = HeadPatTracker()
    assert _gesture(
        tracker,
        [(10, 10), (17, 10), (10, 10), (17, 10)],
        [0.0, 0.1, 0.2, 0.3],
    )
    assert not _gesture(
        tracker,
        [(10, 10), (17, 10), (10, 10), (17, 10)],
        [0.4, 0.5, 0.6, 0.7],
    )
    assert not _gesture(
        HeadPatTracker(),
        [(10, 10), (17, 10), (10, 10), (17, 10)],
        [0.0, 0.1, 1.5, 1.6],
    )


def test_head_pat_animation_modes_filter_invalid_and_loop_specs() -> None:
    catalog = GraphCatalog(
        [
            _spec("点击", GraphType.TOUCH_BODY),
            _spec("摸头", GraphType.TOUCH_HEAD),
            _spec("说话", GraphType.SAY),
            _spec("待机", GraphType.IDEL, AnimatType.B_LOOP),
            _spec("事件", GraphType.EVENT),
            _spec("拖拽", GraphType.RAISED_DYNAMIC),
            _spec("循环", GraphType.WORK, AnimatType.B_LOOP),
        ]
    )

    assert [spec.name for spec in head_pat_specs(catalog)] == ["点击"]
    assert [spec.name for spec in head_pat_specs(catalog, mode=HEAD_PAT_ALL_MODE)] == [
        "点击",
        "摸头",
        "说话",
    ]
    assert [
        spec.name
        for spec in head_pat_specs(
            catalog, mode=HEAD_PAT_CUSTOM_MODE, names=["摸头", "不存在", "摸头"]
        )
    ] == ["摸头"]


def test_head_pat_selection_avoids_immediate_repeat_when_possible() -> None:
    specs = (_spec("a", GraphType.SAY), _spec("b", GraphType.WORK))
    chosen = choose_head_pat_spec(specs, rng=random.Random(1), previous_name="a")
    assert chosen is not None
    assert chosen.name == "b"
    assert choose_head_pat_spec((), rng=random.Random()) is None


def test_head_pat_config_defaults_and_normalization(tmp_path: Path) -> None:
    config = Config(
        tmp_path,
        {
            "head_pat_enabled": "no",
            "head_pat_animation_mode": "not-a-mode",
            "head_pat_animation_names": [" click ", "click", 3, ""],
        },
    )
    assert config.get("head_pat_enabled") is True
    assert config.get("head_pat_animation_mode") == HEAD_PAT_DEFAULT_MODE
    assert config.get("head_pat_animation_names") == ["click"]

    defaults = Config(tmp_path / "defaults")
    assert defaults.get("head_pat_enabled") is True
    assert defaults.get("head_pat_animation_mode") == HEAD_PAT_DEFAULT_MODE
    assert defaults.get("head_pat_animation_names") == []
