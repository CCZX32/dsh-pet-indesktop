from __future__ import annotations

import random
from pathlib import Path

from petcore.contracts.content import AnimationSpec
from petcore.engine.catalog import GraphCatalog
from petcore.engine.enums import AnimatType, GraphType, ModeType


def _spec(
    name: str = "idle",
    *,
    graph: GraphType = GraphType.IDEL,
    animat: AnimatType = AnimatType.B_LOOP,
    mode: ModeType = ModeType.NOMAL,
    path: Path | None = None,
) -> AnimationSpec:
    return AnimationSpec(name=name, graph=graph, animat=animat, mode=mode, path=path)


def _catalog(specs, seed: int = 0) -> GraphCatalog:
    return GraphCatalog(specs, rng=random.Random(seed))


# ---------------------------------------------------------------- mode resolution


def test_find_returns_exact_mode_when_present():
    catalog = _catalog([_spec(mode=mode) for mode in ModeType])
    for mode in ModeType:
        spec = catalog.find("idle", AnimatType.B_LOOP, mode)
        assert spec is not None
        assert spec.mode is mode


def test_mode_fallback_order_normal_and_happy():
    catalog = _catalog([_spec(mode=ModeType.NOMAL), _spec(mode=ModeType.POOR_CONDITION)])
    assert catalog.find("idle", AnimatType.B_LOOP, ModeType.HAPPY).mode is ModeType.NOMAL
    assert catalog.find("idle", AnimatType.B_LOOP, ModeType.NOMAL).mode is ModeType.NOMAL
    assert (
        catalog.find("idle", AnimatType.B_LOOP, ModeType.POOR_CONDITION).mode
        is ModeType.POOR_CONDITION
    )


def test_mode_fallback_order_happy_then_poor():
    happy_only = _catalog([_spec(mode=ModeType.HAPPY)])
    assert happy_only.find("idle", AnimatType.B_LOOP, ModeType.NOMAL).mode is ModeType.HAPPY
    assert (
        happy_only.find("idle", AnimatType.B_LOOP, ModeType.POOR_CONDITION).mode
        is ModeType.HAPPY
    )

    poor_only = _catalog([_spec(mode=ModeType.POOR_CONDITION)])
    assert (
        poor_only.find("idle", AnimatType.B_LOOP, ModeType.HAPPY).mode
        is ModeType.POOR_CONDITION
    )
    assert (
        poor_only.find("idle", AnimatType.B_LOOP, ModeType.NOMAL).mode
        is ModeType.POOR_CONDITION
    )


def test_ill_never_falls_back_to_other_modes():
    without_ill = _catalog([_spec(mode=ModeType.NOMAL), _spec(mode=ModeType.HAPPY)])
    assert without_ill.find("idle", AnimatType.B_LOOP, ModeType.ILL) is None

    with_ill = _catalog([_spec(mode=ModeType.NOMAL), _spec(mode=ModeType.ILL)])
    assert with_ill.find("idle", AnimatType.B_LOOP, ModeType.ILL).mode is ModeType.ILL


def test_find_uses_only_the_requested_animat():
    catalog = _catalog([_spec(animat=AnimatType.B_LOOP), _spec(animat=AnimatType.C_END)])
    assert catalog.find("idle", AnimatType.B_LOOP).animat is AnimatType.B_LOOP
    assert catalog.find("idle", AnimatType.C_END).animat is AnimatType.C_END
    assert catalog.find("idle", AnimatType.SINGLE) is None
    assert catalog.find("idle", AnimatType.A_START) is None


# ---------------------------------------------------------------- unknown lookups


def test_unknown_name_and_graph_return_none():
    catalog = _catalog([_spec(), _spec("wave", graph=GraphType.DEFAULT, animat=AnimatType.SINGLE)])
    assert catalog.find("missing", AnimatType.B_LOOP) is None
    assert catalog.find("idle", AnimatType.A_START) is None
    assert catalog.find_for(GraphType.SAY, AnimatType.B_LOOP) is None
    assert catalog.find_for(GraphType.SAY, AnimatType.SINGLE) is None
    assert catalog.find_name(GraphType.SAY) is None


def test_empty_catalog_answers_none():
    catalog = GraphCatalog(rng=random.Random(0))
    assert catalog.names() == ()
    assert catalog.names_for(GraphType.IDEL) == ()
    assert catalog.specs_for(GraphType.IDEL) == ()
    assert catalog.has("idle") is False
    assert catalog.find("idle", AnimatType.B_LOOP) is None
    assert catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP) is None
    assert catalog.find_name(GraphType.IDEL) is None


# ---------------------------------------------------------------- variant randomness


def test_variants_are_picked_randomly_with_seeded_rng():
    specs = [_spec(path=Path(f"idle_{index}.webm")) for index in range(4)]
    catalog = _catalog(specs, seed=7)
    seen = {catalog.find("idle", AnimatType.B_LOOP).path for _ in range(100)}
    assert seen == {Path(f"idle_{index}.webm") for index in range(4)}


def test_same_seed_reproduces_the_same_variant_sequence():
    specs = [_spec(path=Path(f"idle_{index}.webm")) for index in range(4)]
    left = _catalog(specs, seed=13)
    right = _catalog(specs, seed=13)
    assert [left.find("idle", AnimatType.B_LOOP).path for _ in range(20)] == [
        right.find("idle", AnimatType.B_LOOP).path for _ in range(20)
    ]


def test_variant_randomness_does_not_mix_modes():
    catalog = _catalog(
        [
            _spec(mode=ModeType.NOMAL, path=Path("n.webm")),
            _spec(mode=ModeType.HAPPY, path=Path("h.webm")),
        ],
        seed=3,
    )
    paths = {catalog.find("idle", AnimatType.B_LOOP, ModeType.HAPPY).path for _ in range(50)}
    assert paths == {Path("h.webm")}


# ---------------------------------------------------------------- find_for / find_name


def test_find_for_returns_any_name_of_the_graph():
    catalog = _catalog([_spec("idle_a"), _spec("idle_b")], seed=1)
    names = {catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP).name for _ in range(60)}
    assert names == {"idle_a", "idle_b"}


def test_find_for_skips_names_missing_the_animat():
    catalog = _catalog(
        [
            _spec("idle_a", animat=AnimatType.SINGLE),
            _spec("idle_b", animat=AnimatType.B_LOOP),
        ],
        seed=1,
    )
    for _ in range(40):
        assert catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP).name == "idle_b"


def test_find_for_does_not_cross_graphs():
    catalog = _catalog(
        [
            _spec("idle", graph=GraphType.IDEL),
            _spec("say", graph=GraphType.SAY),
        ],
        seed=1,
    )
    for _ in range(40):
        assert catalog.find_for(GraphType.IDEL, AnimatType.B_LOOP).name == "idle"
        assert catalog.find_for(GraphType.SAY, AnimatType.B_LOOP).name == "say"


def test_find_name_returns_a_name_of_the_graph_or_none():
    catalog = _catalog([_spec("idle_a"), _spec("idle_b")], seed=5)
    seen = {catalog.find_name(GraphType.IDEL) for _ in range(60)}
    assert seen == {"idle_a", "idle_b"}
    assert catalog.find_name(GraphType.WORK) is None


# ---------------------------------------------------------------- registry views


def test_names_and_specs_for_preserve_registered_animations():
    idle = _spec("idle")
    wave = _spec("wave", graph=GraphType.DEFAULT, animat=AnimatType.SINGLE)
    wave_end = _spec("wave", graph=GraphType.DEFAULT, animat=AnimatType.C_END)
    catalog = _catalog([idle, wave, wave_end])

    assert catalog.names() == ("idle", "wave")
    assert catalog.names_for(GraphType.IDEL) == ("idle",)
    assert catalog.names_for(GraphType.DEFAULT) == ("wave",)
    assert catalog.specs_for(GraphType.DEFAULT) == (wave, wave_end)
    assert catalog.specs_for(GraphType.IDEL) == (idle,)
    assert catalog.has("idle") is True
    assert catalog.has("wave") is True
    assert catalog.has("missing") is False


def test_adding_the_same_name_twice_does_not_duplicate_graph_names():
    catalog = _catalog([_spec("idle"), _spec("idle", animat=AnimatType.SINGLE)])
    assert catalog.names() == ("idle",)
    assert catalog.names_for(GraphType.IDEL) == ("idle",)
    assert len(catalog.specs_for(GraphType.IDEL)) == 2


def test_add_many_registers_every_spec():
    catalog = GraphCatalog(rng=random.Random(0))
    catalog.add_many(
        [
            _spec("idle", graph=GraphType.IDEL),
            _spec("say", graph=GraphType.SAY, animat=AnimatType.SINGLE),
        ]
    )
    assert set(catalog.names()) == {"idle", "say"}
    assert catalog.names_for(GraphType.SAY) == ("say",)
    assert catalog.find_for(GraphType.SAY, AnimatType.SINGLE).name == "say"
