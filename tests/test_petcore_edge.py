from __future__ import annotations

from petcore.engine.edge import (
    edge_side_at_rest,
    probe_body_bounds,
    probe_target_x,
    rotated_bounds,
)

BODY = (153, 43, 156, 194)
BOUNDS = (0, 0, 1280, 752)


def test_edge_side_uses_the_body_rect():
    assert edge_side_at_rest((0, 100, 156, 194), BOUNDS) == "left"
    assert edge_side_at_rest((1124, 100, 156, 194), BOUNDS) == "right"
    assert edge_side_at_rest((500, 100, 156, 194), BOUNDS) is None


def test_rotated_bounds_expands_around_the_pivot():
    projected = rotated_bounds(BODY, (230.5, 129.5), 45.0)
    assert projected[2] > BODY[2]
    assert projected[3] > BODY[3]
    assert projected[0] < BODY[0]
    assert projected[1] < BODY[1]


def test_probe_target_puts_the_projected_body_at_the_edge():
    projected = rotated_bounds(BODY, (230.5, 129.5), 45.0)
    left = probe_target_x("left", 0.55, projected, BOUNDS)
    right = probe_target_x("right", 0.55, projected, BOUNDS)

    assert left + projected[0] < BOUNDS[0]
    assert right + projected[0] + projected[2] > BOUNDS[2]
    assert probe_target_x("left", 1.0, projected, BOUNDS) == -projected[0]
    assert probe_target_x("right", 1.0, projected, BOUNDS) == (
        BOUNDS[0] + BOUNDS[2] - projected[0] - projected[2]
    )
    assert probe_target_x("left", 0.0, projected, BOUNDS) == (
        -projected[0] - projected[2]
    )


def test_probe_body_bounds_expands_by_one_body_width_and_subtracts_offset():
    bounds = probe_body_bounds(BOUNDS, BODY)
    assert bounds == (
        BOUNDS[0] - BODY[0] - BODY[2],
        BOUNDS[1] - BODY[1],
        BOUNDS[2] + 2 * BODY[2] + 2 * BODY[0],
        BOUNDS[3] + 2 * BODY[1],
    )
