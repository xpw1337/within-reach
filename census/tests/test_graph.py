import math

import pytest

from census.core.graph import (
    build_graph,
    component_count,
    graph_summary,
    ground_floor,
    shortest_route,
    stairs_only_sweeps,
    walking_time_map,
)
from census.tests.synthetic import line, two_floor
from shared.types import TwinNode


def test_build_graph_weights_are_3d_distances():
    nodes = [
        TwinNode("a", 0, 0.0, 0.0, 0.0, neighbors=["b"]),
        TwinNode("b", 0, 3.0, 0.0, 4.0, neighbors=["a", "c"]),
        TwinNode("c", 1, 3.0, 12.0, 4.0, neighbors=["b"], is_stairs=True),
    ]
    g = build_graph(nodes)
    assert g["a"]["b"]["weight"] == pytest.approx(5.0)
    assert g["b"]["c"]["weight"] == pytest.approx(12.0)
    assert g.nodes["c"]["is_stairs"] is True
    assert g.nodes["c"]["floor"] == 1


def test_build_graph_symmetrizes_and_counts_dangling_neighbors():
    nodes = [
        TwinNode("a", 0, 0, 0, 0, neighbors=["b", "ghost", "a"]),
        TwinNode("b", 0, 1, 0, 0, neighbors=[]),  # one-sided link from a is still an edge
    ]
    g = build_graph(nodes)
    assert g.has_edge("a", "b")
    assert g.number_of_edges() == 1
    assert g.graph["dangling_neighbors"] == 1
    assert not g.has_edge("a", "a")


def test_walking_time_map_single_and_multi_source():
    g = build_graph(line(5, spacing=14.0))  # s0..s4, 14 m apart
    times = walking_time_map(g, ["s0"], walk_speed_mps=1.4)
    assert times["s0"] == 0.0
    assert times["s4"] == pytest.approx(40.0)  # 56 m / 1.4
    both = walking_time_map(g, ["s0", "s4"], walk_speed_mps=1.4)
    assert both["s2"] == pytest.approx(20.0)
    assert both["s1"] == pytest.approx(10.0)
    assert both["s3"] == pytest.approx(10.0)


def test_walking_time_map_disconnected_omits_unreachable():
    nodes = line(3, prefix="a") + line(2, prefix="b")
    g = build_graph(nodes)
    assert component_count(g) == 2
    times = walking_time_map(g, ["a0"], walk_speed_mps=1.0)
    assert set(times) == {"a0", "a1", "a2"}
    assert "b0" not in times


def test_walking_time_map_no_usable_source_is_empty():
    g = build_graph(line(3))
    assert walking_time_map(g, [], 1.4) == {}
    assert walking_time_map(g, ["not-a-sweep"], 1.4) == {}
    with pytest.raises(ValueError):
        walking_time_map(g, ["s0"], 0)


def test_shortest_route_picks_nearest_destination():
    g = build_graph(line(6, spacing=10.0))
    route = shortest_route(g, "s2", ["s0", "s5"])
    assert route.path == ["s2", "s1", "s0"]
    assert route.distance_m == pytest.approx(20.0)


def test_shortest_route_edge_cases():
    nodes = line(3, prefix="a") + line(2, prefix="b")
    g = build_graph(nodes)
    assert shortest_route(g, "a0", ["b1"]) is None  # different component
    assert shortest_route(g, "nowhere", ["a1"]) is None
    assert shortest_route(g, "a0", []) is None
    same = shortest_route(g, "a1", ["a1"])
    assert same.path == ["a1"] and same.distance_m == 0.0


def test_shortest_route_through_floors_uses_cheapest_connection():
    g = build_graph(two_floor(with_elevator=True))
    route = shortest_route(g, "b0", ["a0"])
    # b0 -> b1 (10) -> e1 (2) -> e0 (3) -> a1 (2) -> a0 (10) = 27 m, cheaper than the stairs (~63 m)
    assert route.path == ["b0", "b1", "e1", "e0", "a1", "a0"]
    assert route.distance_m == pytest.approx(27.0)


def test_stairs_only_flags_upper_floor_without_elevator():
    g = build_graph(two_floor(with_elevator=False))
    flagged = stairs_only_sweeps(g, ["a0"])
    assert flagged == ["b0", "b1", "b2"]  # b3 is itself a stairs sweep; floor 0 is ground


def test_stairs_only_clear_with_elevator():
    g = build_graph(two_floor(with_elevator=True))
    assert stairs_only_sweeps(g, ["a0"]) == []


def test_stairs_only_partial_when_elevator_reaches_part_of_floor():
    nodes = two_floor(with_elevator=True)
    # Cut the floor-1 corridor between b1 and b2: b2 can now only leave by the stairs.
    by = {n.sweep_id: n for n in nodes}
    by["b1"].neighbors.remove("b2")
    by["b2"].neighbors.remove("b1")
    g = build_graph(nodes)
    assert stairs_only_sweeps(g, ["a0"]) == ["b2"]


def test_stairs_only_ignores_unreachable_and_no_exits():
    nodes = two_floor(with_elevator=False) + [TwinNode("island", 1, 99, 3, 0)]
    g = build_graph(nodes)
    assert "island" not in stairs_only_sweeps(g, ["a0"])  # cannot reach an exit at all: not stairs-only
    assert stairs_only_sweeps(g, []) == []


def test_exit_tagged_as_stairs_still_counts_as_exit():
    nodes = two_floor(with_elevator=True)
    g = build_graph(nodes)
    # The only exit is the stairwell door at a3; floor 1 reaches it by elevator plus the floor-0 corridor.
    assert stairs_only_sweeps(g, ["a3"]) == []


def test_ground_floor_defaults():
    g = build_graph(two_floor())
    assert ground_floor(g, ["b0"]) == 1
    assert ground_floor(g, []) == 0


def test_graph_summary_and_empty_graph():
    g = build_graph(two_floor())
    s = graph_summary(g)
    assert s["sweeps"] == 10 and s["components"] == 1 and s["floors"] == [0, 1]
    assert s["stairs_sweeps"] == 2 and s["elevator_sweeps"] == 2
    empty = build_graph([])
    assert component_count(empty) == 0
    assert walking_time_map(empty, ["x"], 1.4) == {}
    assert math.isclose(graph_summary(empty)["sweeps"], 0)
