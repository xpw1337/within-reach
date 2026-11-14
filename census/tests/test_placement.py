import pytest

from census.core.graph import build_graph
from census.core.placement import candidate_sweeps, place_one
from census.tests.synthetic import line, two_floor
from shared.types import TwinNode


def test_finds_known_best_sweep_on_a_corridor():
    # s0..s10 every 10 m, AED at s0, 1 m/s, red above 25 s.
    # Hand check: a device at s7 gives worst case 30 s (s3, s4, s10); s6 or s8 give 40 s.
    g = build_graph(line(11, spacing=10.0))
    p = place_one(g, existing=["s0"], candidates=[f"s{i}" for i in range(11)], limit_s=25.0,
                  walk_speed_mps=1.0)
    assert p.sweep_id == "s7"
    assert p.before_worst_s == pytest.approx(100.0)
    assert p.after_worst_s == pytest.approx(30.0)
    assert p.before_red_frac == pytest.approx(8 / 11)  # s3..s10
    assert p.after_red_frac == pytest.approx(3 / 11)  # s3, s4, s10
    assert p.proposed_times["s7"] == 0.0 and p.proposed_times["s9"] == pytest.approx(20.0)
    assert p.candidates_considered == 10  # s0 already has one
    assert p.subsampled is False


def test_from_scratch_when_no_device_is_visible():
    g = build_graph(line(5, spacing=10.0))
    p = place_one(g, existing=[], candidates=[f"s{i}" for i in range(5)], limit_s=15.0, walk_speed_mps=1.0)
    assert p.sweep_id == "s2"
    assert p.before_worst_s is None and p.before_red_frac == 1.0
    assert p.after_worst_s == pytest.approx(20.0)
    assert p.after_red_frac == pytest.approx(2 / 5)


def test_tie_on_worst_case_broken_by_red_fraction():
    # Corridor s0..s6 with the AED at s0, plus a leaf L hanging 50 m off s0 that no candidate
    # can improve, so every candidate leaves the worst case at 50 s. s6 would leave s3 red too;
    # s4 and s5 leave only L red, and s4 wins the id tie-break.
    nodes = line(7, spacing=10.0)
    nodes[0].neighbors.append("L")
    nodes.append(TwinNode("L", 0, 0.0, 0.0, 50.0, neighbors=["s0"]))
    g = build_graph(nodes)
    p = place_one(g, ["s0"], [f"s{i}" for i in range(1, 7)], limit_s=25.0, walk_speed_mps=1.0)
    assert p.after_worst_s == pytest.approx(50.0)
    assert p.sweep_id == "s4"
    assert p.after_red_frac == pytest.approx(1 / 8)


def test_disconnected_scan_covers_the_uncovered_component_first():
    g = build_graph(line(5, prefix="a") + [TwinNode("iso", 0, 500.0, 0.0, 0.0)])
    p = place_one(g, ["a0"], ["a1", "a2", "a3", "a4", "iso"], limit_s=25.0, walk_speed_mps=1.0)
    assert p.sweep_id == "iso"
    assert p.before_worst_s == pytest.approx(40.0)  # measured part only; iso was unreachable
    assert p.before_red_frac == pytest.approx(3 / 6)  # a3, a4, iso
    assert p.after_red_frac == pytest.approx(2 / 6)


def test_no_improvement_returns_none_and_current_map():
    g = build_graph(line(3, spacing=1.0))
    p = place_one(g, ["s0"], [], limit_s=25.0, walk_speed_mps=1.0)
    assert p.sweep_id is None
    assert p.after_worst_s == p.before_worst_s == pytest.approx(2.0)
    assert p.proposed_times == {"s0": 0.0, "s1": 1.0, "s2": 2.0}
    single = build_graph([TwinNode("x", 0, 0, 0, 0)])
    q = place_one(single, ["x"], ["x"], limit_s=25.0, walk_speed_mps=1.0)
    assert q.sweep_id is None and q.after_red_frac == 0.0


def test_subsampling_is_reported():
    g = build_graph(line(50, spacing=1.0))
    p = place_one(g, ["s0"], [f"s{i}" for i in range(50)], limit_s=10.0, walk_speed_mps=1.0,
                  max_candidates=7)
    assert p.subsampled is True and p.candidates_considered == 7
    assert p.sweep_id is not None


def test_candidate_sweeps_excludes_stairs_elevators_and_unsuitable_rooms():
    nodes = two_floor(with_elevator=True)
    by = {n.sweep_id: n for n in nodes}
    by["a2"].room_type = "Bathroom"
    by["b2"].room_type = "office"
    g = build_graph(nodes)
    cands = candidate_sweeps(g)
    assert "a3" not in cands and "b3" not in cands  # stairs
    assert "e0" not in cands and "e1" not in cands  # elevators
    assert "a2" not in cands
    assert "b2" in cands and "a0" in cands
