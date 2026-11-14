"""Scanner tools end to end on a synthetic scene, with a fake LLM and the in-memory Supabase.

The panoramas are generated in memory (a red disc on black, no people) and never written to the
repo. The fake first-pass model really looks for the red disc in the image it is sent, so tiling,
bbox geometry, rays and triangulation are all exercised.
"""

import base64
import io
import math

import numpy as np
import pytest
from PIL import Image

from census.core import tiling
from census.tools import scanner
from shared import db, events, llm
from shared.fakes import FakeAnthropic, FakeSupabase, fake_json_message, isolate_settings
from shared.types import PanoRef

AED = np.array([2.0, 1.4, 3.0])
SWEEPS = {"s1": (0.0, 1.5, 0.0), "s2": (4.0, 1.5, 0.0), "s3": (8.0, 1.5, 0.0)}


def _pano(origin, target, h=256, w=512, radius_m=0.3):
    """Equirect image (pano frame = model frame) with a red disc where ``target`` is seen."""
    d = np.subtract(target, origin)
    dist = float(np.linalg.norm(d))
    radius_deg = math.degrees(math.atan(radius_m / dist))
    cols = (np.arange(w) + 0.5) / w * 360.0 - 180.0
    rows = 90.0 - (np.arange(h) + 0.5) / h * 180.0
    u, v = np.radians(np.meshgrid(cols, rows))
    dirs = np.stack([np.cos(v) * np.sin(u), np.sin(v), np.cos(v) * np.cos(u)], -1)
    ang = np.degrees(np.arccos(np.clip(dirs @ (d / dist), -1, 1)))
    img = np.zeros((h, w, 3), np.uint8)
    img[ang < radius_deg] = (220, 20, 20)
    return img


class SceneAdapter:
    def __init__(self, paths):
        self.paths = paths

    def list_panos(self, building):
        return [PanoRef(sweep_id=s, image_uri=str(p), building_id=building.id) for s, p in self.paths.items()]

    def fetch_pano(self, pano):
        return self.paths[pano.sweep_id]


def _decode(kwargs):
    for part in kwargs["messages"][0]["content"]:
        if part["type"] == "image":
            raw = base64.b64decode(part["source"]["data"])
            return np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
    raise AssertionError("no image sent")


class FakeModel:
    def __init__(self, atype="aed", confidence=0.9, confirm=True, blocked=False, person=False):
        self.atype, self.confidence, self.confirm, self.blocked, self.person = (
            atype,
            confidence,
            confirm,
            blocked,
            person,
        )
        self.first_pass_calls = self.verify_calls = 0

    def __call__(self, kwargs):
        img = _decode(kwargs)
        schema = kwargs["output_config"]["format"]["schema"]
        if "items" in schema["properties"]:
            self.first_pass_calls += 1
            red = (img[..., 0] > 140) & (img[..., 1] < 90) & (img[..., 2] < 90)
            ys, xs = np.nonzero(red)
            if len(xs) < 3:
                return fake_json_message({"items": []})
            h, w = red.shape
            bbox = [xs.min() / (w - 1), ys.min() / (h - 1), xs.max() / (w - 1), ys.max() / (h - 1)]
            return fake_json_message(
                {"items": [{"type": self.atype, "bbox": bbox, "confidence": self.confidence}]}
            )
        self.verify_calls += 1
        return fake_json_message(
            {
                "confirmed": self.confirm,
                "reason": "A red equipment cabinet is visible.",
                "blocked_exit": self.blocked,
                "person_in_crop": self.person,
            }
        )


@pytest.fixture
def scene(monkeypatch, tmp_path):
    isolate_settings(
        monkeypatch,
        USE_BEDROCK="false",
        ANTHROPIC_API_KEY="test",
        CACHE_DIR=str(tmp_path / "cache"),
        TILE_SIZE_PX="257",
        FIRST_PASS_MAX_PX="257",
        TILES_PER_PANO="6",
    )
    fake = FakeSupabase()
    db.set_db(fake)
    llm.reset()
    b = db.insert("buildings", {"costar_property_id": "TEST-1", "name": "Synthetic", "city": "Houston"})[0]
    names = list(SWEEPS)
    for i, (s, pos) in enumerate(SWEEPS.items()):
        nbrs = [names[j] for j in (i - 1, i + 1) if 0 <= j < len(names)]
        db.insert(
            "twin_nodes",
            {
                "building_id": b["id"],
                "sweep_id": s,
                "floor": 0,
                "x": pos[0],
                "y": pos[1],
                "z": pos[2],
                "neighbors": nbrs,
                "label": f"spot {s}",
            },
        )
    paths = {}
    for s, pos in SWEEPS.items():
        p = tmp_path / f"{s}.png"
        Image.fromarray(_pano(pos, AED)).save(p)
        paths[s] = p
        db.insert("panos", {"building_id": b["id"], "sweep_id": s, "image_uri": f"synthetic://{s}"})
    monkeypatch.setattr(scanner, "adapter_factory", lambda: SceneAdapter(paths))
    yield {"db": fake, "building_id": b["id"], "tmp": tmp_path}
    events.flush_events()
    db.set_db(None)
    llm.reset()


def _use(model):
    llm.set_client(FakeAnthropic(handler=model))
    return model


def test_tile_pano_caches_locally_and_uploads_nothing(scene):
    out = scanner.tile_pano(scene["building_id"], "s1", "run-1")
    assert out["tiles"] == 6
    tiles = list((scene["tmp"] / "cache" / "tiles" / scene["building_id"] / "s1").glob("*.jpg"))
    assert len(tiles) == 6
    assert scene["db"].storage_objects == {}
    kinds = [e["kind"] for e in scene["db"].rows("agent_events")]
    assert kinds == ["tool_call", "result"]


def test_first_pass_writes_candidates_once(scene):
    model = _use(FakeModel())
    bid = scene["building_id"]
    out = scanner.detect_first_pass(bid, "s1")
    assert out["candidates"] == 1 and out["by_type"] == {"aed": 1}
    assert model.first_pass_calls == 6
    (det,) = scene["db"].rows("detections")
    assert det["status"] == "candidate" and det["verified_by"] == "first_pass"
    assert det["tile_heading"] == 0.0  # the AED is about 34 degrees right of the s1 image center
    assert db.fetch_one("panos", building_id=bid, sweep_id="s1")["tiles_done"] is True
    # The stored bbox points back at the AED.
    ray = tiling.bbox_ray(
        det["bbox"], scanner._spec_for(det["tile_heading"], det["tile_pitch"]), SWEEPS["s1"]
    )
    to_aed = (AED - SWEEPS["s1"]) / np.linalg.norm(AED - SWEEPS["s1"])
    assert math.degrees(math.acos(np.clip(np.dot(ray.direction, to_aed), -1, 1))) < 2.0
    scanner.detect_first_pass(bid, "s1")
    assert len(scene["db"].rows("detections")) == 1  # rerun replaces, never duplicates


def test_low_confidence_is_dropped(scene):
    _use(FakeModel(confidence=0.2))
    out = scanner.detect_first_pass(scene["building_id"], "s1")
    assert out["candidates"] == 0 and out["below_threshold"] == 1


def test_verify_stores_crop_only(scene):
    _use(FakeModel())
    bid = scene["building_id"]
    scanner.detect_first_pass(bid, "s2")
    (det,) = scene["db"].rows("detections")
    out = scanner.verify_crop(det["id"])
    assert out["confirmed"] and not out["borderline"] and out["crop_stored"]
    row = db.fetch_one("detections", id=det["id"])
    assert row["status"] == "confirmed" and row["verified_by"] == "claude"
    assert row["crop_uri"].endswith(f"/crops/{bid}/{det['id']}.jpg")
    assert set(scene["db"].storage_objects) == {"crops"}
    stored = scene["db"].storage_objects["crops"][f"{bid}/{det['id']}.jpg"]
    crop = Image.open(io.BytesIO(stored["data"]))
    assert crop.width * crop.height < 0.35 * 257 * 257  # an equipment crop, never a full tile


def test_person_in_crop_is_not_stored(scene):
    _use(FakeModel(person=True))
    scanner.detect_first_pass(scene["building_id"], "s1")
    (det,) = scene["db"].rows("detections")
    out = scanner.verify_crop(det["id"])
    assert out["confirmed"] and not out["crop_stored"]
    assert scene["db"].storage_objects == {}
    assert "Crop not stored" in db.fetch_one("detections", id=det["id"])["notes"]


def test_rejected_is_not_pinned(scene):
    _use(FakeModel(confirm=False))
    scanner.detect_first_pass(scene["building_id"], "s1")
    (det,) = scene["db"].rows("detections")
    assert not scanner.verify_crop(det["id"])["confirmed"]
    assert scanner.pin_asset(det["id"])["pinned"] is False
    assert scene["db"].rows("assets") == []
    assert scene["db"].storage_objects == {}


def test_single_view_pins_at_viewing_sweep_and_flags_blocked_exit(scene):
    _use(FakeModel(atype="exit_sign", blocked=True))
    bid = scene["building_id"]
    scanner.detect_first_pass(bid, "s3")
    (det,) = scene["db"].rows("detections")
    scanner.verify_crop(det["id"])
    assert db.fetch_one("detections", id=det["id"])["notes"].startswith("Blocked exit: ")
    pin = scanner.pin_asset(det["id"])
    assert pin["pinned"] and not pin["triangulated"] and pin["blocked_exit"]
    (asset,) = scene["db"].rows("assets")
    assert (asset["x"], asset["y"], asset["z"]) == SWEEPS["s3"] and asset["sweep_id"] == "s3"
    assert asset["flags"] == ["blocked_exit"]


def test_three_views_merge_into_one_triangulated_asset(scene):
    _use(FakeModel(confidence=0.9))
    bid = scene["building_id"]
    for s in SWEEPS:
        scanner.detect_first_pass(bid, s)
    for det in scene["db"].rows("detections"):
        assert scanner.verify_crop(det["id"])["confirmed"]
        scanner.pin_asset(det["id"])
    (asset,) = scene["db"].rows("assets")
    assert len(asset["detection_ids"]) == 3
    assert math.dist((asset["x"], asset["y"], asset["z"]), AED) < 0.3
    assert asset["sweep_id"] == "s1" and asset["label"] == "near spot s1"


def test_borderline_second_view_triangulates(scene):
    _use(FakeModel(confidence=0.5))
    bid = scene["building_id"]
    scanner.detect_first_pass(bid, "s1")
    (det,) = scene["db"].rows("detections")
    v = scanner.verify_crop(det["id"])
    assert v["confirmed"] and v["borderline"]
    det_id = det["id"]
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
