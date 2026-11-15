"""data/matterport.py (Model API export) and the committed demo/rabinowitz/building.json."""

import base64
import json
import math

import httpx
import networkx as nx
import pytest

from data import load as loader
from data import matterport as mp
from data.adapter import is_fixture
from data.fallback import FallbackAdapter
from shared import db
from shared.config import REPO_ROOT, MissingSettingError
from shared.fakes import FakeSupabase, isolate_settings
from shared.types import BuildingRecord

RABINOWITZ_FILE = REPO_ROOT / "demo" / "rabinowitz" / "building.json"
CAMERA_SWEEP = "1k478kza39tbfu1uhbttg5ybb"
AED_SWEEP = "0f2a2fyf5iibscursb5gkyu9a"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    isolate_settings(monkeypatch)
    fake = FakeSupabase()
    db.set_db(fake)
    yield fake
    db.set_db(None)


# ---------------------------------------------------------------- synthetic Model API data

F2 = {"id": "f2", "sequence": 1, "label": "Floor 2"}
F3 = {"id": "f3", "sequence": 2, "label": "Floor 3"}


def _loc(i, floor, x, y, z, neighbors):
    return {"id": i, "floor": floor, "position": {"x": x, "y": y, "z": z}, "neighbors": neighbors}


def synthetic_locations():
    """Ground: a(0,0) b(3,0) c(10,0, only line-of-sight to b at 7 m) d(4,2).
    Upper: u1(0,0,4) over a, u2(3,1,4). Landing s(3.5,1.5,2) labeled upper floor, between levels."""
    return [
        _loc("a", F2, 0, 0, 0, ["b", "u1", "s"]),
        _loc("b", F2, 3, 0, 0, ["a", "c", "u1", "s", "d"]),
        _loc("c", F2, 10, 0, 0, ["b"]),
        _loc("d", F2, 4, 2, 0, ["b", "s"]),
        _loc("u1", F3, 0, 0, 4, ["a", "b", "u2", "s"]),
        _loc("u2", F3, 3, 1, 4, ["u1", "s"]),
        _loc("s", F3, 3.5, 1.5, 2, ["a", "b", "d", "u1", "u2"]),
    ]


def test_z_up_to_y_up_matches_matterport_conversion():
    # Matterport documents fromApiToSdk(x, y, z) = [x, z, -y].
    assert mp.to_y_up({"x": 1.0, "y": 2.0, "z": 3.0}) == (1.0, 3.0, -2.0)


def test_floor_number_from_label_then_sequence():
    assert mp.floor_number(F2) == 2
    assert mp.floor_number({"id": "x", "sequence": 4, "label": ""}) == 4
    assert mp.floor_number(None) is None


def test_stairs_are_sweeps_between_floor_levels():
    assert mp.stair_sweeps(synthetic_locations()) == {"s"}
    # One floor only: nothing can be a landing.
    flat = [loc for loc in synthetic_locations() if loc["floor"] is F2]
    assert mp.stair_sweeps(flat) == set()


def test_walkable_edges_drop_long_and_cross_floor_links():
    edges, rep = mp.walkable_edges(synthetic_locations(), max_edge_m=6.0)
    assert ("b", "c") not in edges  # 7 m line of sight on the same floor
    assert ("a", "u1") not in edges and ("b", "u1") not in edges  # straight up over the void
    assert {("a", "b"), ("b", "d"), ("u1", "u2")} <= edges
    # The landing links only to its nearest neighbor at each level: d below, u2 above.
    stair = {e for e in edges if "s" in e}
    assert stair == {("d", "s"), ("s", "u2")}
    assert rep.stairs == ["s"] and rep.stair_edges == 2 and rep.same_floor_kept == 3
    assert rep.kept == len(edges) == 5
    assert rep.cross_floor_pairs == 5  # a-u1, b-u1, and the landing (labeled upper) to a, b, d


def test_no_stair_sweep_leaves_floors_unconnected():
    locs = [loc for loc in synthetic_locations() if loc["id"] != "s"]
    for loc in locs:
        loc["neighbors"] = [n for n in loc["neighbors"] if n != "s"]
    edges, rep = mp.walkable_edges(locs)
    floors = {loc["id"]: loc["floor"]["id"] for loc in locs}
    assert all(floors[a] == floors[b] for a, b in edges) and rep.stair_edges == 0


def _spec(tmp_path):
    return mp.DemoSpec(
        model_id="M1",
        building={"costar_property_id": "DEMO-TEST", "name": "Test Hall", "city": "Princeton",
                  "matterport_model_id": "M1"},
        camera={"id": "cam-test-1", "name": "Test camera", "sweep_id": "a", "landmark": "the test atrium"},
        assets=[{"type": "aed", "sweep_id": "d", "label": "Demo AED (placed by team)", "source": "manual",
                 "verified": False, "flags": ["simulated"]}],
        labels={"a": "test atrium"},
        note="test",
        out=tmp_path / "building.json",
    )


def _model(**extra):
    return {"id": "M1", "name": "Test", "floors": [F2, F3], "locations": synthetic_locations(), **extra}


def test_build_document_is_the_fallback_format(tmp_path):
    spec = _spec(tmp_path)
    doc = mp.build_document(_model(), spec)
    assert set(doc) >= {"building", "twin_nodes", "panos", "assets", "camera"}
    assert doc["panos"] == []
    b = doc["building"]
    # No coordinates or address from the API: they stay null, never invented.
    assert (b["lat"], b["lng"], b["address"]) == (None, None, None)
    assert (b["size_sqft"], b["tenants_count"], b["property_type"], b["floors"]) == (None,) * 4
    nodes = {n["sweep_id"]: n for n in doc["twin_nodes"]}
    assert (nodes["u1"]["x"], nodes["u1"]["y"], nodes["u1"]["z"]) == (0.0, 4.0, -0.0)
    assert nodes["s"]["is_stairs"] and not nodes["a"]["is_stairs"]
    assert nodes["a"]["label"] == "test atrium" and nodes["b"]["label"] is None
    for n in nodes.values():
        for m in n["neighbors"]:
            assert n["sweep_id"] in nodes[m]["neighbors"]
    (aed,) = doc["assets"]
    assert aed["flags"] == ["simulated"] and aed["verified"] is False
    assert (aed["floor"], aed["x"], aed["y"], aed["z"]) == (2, 4.0, 0.0, -2.0)
    assert doc["camera"]["floor"] == 2

    mp.write_document(doc, spec.out)
    adapter = FallbackAdapter(spec.out)
    (rec,) = adapter.list_buildings()
    assert rec.costar_property_id == "DEMO-TEST" and is_fixture(rec.costar_property_id)
    assert len(adapter.get_twin(rec)) == 7


def test_build_document_uses_api_location_when_present(tmp_path):
    doc = mp.build_document(_model(geocoordinates={"latitude": 40.1, "longitude": -74.2},
                                   address={"locality": "Princeton", "administrativeArea": "NJ",
                                            "postalCode": "08544"}), _spec(tmp_path))
    b = doc["building"]
    assert (b["lat"], b["lng"], b["address"]) == (40.1, -74.2, "Princeton, NJ 08544")


def test_build_document_rejects_unknown_demo_sweep(tmp_path):
    spec = _spec(tmp_path)
    spec.camera = {**spec.camera, "sweep_id": "nowhere"}
    with pytest.raises(ValueError, match="nowhere"):
        mp.build_document(_model(), spec)


def test_fetch_model_needs_credentials():
    with pytest.raises(MissingSettingError, match="MATTERPORT_API_KEY"):
        mp.fetch_model("M1")


def test_fetch_model_sends_basic_auth_and_variables(monkeypatch):
    isolate_settings(monkeypatch, MATTERPORT_API_KEY="k-test", MATTERPORT_API_TOKEN="t-test")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"model": _model()}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        model = mp.fetch_model("M1", client=client)
    assert model["id"] == "M1"
    assert seen["auth"] == "Basic " + base64.b64encode(b"k-test:t-test").decode()
    assert seen["body"]["variables"] == {"id": "M1"} and "neighbors" in seen["body"]["query"]


def test_fetch_model_errors_do_not_echo_credentials(monkeypatch):
    isolate_settings(monkeypatch, MATTERPORT_API_KEY="k-secret", MATTERPORT_API_TOKEN="t-secret")
    responses = iter([
        httpx.Response(401, text="nope"),
        httpx.Response(200, json={"errors": [{"message": "bad field"}]}),
        httpx.Response(200, json={"data": {"model": None}}),
    ])
    with httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))) as client:
        for match in ("HTTP 401", "bad field", "not found"):
            with pytest.raises(mp.MatterportError, match=match) as err:
                mp.fetch_model("M1", client=client)
            assert "secret" not in str(err.value)


# ---------------------------------------------------------------- the committed Rabinowitz file


@pytest.fixture(scope="module")
def doc():
    return json.loads(RABINOWITZ_FILE.read_text(encoding="utf-8"))


def test_rabinowitz_contract_values(doc):
    b = doc["building"]
    assert b["costar_property_id"] == "DEMO-RABINOWITZ" and is_fixture(b["costar_property_id"])
    assert (b["name"], b["city"], b["matterport_model_id"]) == (
        "Julis Romo Rabinowitz Building", "Princeton", "P3S6VUTP3qB")
    assert b["size_sqft"] is None and b["tenants_count"] is None and b["property_type"] is None
    assert doc["panos"] == []
    cam = doc["camera"]
    assert cam["id"] == "cam-atrium-1" and cam["sweep_id"] == CAMERA_SWEEP and cam["landmark"]
    (aed,) = doc["assets"]
    assert aed == {**aed, "type": "aed", "source": "manual", "verified": False,
                   "label": "Demo AED (placed by team)", "sweep_id": AED_SWEEP}
    assert "simulated" in aed["flags"]


def test_rabinowitz_graph_is_walkable(doc):
    nodes = {n["sweep_id"]: n for n in doc["twin_nodes"]}
    assert len(nodes) == 66
    # y-up: the atrium level sits near y = 0 and the gallery about 4 m above it.
    levels = {f: sorted(n["y"] for n in nodes.values() if n["floor"] == f and not n["is_stairs"]) for f in (2, 3)}
    assert abs(levels[2][len(levels[2]) // 2]) < 0.2 and 3.5 < levels[3][len(levels[3]) // 2] < 4.5
    g = mp.graph_of(nodes.values())
    for a, c, data in g.edges(data=True):
        assert a in nodes[c]["neighbors"] and c in nodes[a]["neighbors"]
        assert data["weight"] <= mp.WALK_EDGE_MAX_M + 1e-6
        if nodes[a]["floor"] != nodes[c]["floor"] or abs(nodes[a]["y"] - nodes[c]["y"]) > 1.0:
            assert nodes[a]["is_stairs"] or nodes[c]["is_stairs"]  # floors join only through stairs
    meters = nx.dijkstra_path_length(g, CAMERA_SWEEP, AED_SWEEP, weight="weight")
    assert 8 <= meters <= 15
    assert nodes[CAMERA_SWEEP]["floor"] == nodes[AED_SWEEP]["floor"] == 2
    assert doc["_edges"]["max_edge_m"] == mp.WALK_EDGE_MAX_M
    assert g.number_of_edges() == doc["_edges"]["same_floor_edges"] + doc["_edges"]["stair_edges"]


def test_rabinowitz_loads_idempotently_next_to_the_fallback(_isolated):
    fake = _isolated
    loader.main(["--fallback"])
    before = {t: len(fake.rows(t)) for t in ("buildings", "twin_nodes", "assets", "cameras")}
    assert loader.main(["--file", "demo/rabinowitz/building.json"]) == 0
    assert loader.main(["--file", str(RABINOWITZ_FILE)]) == 0
    after = {t: len(fake.rows(t)) for t in before}
    assert after == {"buildings": before["buildings"] + 1, "twin_nodes": before["twin_nodes"] + 66,
                     "assets": before["assets"] + 1, "cameras": before["cameras"] + 1}
    def rows(table, **eq):
        return [r for r in fake.rows(table) if all(r.get(k) == v for k, v in eq.items())]

    (b,) = rows("buildings", costar_property_id="DEMO-RABINOWITZ")
    (cam,) = rows("cameras", id="cam-atrium-1")
    assert cam["building_id"] == b["id"] and cam["landmark"]
    (aed,) = rows("assets", building_id=b["id"])
    assert aed["verified"] is False and aed["flags"] == ["simulated"] and aed["source"] == "manual"
    stairs = [r for r in rows("twin_nodes", building_id=b["id"]) if r["is_stairs"]]
    assert len(stairs) == 1  # the landing, not an inference from floor-changing edges
    (lobby,) = rows("cameras", id="cam-lobby-1")
    assert lobby["building_id"] != b["id"]


def test_fallback_adapter_only_answers_for_its_own_building():
    adapter = FallbackAdapter()  # the FALLBACK-1 file
    other = BuildingRecord(costar_property_id="DEMO-RABINOWITZ")
    assert adapter.get_vexcel(other) is None
    assert adapter.get_twin(other) == [] and adapter.get_assets(other) == [] and adapter.get_camera(other) is None
    (mine,) = adapter.list_buildings()
    assert adapter.get_vexcel(mine) is not None and adapter.get_twin(mine)


def test_rabinowitz_edges_are_short(doc):
    nodes = {n["sweep_id"]: n for n in doc["twin_nodes"]}
    for n in nodes.values():
        for m in n["neighbors"]:
            o = nodes[m]
            assert math.dist((n["x"], n["y"], n["z"]), (o["x"], o["y"], o["z"])) <= mp.WALK_EDGE_MAX_M + 1e-6
