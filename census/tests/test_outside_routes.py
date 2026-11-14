import pytest

from census.core.directions import describe_route, route_directions
from census.core.ems_door import pick_ems_door
from census.core.graph import build_graph, shortest_route
from census.tests.fakes import EventSink, FakeSupabase, make_context
from census.tests.fixture_building import fixture_building, seed
from census.tests.synthetic import two_floor
from census.tools import outside, routes
from census.tools.context import use_context


@pytest.fixture
def env():
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events, run_id="run-1")):
        yield db, events, seed(db)


def test_directions_on_synthetic_two_floor_building():
    g = build_graph(two_floor(with_elevator=True))
    r = shortest_route(g, "b0", ["a0"])
    assert route_directions(g, r) == "take the elevator down one floor, past the front desk, near the main entrance"
    text = describe_route(g, r, "left of the main doors")
    assert text.startswith("27 meters, ") and text.endswith("left of the main doors")
    assert route_directions(g, shortest_route(g, "a1", ["a1"])) == "near the front desk"


def test_directions_use_stairs_wording_without_elevator():
    g = build_graph(two_floor(with_elevator=False))
    r = shortest_route(g, "b0", ["a0"])
    assert "take the stairs down one floor" in route_directions(g, r)


def test_camera_routes_written_with_readable_directions(env):
    db, events, _ = env
    db.rows("cameras", id="cam-lobby-1")[0]["sweep_id"] = "f1s4"
    routes.precompute_camera_routes("cam-lobby-1")
    rows = {r["target"]: r for r in db.rows("camera_routes", camera_id="cam-lobby-1")}
    assert set(rows) == {"aed", "exit", "extinguisher"}  # no naloxone mapped
    aed = rows["aed"]
    assert aed["path"][0] == "f1s4" and aed["path"][-1] == "f0s1"
    assert aed["distance_m"] == pytest.approx(72.0)  # 60 along floor 1 + 4 + 4 + 4 via the elevator
    assert aed["directions"] == ("past the east elevators landing, take the elevator down one floor, "
                                 "by the front desk")
    assert "meters" not in aed["directions"]  # the speaker template adds the distance
    assert aed["audio_url"] is None
    assert rows["extinguisher"]["distance_m"] == 0.0  # one hangs at the spin room door
    assert any("nearest AED is 72 meters away" in m for m in events.messages("result"))


def test_camera_routes_idempotent_and_drop_missing_targets(env):
    db, _, _ = env
    routes.precompute_camera_routes("cam-lobby-1")
    db.tables["assets"] = [a for a in db.tables["assets"] if a["type"] != "extinguisher"]
    routes.precompute_camera_routes("cam-lobby-1")
    targets = sorted(r["target"] for r in db.rows("camera_routes", camera_id="cam-lobby-1"))
    assert targets == ["aed", "exit"]
    with pytest.raises(ValueError):
        routes.precompute_camera_routes("cam-nowhere")


def test_ems_door_by_walking_graph(env):
    db, events, bid = env
    assert outside.get_vexcel(bid)["entrances"] == 2
    door = outside.pick_ems_door(bid)["ems_door"]
    # The AED red zone is at the far end of floor 1, a few meters up the rear stairs.
    assert door["desc"] == "Rear loading door" and door["method"] == "walking_graph"
    assert "reason" in door and door["staging"]["desc"] == "Rear lot"
    assert db.rows("buildings", id=bid)[0]["ems_door"]["desc"] == "Rear loading door"
    assert any(e["kind"] == "decision" and e["agent"] == "outside" for e in events.events)


def test_ems_door_without_sweep_links_uses_parking():
    data = fixture_building()
    for e in data["vexcel"]["entrances"]:
        e.pop("sweep_id")
    db = FakeSupabase()
    with use_context(make_context(db, EventSink())):
        bid = seed(db, data)
        door = outside.pick_ems_door(bid)["ems_door"]
    assert door["method"] == "nearest_parking" and door["desc"] == "Rear loading door"


def test_get_vexcel_prefers_adapter_and_survives_failures(env):
    db, _, bid = env

    class Adapter:
        def get_vexcel(self, record):
            from shared.types import VexcelInfo

            assert record.costar_property_id == "FALLBACK-TEST"
            return VexcelInfo(entrances=[{"lat": 1.0, "lng": 2.0, "desc": "Only door"}])

    with use_context(make_context(db, EventSink(), adapter=Adapter())):
        assert outside.get_vexcel(bid)["entrances"] == 1
    assert db.rows("buildings", id=bid)[0]["vexcel"]["entrances"][0]["desc"] == "Only door"

    class Broken:
        def get_vexcel(self, record):
            raise RuntimeError("no network")

    sink = EventSink()
    with use_context(make_context(db, sink, adapter=Broken())):
        assert outside.get_vexcel(bid)["entrances"] == 1  # stored copy
    assert any(e["payload"].get("code") == "vexcel_unavailable" for e in sink.events)


def test_core_ems_door_rules():
    a = {"lat": 0.0, "lng": 0.0, "desc": "A", "ambulance_access": False}
    b = {"lat": 0.0, "lng": 0.001, "desc": "B", "ambulance_access": True}
    door = pick_ems_door([a, b], [], [], walk_m_to_risk={0: 5.0, 1: 50.0})
    assert door["desc"] == "B"  # A is closer but has no ambulance access
    assert pick_ems_door([], [], []) is None
    first = pick_ems_door([{"desc": "C"}, {"desc": "D"}], [], [])
    assert first["desc"] == "C" and first["method"] == "first_listed" and first["staging"] is None
