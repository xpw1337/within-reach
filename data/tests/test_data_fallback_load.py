import math

import networkx as nx
import pytest

from data import load as loader
from data.adapter import get_adapter, is_fixture
from data.fallback import FALLBACK_ID, FallbackAdapter
from shared import db, thresholds
from shared.fakes import FakeSupabase, isolate_settings
from shared.types import BuildingRecord, TwinNode


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    isolate_settings(monkeypatch)
    fake = FakeSupabase()
    db.set_db(fake)
    yield fake
    db.set_db(None)


@pytest.fixture
def adapter():
    return FallbackAdapter()


def _graph(nodes):
    g = nx.Graph()
    by = {n.sweep_id: n for n in nodes}
    for n in nodes:
        for m in n.neighbors:
            o = by[m]
            g.add_edge(n.sweep_id, m, weight=math.dist((n.x, n.y, n.z), (o.x, o.y, o.z)))
    return g


# ---------------------------------------------------------------- fixture requirements (demo/DESIGN.md)


def test_fixture_meets_design_requirements(adapter):
    (b,) = adapter.list_buildings()
    assert b.costar_property_id == FALLBACK_ID and is_fixture(b.costar_property_id)
    assert "fixture" in b.name.lower() and "fictional" in b.address.lower()
    nodes = adapter.get_twin(b)
    assert 28 <= len(nodes) <= 36
    assert {n.floor for n in nodes} == {0, 1}
    g = _graph(nodes)
    assert nx.is_connected(g)
    by = {n.sweep_id: n for n in nodes}
    cross = [(a, c) for a, c in g.edges if by[a].floor != by[c].floor]
    kinds = sorted(
        "elevator" if by[a].is_elevator else "stairs" if by[a].is_stairs else "?" for a, _ in cross
    )
    assert kinds == ["elevator", "stairs"]  # one stair and one elevator connect the floors
    assert all(
        by[c].is_elevator == by[a].is_elevator and by[c].is_stairs == by[a].is_stairs for a, c in cross
    )

    assets = adapter.get_assets(b)
    count = {t: sum(a["type"] == t for a in assets) for t in ("aed", "extinguisher", "exit")}
    assert count == {"aed": 1, "extinguisher": 3, "exit": 2}
    assert all(a["sweep_id"] in by for a in assets)

    cam = adapter.get_camera(b)
    assert cam["id"] == "cam-lobby-1" and cam["landmark"] == "east elevators"
    assert by[cam["sweep_id"]].label == "east elevators"

    v = adapter.get_vexcel(b)
    assert len(v.entrances) == 2 and all("lat" in e and "lng" in e for e in v.entrances)


def test_fixture_far_end_of_second_floor_is_clearly_aed_red(adapter):
    (b,) = adapter.list_buildings()
    nodes = adapter.get_twin(b)
    g = _graph(nodes)
    aed = next(a["sweep_id"] for a in adapter.get_assets(b) if a["type"] == "aed")
    dist = nx.single_source_dijkstra_path_length(g, aed, weight="weight")
    times = {s: d / 1.4 for s, d in dist.items()}
    floor1 = [n.sweep_id for n in nodes if n.floor == 1]
    worst = max(floor1, key=times.get)
    assert thresholds.zone("aed", times[worst]) == "red"
    assert times[worst] > 1.15 * thresholds.limit_seconds("aed")  # clearly, not marginally
    zones = {thresholds.zone("aed", times[s]) for s in times}
    assert zones == {"green", "yellow", "red"}  # the heatmap shows all three colors


def test_neighbors_symmetric_in_file(adapter):
    (b,) = adapter.list_buildings()
    nodes = adapter.get_twin(b)
    _, rep = loader.normalize_twin(nodes)
    assert rep.neighbor_fixes == 0 and rep.dropped_neighbors == 0


def test_get_adapter_defaults_to_fallback(monkeypatch):
    assert isinstance(get_adapter(), FallbackAdapter)
    isolate_settings(monkeypatch, COSTAR_DATA_PATH="/nowhere")
    with pytest.raises(NotImplementedError, match="COSTAR_DATA_PATH"):
        get_adapter()


def test_filters(adapter):
    assert len(list(adapter.list_buildings(city="houston", types=["Gym"]))) == 1
    assert list(adapter.list_buildings(city="Los Angeles")) == []
    assert list(adapter.list_buildings(types=["office"])) == []


# ---------------------------------------------------------------- normalization


def _n(s, floor, y=0.0, neighbors=(), **kw):
    return TwinNode(sweep_id=s, floor=floor, x=0.0, y=y, z=0.0, neighbors=list(neighbors), **kw)


def test_symmetrize_and_drop():
    nodes = [_n("a", 0, neighbors=["b", "ghost", "a"]), _n("b", 0), _n("c", 0, neighbors=["b", "b"])]
    out, rep = loader.normalize_twin(nodes)
    by = {n.sweep_id: n for n in out}
    assert sorted(by["b"].neighbors) == ["a", "c"]
    assert by["a"].neighbors == ["b"] and by["c"].neighbors == ["b"]
    assert rep.neighbor_fixes == 2 and rep.dropped_neighbors == 2
    assert nodes[0].neighbors == ["b", "ghost", "a"]  # input not mutated


def test_floors_clustered_from_heights():
    nodes = [_n("a", None, y=0.1), _n("b", None, y=0.4), _n("c", 2.0, y=4.2), _n("d", None, y=8.6)]
    out, rep = loader.normalize_twin(nodes)
    assert rep.floors_clustered
    assert [n.floor for n in out] == [0, 0, 1, 2]
    assert all(isinstance(n.floor, int) for n in out)


def test_integral_float_floors_become_ints():
    out, rep = loader.normalize_twin([_n("a", 1.0), _n("b", 0)])
    assert [n.floor for n in out] == [1, 0] and not rep.floors_clustered
    assert all(type(n.floor) is int for n in out)


def test_stairs_from_labels_and_inference():
    out, _ = loader.normalize_twin(
        [
            _n("a", 0, label="Stairwell B"),
            _n("b", 0, room_type="Elevator lobby"),
            _n("c", 0, label="weight lifting"),
        ]
    )
    assert [(n.is_stairs, n.is_elevator) for n in out] == [(True, False), (False, True), (False, False)]
    out, rep = loader.normalize_twin(
        [_n("a", 0, neighbors=["b"]), _n("b", 1, y=4.0), _n("c", 0, neighbors=["a"])]
    )
    assert rep.stairs_inferred == 2
    assert [n.is_stairs for n in out] == [True, True, False]


# ---------------------------------------------------------------- loading (fake Supabase)


def test_fallback_load_fills_tables(adapter, _isolated):
    fake = _isolated
    (s,) = loader.load(adapter, with_fixture_rows=True)
    assert s.twin_nodes == 33 and s.assets == 6 and s.cameras == 1
    (b,) = fake.rows("buildings")
    assert b["costar_property_id"] == FALLBACK_ID and b["census_status"] == "pending"
    assert "vexcel" not in b or b["vexcel"] is None  # census Outside owns vexcel
    assert len(fake.rows("twin_nodes")) == 33
    assert {r["type"] for r in fake.rows("assets")} == {"aed", "extinguisher", "exit"}
    assert all(r["source"] == "manual" and r["verified"] for r in fake.rows("assets"))
    (cam,) = fake.rows("cameras")
    assert cam["building_id"] == b["id"] and cam["sweep_id"] == "s3" and cam["landmark"] == "east elevators"
    aed = next(r for r in fake.rows("assets") if r["type"] == "aed")
    assert (aed["x"], aed["floor"]) == (88.0, 0)


def test_fallback_load_twice_is_idempotent(adapter, _isolated):
    fake = _isolated
    loader.load(adapter, with_fixture_rows=True)
    first = {t: fake.rows(t) for t in ("buildings", "twin_nodes", "panos", "assets", "cameras")}
    # Census writes must survive a reload.
    db.update("buildings", {"census_status": "mapped", "occupancy_est": 5}, costar_property_id=FALLBACK_ID)
    db.update("panos", {"tiles_done": True}, building_id=first["buildings"][0]["id"])
    loader.load(adapter, with_fixture_rows=True)
    for table, rows in first.items():
        assert len(fake.rows(table)) == len(rows), table
    (b,) = fake.rows("buildings")
    assert b["id"] == first["buildings"][0]["id"]
    assert b["census_status"] == "mapped" and b["occupancy_est"] == 5
    assert sorted(r["id"] for r in fake.rows("assets")) == sorted(r["id"] for r in first["assets"])


def test_asymmetric_dataset_is_fixed_and_logged(caplog, _isolated):
    class Asym:
        def list_buildings(self, city=None, types=None):
            return [BuildingRecord(costar_property_id="T-1", city="Houston")]

        def get_twin(self, b):
            return [_n("a", 0, neighbors=["b"]), _n("b", 0, neighbors=[]), _n("c", 0, neighbors=["a", "zz"])]

        def list_panos(self, b):
            from shared.types import PanoRef

            return [PanoRef(sweep_id="a", image_uri="s3://bucket/a.jpg")]

        def fetch_pano(self, p):
            raise NotImplementedError

        def get_vexcel(self, b):
            return None

    with caplog.at_level("WARNING", logger="data.load"):
        (s,) = loader.load(Asym())
        loader.load(Asym())
    assert s.report.neighbor_fixes == 2 and s.report.dropped_neighbors == 1
    assert "added 2 missing neighbor back-links" in caplog.text
    rows = {r["sweep_id"]: r for r in _isolated.rows("twin_nodes")}
    assert sorted(rows["a"]["neighbors"]) == ["b", "c"]
    assert len(_isolated.rows("panos")) == 1 and _isolated.rows("panos")[0]["tiles_done"] is False
    assert len(_isolated.rows("buildings")) == 1


def test_cli_fallback(capsys, _isolated):
    assert loader.main(["--fallback"]) == 0
    assert loader.main(["--fallback"]) == 0
    out = capsys.readouterr().out
    assert out.count("FALLBACK-1: building") == 2 and "33 sweeps" in out
    assert len(_isolated.rows("buildings")) == 1 and len(_isolated.rows("assets")) == 6
