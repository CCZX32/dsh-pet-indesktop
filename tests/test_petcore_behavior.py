from __future__ import annotations

import random
from collections import Counter
from dataclasses import FrozenInstanceError

import pytest

from petcore.contracts.content import AnimationSpec
from petcore.engine.behavior import (
    DEFAULT_WEIGHTS,
    KIND_ACT,
    KIND_IDLE,
    KIND_MOVE,
    KIND_TURN,
    Action,
    BehaviorDirector,
    normalize_weights,
)
from petcore.engine.catalog import GraphCatalog
from petcore.engine.enums import AnimatType, GraphType, ModeType


def _spec(
    name: str,
    graph: GraphType,
    animat: AnimatType,
    locate: str = "ground",
) -> AnimationSpec:
    return AnimationSpec(name=name, graph=graph, animat=animat, locate=locate)


def _full_specs() -> list[AnimationSpec]:
    return [
        _spec("idle_a", GraphType.IDEL, AnimatType.B_LOOP),
        _spec("turn_left", GraphType.MOVE, AnimatType.B_LOOP, "in_place"),
        _spec("turn_right", GraphType.MOVE, AnimatType.B_LOOP, "in_place"),
        _spec("walk", GraphType.MOVE, AnimatType.B_LOOP),
        _spec("run", GraphType.MOVE, AnimatType.B_LOOP),
        _spec("wave", GraphType.DEFAULT, AnimatType.SINGLE),
    ]


def _director(specs, seed: int = 0) -> BehaviorDirector:
    catalog = GraphCatalog(specs, rng=random.Random(seed))
    return BehaviorDirector(catalog, rng=random.Random(seed))


def _choose_many(director: BehaviorDirector, count: int = 1000) -> list[Action]:
    actions = []
    for _ in range(count):
        action = director.choose()
        assert action is not None
        actions.append(action)
    return actions


# ---------------------------------------------------------------- weighted choice


def test_choose_matches_the_weight_bands():
    actions = _choose_many(_director(_full_specs(), seed=0), count=1000)
    counts = Counter(action.kind for action in actions)

    assert set(counts) == {KIND_IDLE, KIND_TURN, KIND_ACT, KIND_MOVE}
    assert sum(counts.values()) == 1000
    assert 230 <= counts[KIND_IDLE] <= 370, counts
    assert 60 <= counts[KIND_TURN] <= 140, counts
    assert 380 <= counts[KIND_ACT] <= 520, counts
    assert 160 <= counts[KIND_MOVE] <= 240, counts


def test_choose_is_reproducible_with_a_seeded_rng():
    first = _choose_many(_director(_full_specs(), seed=11), count=200)
    second = _choose_many(_director(_full_specs(), seed=11), count=200)
    assert [action.kind for action in first] == [action.kind for action in second]
    assert [action.spec.name for action in first] == [action.spec.name for action in second]


def test_director_defaults_to_the_catalog_rng():
    catalog = GraphCatalog(_full_specs(), rng=random.Random(0))
    director = BehaviorDirector(catalog)
    assert director.rng is catalog.rng


def test_choose_returns_specs_from_the_catalog():
    director = _director(_full_specs(), seed=0)
    catalog_specs = set(director.catalog.animations)
    for action in _choose_many(director, count=100):
        assert action.spec in catalog_specs


# ---------------------------------------------------------------- category factories


def test_idle_uses_the_idle_graph_loop():
    action = _director(_full_specs()).idle()
    assert action is not None
    assert action.kind == KIND_IDLE
    assert action.spec.graph is GraphType.IDEL
    assert action.spec.animat is AnimatType.B_LOOP


def test_act_uses_a_default_single():
    action = _director(_full_specs()).act()
    assert action is not None
    assert action.kind == KIND_ACT
    assert action.spec.graph is GraphType.DEFAULT
    assert action.spec.animat is AnimatType.SINGLE


def test_turn_only_picks_in_place_move_specs():
    director = _director(_full_specs(), seed=2)
    names = set()
    for _ in range(100):
        action = director.turn()
        assert action is not None
        assert action.kind == KIND_TURN
        assert action.spec.locate == "in_place"
        assert action.spec.graph is GraphType.MOVE
        names.add(action.spec.name)
    assert names == {"turn_left", "turn_right"}


def test_move_only_picks_ground_move_specs():
    director = _director(_full_specs(), seed=2)
    names = set()
    for _ in range(100):
        action = director.move()
        assert action is not None
        assert action.kind == KIND_MOVE
        assert action.spec.locate == "ground"
        assert action.spec.locate != "in_place"
        assert action.spec.graph is GraphType.MOVE
        names.add(action.spec.name)
    assert names == {"walk", "run"}


def test_turn_and_move_partition_the_move_graph():
    director = _director(_full_specs())
    move_specs = set(director.catalog.specs_for(GraphType.MOVE))
    turn_specs = {spec for spec in move_specs if spec.locate == "in_place"}
    ground_specs = {spec for spec in move_specs if spec.locate != "in_place"}
    assert turn_specs | ground_specs == move_specs
    assert turn_specs & ground_specs == set()


# ---------------------------------------------------------------- missing categories


def test_idle_requires_a_loop_in_the_idle_graph():
    assert _director([_spec("idle", GraphType.IDEL, AnimatType.SINGLE)]).idle() is None
    assert _director([]).idle() is None


def test_act_requires_a_single_in_the_default_graph():
    assert _director([_spec("wave", GraphType.DEFAULT, AnimatType.B_LOOP)]).act() is None


def test_turn_is_none_without_an_in_place_move():
    assert _director([_spec("walk", GraphType.MOVE, AnimatType.B_LOOP)]).turn() is None


def test_move_is_none_without_a_ground_move():
    assert (
        _director([_spec("turn", GraphType.MOVE, AnimatType.B_LOOP, "in_place")]).move() is None
    )


def test_choose_falls_back_to_idle_when_only_the_idle_category_exists():
    actions = _choose_many(_director([_spec("idle", GraphType.IDEL, AnimatType.B_LOOP)]))
    assert {action.kind for action in actions} == {KIND_IDLE}


def test_choose_falls_back_to_move_when_only_ground_moves_exist():
    actions = _choose_many(_director([_spec("walk", GraphType.MOVE, AnimatType.B_LOOP)]))
    assert {action.kind for action in actions} == {KIND_MOVE}


def test_choose_falls_back_to_act_when_only_default_singles_exist():
    actions = _choose_many(
        _director([_spec("wave", GraphType.DEFAULT, AnimatType.SINGLE)])
    )
    assert {action.kind for action in actions} == {KIND_ACT}


def test_choose_falls_back_to_turn_when_only_in_place_moves_exist():
    actions = _choose_many(
        _director([_spec("turn", GraphType.MOVE, AnimatType.B_LOOP, "in_place")])
    )
    assert {action.kind for action in actions} == {KIND_TURN}


def test_choose_never_returns_none_while_one_category_is_available():
    specs = [
        _spec("turn", GraphType.MOVE, AnimatType.B_LOOP, "in_place"),
        _spec("wave", GraphType.DEFAULT, AnimatType.SINGLE),
    ]
    actions = _choose_many(_director(specs, seed=4))
    assert {action.kind for action in actions} <= {KIND_TURN, KIND_ACT}


def test_choose_returns_none_only_for_an_empty_catalog():
    assert _director([]).choose() is None


def test_action_is_frozen_and_carries_its_spec():
    spec = _spec("idle", GraphType.IDEL, AnimatType.B_LOOP)
    action = Action(KIND_IDLE, spec)
    assert action.kind == KIND_IDLE
    assert action.spec is spec
    with pytest.raises(FrozenInstanceError):
        action.kind = KIND_MOVE


def test_mode_is_not_used_by_the_director_but_specs_keep_it():
    spec = AnimationSpec(
        name="idle",
        graph=GraphType.IDEL,
        animat=AnimatType.B_LOOP,
        mode=ModeType.HAPPY,
    )
    action = _director([spec]).idle()
    assert action is not None
    assert action.spec.mode is ModeType.HAPPY


# ---------------------------------------------------------------- weights


def test_default_weights_match_the_master_branch_bands():
    assert DEFAULT_WEIGHTS == (0.30, 0.10, 0.40, 0.20)


def test_normalize_weights_scales_to_one():
    assert normalize_weights(1, 1, 1, 1) == (0.25, 0.25, 0.25, 0.25)
    assert normalize_weights(30, 10, 40, 20) == DEFAULT_WEIGHTS


def test_normalize_weights_clamps_and_falls_back_to_defaults():
    assert normalize_weights(0, 0, 0, 0) == DEFAULT_WEIGHTS
    assert normalize_weights(-5, float("nan"), "bad", None) == DEFAULT_WEIGHTS
    assert normalize_weights(0, 0, 0, 10) == (0.0, 0.0, 0.0, 1.0)


def test_custom_weights_shift_the_dice_distribution():
    catalog = GraphCatalog(_full_specs(), rng=random.Random(3))
    director = BehaviorDirector(
        catalog, rng=random.Random(3), weights=(0, 0, 0, 100)
    )
    actions = _choose_many(director, count=200)
    assert {action.kind for action in actions} == {KIND_MOVE}


def test_weights_provider_is_read_on_every_roll():
    catalog = GraphCatalog(_full_specs(), rng=random.Random(5))
    weights = [0.0, 0.0, 0.0, 1.0]
    director = BehaviorDirector(
        catalog, rng=random.Random(5), weights_provider=lambda: tuple(weights)
    )
    assert director.weights == (0.0, 0.0, 0.0, 1.0)
    assert director.choose().kind == KIND_MOVE
    weights[:] = [0.0, 0.0, 1.0, 0.0]
    assert director.weights == (0.0, 0.0, 1.0, 0.0)
    assert director.choose().kind == KIND_ACT
