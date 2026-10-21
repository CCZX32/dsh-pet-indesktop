from __future__ import annotations

import random

from petcore.contracts.content import AnimationSpec
from petcore.engine.animation import AnimationPlayer
from petcore.engine.catalog import GraphCatalog
from petcore.engine.enums import AnimatType, GraphType, ModeType


def _spec(
    name: str,
    animat: AnimatType,
    *,
    graph: GraphType = GraphType.DEFAULT,
    mode: ModeType = ModeType.NOMAL,
    loop: bool = False,
) -> AnimationSpec:
    return AnimationSpec(name=name, graph=graph, animat=animat, mode=mode, loop=loop)


def _player(specs, seed: int = 0) -> AnimationPlayer:
    return AnimationPlayer(GraphCatalog(specs, rng=random.Random(seed)))


def _wave_specs() -> list[AnimationSpec]:
    return [
        _spec("wave", AnimatType.A_START),
        _spec("wave", AnimatType.B_LOOP),
        _spec("wave", AnimatType.C_END),
    ]


# ---------------------------------------------------------------- single animations


def test_single_animation_has_no_follow_up():
    player = _player([_spec("click", AnimatType.SINGLE, graph=GraphType.TOUCH_BODY)])
    spec = player.play(name="click")
    assert spec is not None
    assert spec.animat is AnimatType.SINGLE
    assert player.current is spec
    assert player.advance() is None
    assert player.current is None
    assert player.advance() is None


# ---------------------------------------------------------------- start/loop/end chains


def test_a_start_advances_through_b_loop_to_c_end():
    player = _player(_wave_specs())
    started = player.play(name="wave", animat=AnimatType.A_START)
    assert started is not None
    assert started.animat is AnimatType.A_START

    loop = player.advance()
    assert loop is not None
    assert loop.animat is AnimatType.B_LOOP
    assert player.current is loop

    end = player.advance()
    assert end is not None
    assert end.animat is AnimatType.C_END
    assert player.current is end

    assert player.advance() is None
    assert player.current is None


def test_a_start_prefers_b_loop_over_c_end():
    player = _player(_wave_specs())
    player.play(name="wave", animat=AnimatType.A_START)
    assert player.advance().animat is AnimatType.B_LOOP


def test_b_loop_with_loop_flag_restarts_the_same_spec():
    specs = [_spec("idle", AnimatType.B_LOOP, graph=GraphType.IDEL, loop=True)]
    player = _player(specs)
    loop = player.play(name="idle", animat=AnimatType.B_LOOP)
    assert loop is not None

    for _ in range(3):
        assert player.advance() is loop
        assert player.current is loop


def test_b_loop_without_loop_flag_moves_to_c_end():
    player = _player(_wave_specs())
    loop = player.play(name="wave", animat=AnimatType.B_LOOP)
    assert loop is not None
    end = player.advance()
    assert end is not None
    assert end.animat is AnimatType.C_END


def test_missing_b_loop_falls_back_to_c_end():
    player = _player(
        [
            _spec("wave", AnimatType.A_START),
            _spec("wave", AnimatType.C_END),
        ]
    )
    assert player.play(name="wave", animat=AnimatType.A_START) is not None
    end = player.advance()
    assert end is not None
    assert end.animat is AnimatType.C_END


def test_missing_b_loop_and_c_end_ends_the_chain():
    player = _player([_spec("wave", AnimatType.A_START)])
    assert player.play(name="wave", animat=AnimatType.A_START) is not None
    assert player.advance() is None
    assert player.current is None


def test_c_end_has_no_follow_up():
    player = _player(_wave_specs())
    assert player.play(name="wave", animat=AnimatType.C_END) is not None
    assert player.advance() is None
    assert player.current is None


# ---------------------------------------------------------------- play selectors


def test_play_by_name_prefers_single_then_loop():
    player = _player(
        [
            _spec("mixed", AnimatType.A_START),
            _spec("mixed", AnimatType.B_LOOP),
            _spec("mixed", AnimatType.C_END),
        ]
    )
    first = player.play(name="mixed")
    assert first is not None
    assert first.animat is AnimatType.B_LOOP

    with_single = _player(
        [
            _spec("mixed", AnimatType.B_LOOP),
            _spec("mixed", AnimatType.C_END),
            _spec("mixed", AnimatType.SINGLE),
        ]
    )
    exact = with_single.play(name="mixed")
    assert exact is not None
    assert exact.animat is AnimatType.SINGLE


def test_play_by_name_and_animat_uses_the_exact_animat():
    player = _player(_wave_specs())
    spec = player.play(name="wave", animat=AnimatType.C_END)
    assert spec is not None
    assert spec.animat is AnimatType.C_END


def test_play_by_graph_uses_the_graph_catalog():
    player = _player(
        [
            _spec("idle", AnimatType.B_LOOP, graph=GraphType.IDEL),
            _spec("wave", AnimatType.B_LOOP, graph=GraphType.DEFAULT),
        ]
    )
    spec = player.play(GraphType.IDEL, animat=AnimatType.B_LOOP)
    assert spec is not None
    assert spec.name == "idle"
    assert spec.graph is GraphType.IDEL


def test_play_by_graph_requires_an_animat():
    player = _player([_spec("idle", AnimatType.B_LOOP, graph=GraphType.IDEL)])
    assert player.play(GraphType.IDEL) is None
    assert player.current is None


def test_play_without_selector_or_unknown_name_returns_none():
    player = _player(_wave_specs())
    assert player.play() is None
    assert player.play(name="missing") is None
    assert player.play(name="wave", animat=AnimatType.SINGLE) is None
    assert player.play(GraphType.SAY, animat=AnimatType.SINGLE) is None
    assert player.current is None


def test_advance_without_a_current_animation_returns_none():
    player = _player(_wave_specs())
    assert player.advance() is None
    assert player.current is None


# ---------------------------------------------------------------- mode propagation


def test_advance_keeps_the_mode_of_the_started_animation():
    specs = [
        _spec("mood", AnimatType.A_START, mode=ModeType.HAPPY),
        _spec("mood", AnimatType.B_LOOP, mode=ModeType.NOMAL),
        _spec("mood", AnimatType.B_LOOP, mode=ModeType.HAPPY),
        _spec("mood", AnimatType.C_END, mode=ModeType.HAPPY),
    ]
    player = _player(specs)
    started = player.play(name="mood", animat=AnimatType.A_START, mode=ModeType.HAPPY)
    assert started is not None
    assert started.mode is ModeType.HAPPY
    loop = player.advance()
    assert loop is not None
    assert loop.animat is AnimatType.B_LOOP
    assert loop.mode is ModeType.HAPPY


def test_play_by_graph_honours_the_requested_mode():
    specs = [
        _spec("idle", AnimatType.B_LOOP, graph=GraphType.IDEL, mode=ModeType.NOMAL),
        _spec("idle", AnimatType.B_LOOP, graph=GraphType.IDEL, mode=ModeType.POOR_CONDITION),
    ]
    player = _player(specs)
    spec = player.play(GraphType.IDEL, animat=AnimatType.B_LOOP, mode=ModeType.POOR_CONDITION)
    assert spec is not None
    assert spec.mode is ModeType.POOR_CONDITION


# ---------------------------------------------------------------- reset


def test_reset_clears_the_current_animation():
    player = _player(_wave_specs())
    assert player.play(name="wave", animat=AnimatType.A_START) is not None
    player.reset()
    assert player.current is None
    assert player.advance() is None
