import pytest

from census.tests.fakes import TEST_LIMITS_S, TEST_WALK_SPEED, EventSink, FakeSupabase, make_context
from census.tests.fixture_building import fixture_building, seed
from census.tools import mapper, ranking, records
from census.tools.context import use_context


@pytest.fixture
def env():
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events, run_id="run-1")):
        yield db, events, seed(db)


def test_map_building_writes_current_coverage_and_score(env):
    db, events, bid = env
    records.estimate_occupancy(bid)
    out = mapper.map_building(bid)

    cov = db.rows("coverage", building_id=bid, scenario="current")
    assert len(cov) == 20 * 3  # every sweep, every gap type, NULL where unreachable
    aed = {r["sweep_id"]: r["time_s"] for r in cov if r["asset_type"] == "aed"}
    # f0s1 holds the AED. f1s7: 4 (to e0) + 4 (e0 to e1) + 4 (to f1s1) + 120 along floor 1 = 132 m.
    assert aed["f0s1"] == 0.0
    assert aed["f1s7"] == pytest.approx(132 / TEST_WALK_SPEED)

    (score,) = db.rows("building_scores", building_id=bid)
    assert score["aed_worst_s"] == pytest.approx(132 / TEST_WALK_SPEED)  # one-way seconds (D4)
    red_aed = sum(1 for t in aed.values() if t > TEST_LIMITS_S["aed"])
    assert score["aed_red_frac"] == pytest.approx(red_aed / 20)
    assert score["blocked_exits"] == 1
    assert score["stairs_only"] is False  # the elevator gives floor 1 a stairs-free route
    assert score["people_at_risk"] is not None and score["worst_gap"] in ("aed", "extinguisher", "exit")
    assert db.rows("buildings", id=bid)[0]["census_status"] == "mapped"
    assert out["worst_gap"] == score["worst_gap"]

    kinds = events.kinds("mapper")
    assert kinds.count("tool_call") >= 1 and "decision" in kinds and "result" in kinds
    assert all(e["run_id"] == "run-1" for e in events.events)
    # AED times shown to people are round trip; payload metrics stay one-way.
    aed_msg = next(m for m in events.messages("result") if m.startswith("AED worst case"))
    assert f"{round(2 * 132 / TEST_WALK_SPEED)} s round trip" in aed_msg


def test_mapping_is_idempotent(env):
    db, _, bid = env
    mapper.map_building(bid)
    mapper.map_building(bid)
    assert len(db.rows("coverage", building_id=bid)) == 60
    assert len(db.rows("building_scores", building_id=bid)) == 1


def test_no_aed_visible_is_all_red_with_wording(env):
    db, events, bid = env
    db.tables["assets"] = [a for a in db.tables["assets"] if a["type"] != "aed"]
    mapper.map_building(bid)
    (score,) = db.rows("building_scores", building_id=bid)
    assert score["aed_red_frac"] == 1.0 and score["aed_worst_s"] is None
    assert any("No AED visible in the scan" in m for m in events.messages())
    assert not any("no AED" in m and "visible" not in m for m in events.messages())


def test_stairs_only_flag_without_elevator():
    data = fixture_building()
    data["twin_nodes"] = [n for n in data["twin_nodes"] if n["sweep_id"] not in ("e0", "e1")]
    for n in data["twin_nodes"]:
        n["neighbors"] = [x for x in n["neighbors"] if x not in ("e0", "e1")]
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events)):
        bid = seed(db, data)
        mapper.map_building(bid)
    (score,) = db.rows("building_scores", building_id=bid)
    assert score["stairs_only"] is True
    assert any(e["payload"].get("code") == "stairs_only" for e in events.events)


def test_mapper_refuses_building_without_twin_nodes(env):
    db, events, bid = env
    db.tables["twin_nodes"] = []
    with pytest.raises(mapper.MapperError):
        mapper.map_building(bid)
    assert any(e["payload"].get("code") == "no_twin_nodes" for e in events.events)
    assert db.rows("coverage") == []


def test_single_type_tool_and_bad_type(env):
    db, _, bid = env
    out = mapper.walking_time_map(bid, "extinguisher")
    assert out["sources"] == 3
    assert {r["asset_type"] for r in db.rows("coverage")} == {"extinguisher"}
    with pytest.raises(ValueError):
        mapper.walking_time_map(bid, "sprinkler")
    summary = mapper.build_graph(bid)
    assert summary["sweeps"] == 20 and summary["components"] == 1


def test_records_occupancy_and_priority(env):
    db, _, bid = env
    out = records.estimate_occupancy(bid)
    assert out["occupancy_est"] == 400  # 20000 sq ft gym / 50 (unverified factor)
    row = db.rows("buildings", id=bid)[0]
    assert row["occupancy_est"] == 400 and row["priority_score"] == 400.0
    profile = records.get_costar_profile(bid)
    assert profile["property_type"] == "Gym"
    assert records.is_fixture(row)


def test_prioritize_orders_by_occupancy_and_unknown_last(env):
    db, events, bid = env
    small = dict(fixture_building())
    small["building"] = dict(small["building"], costar_property_id="X-2", size_sqft=1000)
    land = dict(fixture_building())
    land["building"] = dict(land["building"], costar_property_id="X-3", property_type="Land")
    b2, b3 = seed(db, small), seed(db, land)
    order = records.prioritize([b3, b2, bid])
    assert order == [bid, b2, b3]
    assert db.rows("buildings", id=b3)[0]["occupancy_est"] is None
    assert any(e["kind"] == "decision" and e["agent"] == "records" for e in events.events)


def test_rerank_groups_fixtures_apart(env):
    db, _, bid = env
    real = dict(fixture_building())
    real["building"] = dict(real["building"], costar_property_id="REAL-1")
    rid = seed(db, real)
    for b in (bid, rid):
        records.estimate_occupancy(b)
        mapper.map_building(b)
    out = ranking.rerank()
    assert out["groups"] == {"fixture": 1, "Houston": 1}
    assert db.rows("building_scores", building_id=rid)[0]["rank"] == 1
    assert db.rows("building_scores", building_id=bid)[0]["rank"] == 1


def test_exit_signs_count_as_exits_and_not_connected_positions_are_left_out():
    data = fixture_building()
    data["assets"] = [a for a in data["assets"] if a["type"] != "exit"]
    data["assets"].append({"type": "exit_sign", "sweep_id": "f0s0", "floor": 0, "label": "over the main doors",
                           "source": "manual"})
    data["twin_nodes"].append({"sweep_id": "island", "floor": 1, "x": 500.0, "y": 4.0, "z": 0.0, "neighbors": [],
                               "room_type": None, "label": None, "is_elevator": False, "is_stairs": False})
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events)):
        bid = seed(db, data)
        mapper.map_building(bid)
    (score,) = db.rows("building_scores", building_id=bid)
    assert score["exit_worst_s"] is not None  # the exit sign is an exit source
    exit_times = {r["sweep_id"]: r["time_s"] for r in db.rows("coverage", building_id=bid)
                  if r["asset_type"] == "exit"}
    assert exit_times["f0s0"] == 0.0 and exit_times["island"] is None
    red = sum(1 for s, t in exit_times.items() if t is not None and t > TEST_LIMITS_S["exit"])
    assert score["exit_red_frac"] == pytest.approx(red / 20)  # 21 sweeps, 1 not connected
    assert any("1 position not connected in the scan was left out." in m for m in events.messages("result"))


def test_no_exit_sign_wording():
    data = fixture_building()
    data["assets"] = [a for a in data["assets"] if a["type"] != "exit"]
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events)):
        bid = seed(db, data)
        mapper.map_building(bid)
    assert any(m.startswith("No exit sign visible in the scan") for m in events.messages("result"))
    assert db.rows("building_scores", building_id=bid)[0]["exit_red_frac"] == 1.0
