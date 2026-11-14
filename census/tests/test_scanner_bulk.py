# ruff: noqa: F811 - the scene fixture is imported from test_scanner
"""Bulk scanning on the synthetic scene from test_scanner.py."""

import math

from census.tests.test_scanner import AED, FakeModel, _use, scene  # noqa: F401 - scene is a fixture
from census.tools import bulk, scanner
from shared import db


def test_bulk_merges_three_views_into_one_triangulated_asset(scene):
    model = _use(FakeModel(confidence=0.9))
    bid = scene["building_id"]
    out = bulk.scan_building_bulk(bid, "run-1", concurrency=2)
    assert out["panos_scanned"] == 3 and out["confirmed"] == 3 and out["borderline"] == 0
    (asset,) = scene["db"].rows("assets")
    assert asset["type"] == "aed" and asset["source"] == "detected" and asset["verified"]
    assert len(asset["detection_ids"]) == 3
    assert math.dist((asset["x"], asset["y"], asset["z"]), AED) < 0.3
    assert asset["sweep_id"] == "s1" and asset["label"] == "near spot s1"  # nearest sweep to the AED
    calls = model.first_pass_calls
    again = bulk.scan_building_bulk(bid, "run-1")
    assert again["panos_scanned"] == 0 and model.first_pass_calls == calls  # resumable via tiles_done
    assert len(scene["db"].rows("assets")) == 1
    msgs = [e["message"] for e in scene["db"].rows("agent_events") if e["kind"] == "result"]
    assert msgs[0].startswith("Scanned 3 panoramas: 3 items confirmed")


def test_bulk_leaves_borderline_for_the_planner(scene):
    _use(FakeModel(confidence=0.5))
    bid = scene["building_id"]
    db.update("panos", {"tiles_done": True}, building_id=bid, sweep_id="s2")
    db.update("panos", {"tiles_done": True}, building_id=bid, sweep_id="s3")
    out = bulk.scan_building_bulk(bid, "run-1")
    assert out["borderline"] == 1 and scene["db"].rows("assets") == []
    det_id = out["borderline_detection_ids"][0]
    sv = scanner.find_second_view(det_id, "run-1")
    assert sv["matched"] and sv["second_sweep"] == "s2"
    assert math.dist(sv["position"], AED) < 0.3
    assert db.fetch_one("detections", id=det_id)["verified_by"] == "second_pano"
    second = db.fetch_one("detections", id=sv["second_detection_id"])
    assert second["verified_by"] == "second_pano" and second["status"] == "confirmed"
    pin = scanner.pin_asset(det_id, "run-1")
    assert pin["pinned"] and pin["triangulated"]
    (asset,) = scene["db"].rows("assets")
    assert sorted(asset["detection_ids"]) == sorted([det_id, sv["second_detection_id"]])
    assert math.dist((asset["x"], asset["y"], asset["z"]), AED) < 0.3
    assert scanner.pin_asset(sv["second_detection_id"])["merged"]  # same asset, no duplicate
    assert len(scene["db"].rows("assets")) == 1
    decisions = [e for e in scene["db"].rows("agent_events") if e["kind"] == "decision"]
    assert decisions and "checking a second panorama from s2" in decisions[0]["message"]


def test_bulk_stops_at_budget(scene):
    _use(FakeModel())
    out = bulk.scan_building_bulk(scene["building_id"], "run-1", budget_ok=lambda _rid: False)
    assert out["stopped_for_budget"] and out["panos_scanned"] == 0
    warnings = [e for e in scene["db"].rows("agent_events") if e["kind"] == "warning"]
    assert warnings and warnings[0]["payload"]["code"] == "budget"


def test_default_budget_guard_reads_run_cost(scene):
    run = db.insert("runs", {"buildings_target": 1, "est_cost_usd": 151.0})[0]
    assert bulk._budget_ok(run["id"]) is False
    db.update("runs", {"est_cost_usd": 1.0}, id=run["id"])
    assert bulk._budget_ok(run["id"]) is True
    assert bulk._budget_ok(None) is True
