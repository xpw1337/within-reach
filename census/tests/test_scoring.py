import pytest

from census.core.occupancy import (
    OCCUPANT_LOAD_FACTORS_SQFT_GROSS,
    TABLE_STATUS,
    estimate_occupancy,
    function_of_space,
)
from census.core.scoring import (
    GAP_WEIGHTS,
    gap_score,
    people_at_risk,
    rank_buildings,
    red_sweeps,
    scan_priority,
    score_building,
    type_stats,
    worst_gap,
)
from shared.types import BuildingScore, Flags

LIMITS = {"aed": 90.0, "extinguisher": 20.0, "exit": 40.0}


def test_occupancy_table_is_marked_unverified():
    assert TABLE_STATUS == "unverified"


@pytest.mark.parametrize(
    "ptype,function",
    [
        ("Office", "business_areas"),
        ("Medical Office", "institutional_outpatient_areas"),
        ("Gym / Fitness Center", "exercise_rooms"),
        ("Retail", "mercantile"),
        ("Industrial", "industrial_areas"),
        ("Warehouse", "warehouses"),
        ("Multi-Family", "residential"),
        ("Hotel", "residential"),
        ("Land", None),
        ("Flex", None),
        ("", None),
        (None, None),
    ],
)
def test_function_of_space_mapping(ptype, function):
    assert function_of_space(ptype) == function


def test_estimate_occupancy_divides_gross_area_by_factor():
    est = estimate_occupancy("Office", 15000)
    assert est.people == 15000 // OCCUPANT_LOAD_FACTORS_SQFT_GROSS["business_areas"]
    assert est.sqft_per_occupant == 150
    assert "unverified" in est.basis
    # Rounded up to whole people.
    assert estimate_occupancy("gym", 101).people == 3  # 101 / 50 = 2.02


def test_estimate_occupancy_returns_none_rather_than_guessing():
    assert estimate_occupancy("Land", 10000) is None
    assert estimate_occupancy("Office", None) is None
    assert estimate_occupancy("Office", 0) is None


def test_type_stats_counts_red_and_unreachable():
    times = {"a": 10.0, "b": 90.0, "c": 91.0}
    s = type_stats(times, sweeps_total=4, limit_s=90.0)  # "d" is unreachable
    assert s.worst_s == 91.0
    assert s.red_sweeps == 2  # c over the limit (strictly greater), d unreachable
    assert s.unreachable == 1
    assert s.red_frac == pytest.approx(0.5)
    assert red_sweeps(times, ["a", "b", "c", "d"], 90.0) == ["c", "d"]


def test_type_stats_no_asset_visible_is_all_red_with_no_worst_case():
    s = type_stats({}, sweeps_total=10, limit_s=90.0)
    assert s.worst_s is None and s.red_frac == 1.0
    empty = type_stats({}, sweeps_total=0, limit_s=90.0)
    assert empty.red_frac is None


def test_worst_gap_and_ties():
    assert worst_gap({"aed": 0.1, "extinguisher": 0.4, "exit": 0.0}) == "extinguisher"
    assert worst_gap({"aed": 0.3, "extinguisher": 0.3, "exit": 0.3}) == "aed"
    assert worst_gap({"aed": 0.0, "extinguisher": 0.0, "exit": None}) == "none"


def test_gap_score_weights_aed_highest():
    assert GAP_WEIGHTS["aed"] > GAP_WEIGHTS["extinguisher"] and GAP_WEIGHTS["aed"] > GAP_WEIGHTS["exit"]
    assert sum(GAP_WEIGHTS.values()) == pytest.approx(1.0)
    assert gap_score({"aed": 1.0, "extinguisher": 0.0, "exit": 0.0}) > gap_score(
        {"aed": 0.0, "extinguisher": 1.0, "exit": 0.0})
    assert gap_score({"aed": None}) == 0.0


def test_people_at_risk():
    assert people_at_risk(200, 0.25) == 50
    assert people_at_risk(None, 0.25) is None
    assert people_at_risk(200, None) == 0


def test_score_building_end_to_end():
    coverage = {
        "aed": {"s0": 0.0, "s1": 50.0, "s2": 100.0, "s3": 120.0},  # 2 of 4 red
        "extinguisher": {"s0": 5.0, "s1": 5.0, "s2": 5.0, "s3": 5.0},  # none red
        "exit": {},  # no exit visible in the scan
    }
    flags = Flags(stairs_only_sweeps=["s3"], blocked_exits=1, sweeps_total=4)
    score = score_building(coverage, 400, flags, limits_s=LIMITS)
    assert score.aed_worst_s == 120.0 and score.aed_red_frac == pytest.approx(0.5)
    assert score.ext_worst_s == 5.0 and score.ext_red_frac == 0.0
    assert score.exit_worst_s is None and score.exit_red_frac == 1.0
    assert score.worst_gap == "exit"
    assert score.people_at_risk == 400
    assert score.stairs_only is True and score.blocked_exits == 1
    assert score.gap_score == pytest.approx(0.5 * 0.5 + 0.25 * 0.0 + 0.25 * 1.0)


def test_score_building_all_green_and_unknown_occupancy():
    cov = {g: {"s0": 1.0, "s1": 2.0} for g in ("aed", "extinguisher", "exit")}
    score = score_building(cov, None, Flags(sweeps_total=2), limits_s=LIMITS)
    assert score.worst_gap == "none"
    assert score.people_at_risk is None
    assert score.gap_score == 0.0


def _score(gap, par):
    return BuildingScore(None, None, None, None, None, None, False, 0, "aed", par, gap)


def test_rank_buildings_orders_by_gap_then_people_then_id():
    ranks = rank_buildings({
        "b": _score(0.5, 10),
        "a": _score(0.5, 10),
        "c": _score(0.5, None),
        "d": _score(0.9, 1),
        "e": _score(0.5, 99),
    })
    assert ranks == {"d": 1, "e": 2, "a": 3, "b": 4, "c": 5}


def test_scan_priority():
    assert scan_priority(120) == 120.0
    assert scan_priority(None) is None
