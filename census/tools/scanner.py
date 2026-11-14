"""Scanner subagent tools (spec sections 9.2 and 9.3): tile_pano, detect_first_pass, verify_crop,
find_second_view, pin_asset.

Each tool reads rows, calls census/core or census/vision, writes rows, emits a ``tool_call`` and a
``result`` console event, and returns a short JSON-serializable summary (never bulk data).

Privacy: panoramas and tiles stay in the local cache (``.cache/tiles``); only equipment crops are
uploaded, only to the ``crops`` bucket, only for confirmed detections, never when the verifier
reports a person filling the crop, and never when the padded crop covers most of the tile.

Row conventions:
- ``detections.tile_heading`` / ``tile_pitch``: orientation of the tile the detection was found in
  (the tile FOV is ``TILE_FOV_DEG``); ``bbox``: normalized ``[x_min, y_min, x_max, y_max]`` in it.
- ``detections.notes``: the verifier's reason, prefixed "Blocked exit: " when the exit looks
  obstructed. A second-view detection ends with "Second view of detection <id>."
- An asset whose position equals its sweep position was pinned at the viewing sweep (no
  triangulation); otherwise its position is triangulated from two views.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from census.core import tiling
from census.core.tiling import TileSpec
from census.core.triangulate import triangulate
from census.vision import first_pass as vision_first_pass
from census.vision import verify as vision_verify
from data.adapter import get_adapter
from shared import db, events
from shared.config import get_settings
from shared.types import BuildingRecord, PanoRef, Ray, from_row

log = logging.getLogger(__name__)

AGENT = "scanner"
CROPS_BUCKET = "crops"
MERGE_RADIUS_M = 1.5  # same type within this distance is the same physical item
MAX_CROP_AREA_FRAC = 0.35  # a padded crop larger than this share of the tile is not uploaded
SECOND_VIEW_MIN_ANGLE_DEG = 20.0
DEPTH_GUESSES_M = (1.5, 2.5, 4.0, 6.0, 9.0, 13.0)
_SECOND_VIEW_RE = re.compile(r"Second view of detection ([0-9a-fA-F-]{36})")
BLOCKED_PREFIX = "Blocked exit: "

# Injectable for tests and for the real dataset adapter.
adapter_factory = get_adapter


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _run_id(run_id: str | None) -> str | None:
    """Explicit run id, else the census run context's (census/tools/context.py) when one is active."""
    if run_id is not None:
        return run_id
    try:
        from census.tools.context import _override  # active context only; never builds a default

        current = _override.get()
        return current.run_id if current is not None else None
    except Exception:  # noqa: BLE001 - the context module is optional for these tools
        return None


def _emit(run_id: str | None, kind: str, message: str, building_id: str | None, payload: dict) -> None:
    events.emit_agent_event(run_id, AGENT, kind, message, building_id, payload)


def _tool_call(run_id: str | None, tool: str, args: dict, building_id: str | None) -> None:
    shown = ", ".join(f"{k}={v}" for k, v in args.items() if k != "building_id")
    _emit(run_id, "tool_call", f"{tool}({shown})", building_id, {"tool": tool, "args": args})


def _result(run_id: str | None, tool: str, message: str, building_id: str | None, metrics: dict) -> None:
    _emit(run_id, "result", message, building_id, {"tool": tool, "summary": message, "metrics": metrics})


def _type_name(t: str) -> str:
    return {
        "aed": "AED",
        "exit_sign": "exit sign",
        "smoke_detector": "smoke detector",
        "first_aid": "first aid kit",
    }.get(t, t)


def _tile_cache_dir(building_id: str, sweep_id: str) -> Path:
    return Path(get_settings().cache_dir) / "tiles" / building_id / sweep_id


def _specs() -> list[TileSpec]:
    s = get_settings()
    return tiling.tile_specs(s.tiles_per_pano, s.tile_fov_deg, s.tile_size_px)


def _spec_for(heading: float, pitch: float) -> TileSpec:
    """The standard tile with this orientation, or an ad-hoc one (second-view tiles)."""
    for spec in _specs():
        if math.isclose(spec.heading_deg, heading, abs_tol=1e-3) and math.isclose(
            spec.pitch_deg, pitch, abs_tol=1e-3
        ):
            return spec
    s = get_settings()
    return TileSpec(-1, float(heading), float(pitch), s.tile_fov_deg, s.tile_size_px)


def _nodes(building_id: str) -> dict[str, dict]:
    return {n["sweep_id"]: n for n in db.fetch_all("twin_nodes", building_id=building_id)}


def _pos(node: dict) -> tuple[float, float, float]:
    return float(node["x"]), float(node["y"]), float(node["z"])


def _pano_ref(building_id: str, sweep_id: str) -> PanoRef | None:
    """PanoRef with the sweep rotation from the adapter when available, else from the panos row."""
    row = db.fetch_one("panos", building_id=building_id, sweep_id=sweep_id)
    try:
        b = db.fetch_one("buildings", id=building_id)
        if b is not None:
            rec = from_row(BuildingRecord, b)
            for p in adapter_factory().list_panos(rec):
                if p.sweep_id == sweep_id:
                    p.building_id = building_id
                    return p
    except Exception as exc:  # noqa: BLE001 - fall back to the stored row
        log.info("adapter pano lookup failed for %s/%s: %s", building_id, sweep_id, exc)
    if row is None:
        return None
    return PanoRef(sweep_id=sweep_id, image_uri=row["image_uri"], building_id=building_id)


def _load_pano(ref: PanoRef) -> np.ndarray:
    return tiling.load_image(str(adapter_factory().fetch_pano(ref)))


def _detection_ray(det: dict, nodes: dict[str, dict], rotation: Any = None) -> Ray | None:
    node = nodes.get(det.get("sweep_id"))
    bbox = det.get("bbox")
    if node is None or not bbox or det.get("tile_heading") is None:
        return None
    spec = _spec_for(det["tile_heading"], det.get("tile_pitch") or 0.0)
    return tiling.bbox_ray(bbox, spec, _pos(node), rotation)


def _rotation(building_id: str, sweep_id: str) -> Any:
    ref = _pano_ref(building_id, sweep_id)
    return ref.rotation if ref else None


def _second_view_of(det: dict) -> str | None:
    m = _SECOND_VIEW_RE.search(det.get("notes") or "")
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# tile_pano
# ---------------------------------------------------------------------------


def _cached_tiles(building_id: str, sweep_id: str) -> dict[int, Path]:
    d = _tile_cache_dir(building_id, sweep_id)
    return {int(p.stem): p for p in d.glob("*.jpg") if p.stem.isdigit()} if d.exists() else {}


def _ensure_tiles(building_id: str, sweep_id: str) -> tuple[list[TileSpec], dict[int, Path]]:
    specs = _specs()
    cached = _cached_tiles(building_id, sweep_id)
    if all(s.index in cached for s in specs):
        return specs, cached
    ref = _pano_ref(building_id, sweep_id)
    if ref is None:
        raise FileNotFoundError(f"no panorama recorded for sweep {sweep_id}")
    pano = _load_pano(ref)
    out_dir = _tile_cache_dir(building_id, sweep_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    for tile in tiling.tile_pano(pano, specs):
        path = out_dir / f"{tile.spec.index}.jpg"
        path.write_bytes(tiling.to_jpeg(tile.image, quality=90))
        cached[tile.spec.index] = path
    return specs, cached


def tile_pano(building_id: str, sweep_id: str, run_id: str | None = None, *, quiet: bool = False) -> dict:
    """Cut the sweep's panorama into perspective tiles in the local cache (never uploaded)."""
    rid = _run_id(run_id)
    if not quiet:
        _tool_call(rid, "tile_pano", {"building_id": building_id, "sweep_id": sweep_id}, building_id)
    specs, _ = _ensure_tiles(building_id, sweep_id)
    summary = {"sweep_id": sweep_id, "tiles": len(specs), "headings": [s.heading_deg for s in specs]}
    if not quiet:
        _result(rid, "tile_pano", f"Cut panorama {sweep_id} into {len(specs)} tiles.", building_id, summary)
    return summary


# ---------------------------------------------------------------------------
# detect_first_pass
# ---------------------------------------------------------------------------


def detect_first_pass(
    building_id: str, sweep_id: str, run_id: str | None = None, *, quiet: bool = False
) -> dict:
    """First pass over every tile of one sweep; candidates at or above DETECT_MIN_CONF become
    ``detections`` rows (status candidate). Marks ``panos.tiles_done``. Re-running replaces the
    sweep's unverified candidates instead of duplicating them."""
    rid = _run_id(run_id)
    s = get_settings()
    if not quiet:
        _tool_call(rid, "detect_first_pass", {"building_id": building_id, "sweep_id": sweep_id}, building_id)
    specs, cached = _ensure_tiles(building_id, sweep_id)
    db.delete(
        "detections", building_id=building_id, sweep_id=sweep_id, status="candidate", verified_by="first_pass"
    )
    rows, below = [], 0
    for spec in specs:
        image = tiling.load_image(str(cached[spec.index]))
        for c in vision_first_pass.detect_first_pass(image, run_id=rid):
            if c.confidence < s.detect_min_conf:
                below += 1
                continue
            rows.append(
                {
                    "building_id": building_id,
                    "sweep_id": sweep_id,
                    "asset_type": c.type,
                    "tile_heading": spec.heading_deg,
                    "tile_pitch": spec.pitch_deg,
                    "bbox": c.bbox,
                    "confidence": c.confidence,
                    "verified_by": "first_pass",
                    "status": "candidate",
                }
            )
    inserted = db.insert("detections", rows) if rows else []
    db.update("panos", {"tiles_done": True}, building_id=building_id, sweep_id=sweep_id)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["asset_type"]] = by_type.get(r["asset_type"], 0) + 1
    summary = {
        "sweep_id": sweep_id,
        "tiles": len(specs),
        "candidates": len(rows),
        "below_threshold": below,
        "by_type": by_type,
        "detection_ids": [r["id"] for r in inserted][:20],
    }
    if not quiet:
        found = ", ".join(f"{n} {_type_name(t)}" for t, n in sorted(by_type.items())) or "nothing"
        _result(rid, "detect_first_pass", f"First pass on {sweep_id} found {found}.", building_id, summary)
    return summary


# ---------------------------------------------------------------------------
# verify_crop
# ---------------------------------------------------------------------------


@dataclass
class _Crop:
    image: np.ndarray
    area_frac: float


def _crop_for(det: dict, tile_image: np.ndarray, pad: float = 0.15) -> _Crop:
    img = tiling.crop(tile_image, det["bbox"], pad_frac=pad)
    h, w = tile_image.shape[:2]
    return _Crop(img, img.shape[0] * img.shape[1] / float(h * w))


def _tile_image_for(det: dict) -> np.ndarray:
    building_id, sweep_id = det["building_id"], det["sweep_id"]
    spec = _spec_for(det["tile_heading"], det.get("tile_pitch") or 0.0)
    if spec.index >= 0:
        _, cached = _ensure_tiles(building_id, sweep_id)
        return tiling.load_image(str(cached[spec.index]))
    ref = _pano_ref(building_id, sweep_id)
    if ref is None:
        raise FileNotFoundError(f"no panorama recorded for sweep {sweep_id}")
    return tiling.render_tile(
        _load_pano(ref), spec.heading_deg, spec.pitch_deg, spec.fov_deg, spec.size_px
    ).image


def _store_verdict(
    det: dict, verdict: vision_verify.Verdict, crop: _Crop, verified_by: str, extra_note: str = ""
) -> dict:
    note = (BLOCKED_PREFIX if verdict.blocked_exit else "") + verdict.reason
    if verdict.person_in_crop:
        note += " Crop not stored: a person fills it."
    if extra_note:
        note = f"{note} {extra_note}".strip()
    values: dict[str, Any] = {
        "status": "confirmed" if verdict.confirmed else "rejected",
        "verified_by": verified_by,
        "notes": note,
    }
    uploaded = False
    if verdict.confirmed and not verdict.person_in_crop and crop.area_frac <= MAX_CROP_AREA_FRAC:
        values["crop_uri"] = db.upload(
            CROPS_BUCKET, f"{det['building_id']}/{det['id']}.jpg", tiling.to_jpeg(crop.image), "image/jpeg"
        )
        uploaded = True
    db.update("detections", values, id=det["id"])
    return {"crop_stored": uploaded, **values}


def verify_crop(detection_id: str, run_id: str | None = None, *, quiet: bool = False) -> dict:
    """Crop the candidate (with padding) and ask the reasoning tier: confirmed or rejected, plus
    blocked exit. Confirmed crops go to the ``crops`` bucket. Reports whether it is borderline."""
    rid = _run_id(run_id)
    s = get_settings()
    det = db.fetch_one("detections", id=detection_id)
    if det is None:
        raise ValueError(f"detection {detection_id} not found")
    building_id = det["building_id"]
    if not quiet:
        _tool_call(rid, "verify_crop", {"detection_id": detection_id}, building_id)
    crop = _crop_for(det, _tile_image_for(det))
    verdict = vision_verify.verify_crop(crop.image, det["asset_type"], run_id=rid)
    stored = _store_verdict(det, verdict, crop, "claude")
    conf = det.get("confidence") or 0.0
    borderline = verdict.confirmed and conf < s.detect_borderline_high
    summary = {
        "detection_id": detection_id,
        "asset_type": det["asset_type"],
        "confirmed": verdict.confirmed,
        "confidence": conf,
        "borderline": borderline,
        "blocked_exit": verdict.blocked_exit,
        "crop_stored": stored["crop_stored"],
        "reason": verdict.reason,
    }
    if not quiet:
        word = "Confirmed" if verdict.confirmed else "Rejected"
        msg = f"{word} {_type_name(det['asset_type'])} at {det['sweep_id']} (first pass {conf:.2f}): {verdict.reason}"
        if borderline:
            msg += " It is borderline, so a second view would help."
        _result(rid, "verify_crop", msg if msg.endswith(".") else msg + ".", building_id, summary)
    return summary


# ---------------------------------------------------------------------------
# find_second_view
# ---------------------------------------------------------------------------


def _candidate_sweeps(nodes: dict[str, dict], sweep_id: str) -> list[str]:
    """Neighbors and their neighbors on the same floor, nearest first."""
    origin = nodes[sweep_id]
    seen, ring = {sweep_id}, [sweep_id]
    found: list[str] = []
    for _ in range(2):
        nxt = []
        for s in ring:
            for m in nodes[s].get("neighbors") or []:
                if m in nodes and m not in seen:
                    seen.add(m)
                    nxt.append(m)
                    if nodes[m].get("floor") == origin.get("floor"):
                        found.append(m)
        ring = nxt
    return found


def _best_view(
    ray: Ray, nodes: dict[str, dict], candidates: list[str]
) -> tuple[str, np.ndarray, float] | None:
    """Pick the sweep with the best angular separation to a plausible target point on the ray."""
    o, d = np.asarray(ray.origin), np.asarray(ray.direction)
    best: tuple[float, str, np.ndarray, float] | None = None
    for sid in candidates:
        c = np.asarray(_pos(nodes[sid]))
        t = float(np.clip((c - o) @ d, DEPTH_GUESSES_M[0], DEPTH_GUESSES_M[-1]))
        point = o + t * d
        to_point = point - c
        dist = float(np.linalg.norm(to_point))
        if dist < 0.5:
            continue
        angle = math.degrees(math.acos(float(np.clip((to_point / dist) @ d, -1, 1))))
        if angle < SECOND_VIEW_MIN_ANGLE_DEG:
            continue
        score = -abs(angle - 75.0) - dist  # wide baseline, but not looking back at the camera
        if best is None or score > best[0]:
            best = (score, sid, point, angle)
    return None if best is None else (best[1], best[2], best[3])


def find_second_view(detection_id: str, run_id: str | None = None) -> dict:
    """Double-check a borderline detection from a neighboring sweep (spec section 9.3 step 4).

    Picks the nearby sweep with the best angle on the item, renders one tile facing it, runs the
    first pass and the verifier there, and triangulates. A match marks both detections
    ``verified_by='second_pano'``.
    """
    rid = _run_id(run_id)
    det = db.fetch_one("detections", id=detection_id)
    if det is None:
        raise ValueError(f"detection {detection_id} not found")
    building_id, sweep_id, atype = det["building_id"], det["sweep_id"], det["asset_type"]
    _tool_call(rid, "find_second_view", {"detection_id": detection_id}, building_id)
    nodes = _nodes(building_id)
    ray = _detection_ray(det, nodes, _rotation(building_id, sweep_id))
    if ray is None:
        summary = {"detection_id": detection_id, "matched": False, "reason": "detection has no usable ray"}
        _result(
            rid,
            "find_second_view",
            "This detection cannot be checked from a second view.",
            building_id,
            summary,
        )
        return summary
    candidates = [c for c in _candidate_sweeps(nodes, sweep_id) if _pano_ref(building_id, c) is not None]
    pick = _best_view(ray, nodes, candidates)
    if pick is None:
        summary = {
            "detection_id": detection_id,
            "matched": False,
            "reason": "no nearby panorama with a useful angle",
        }
        _result(
            rid,
            "find_second_view",
            f"No nearby panorama sees this {_type_name(atype)} from a useful angle.",
            building_id,
            summary,
        )
        return summary
    other, point, angle = pick
    conf = det.get("confidence") or 0.0
    _emit(
        rid,
        "decision",
        f"Borderline {_type_name(atype)} at {conf:.2f} from {sweep_id}; checking a second panorama from {other} "
        f"({round(angle)} degrees apart).",
        building_id,
        {
            "reason": "borderline confidence",
            "detection_id": detection_id,
            "sweep_id": other,
            "options": candidates[:8],
        },
    )
    other_rot = _rotation(building_id, other)
    heading, pitch = tiling.world_heading_pitch(point, _pos(nodes[other]), other_rot)
    s = get_settings()
    spec = TileSpec(-1, heading, pitch, s.tile_fov_deg, s.tile_size_px)
    ref = _pano_ref(building_id, other)
    tile = tiling.render_tile(_load_pano(ref), heading, pitch, s.tile_fov_deg, s.tile_size_px)
    best: tuple[float, Any, tuple[float, float, float]] | None = None
    for c in vision_first_pass.detect_first_pass(tile.image, run_id=rid):
        if c.type != atype:
            continue
        r2 = tiling.bbox_ray(c.bbox, spec, _pos(nodes[other]), other_rot)
        p = triangulate(ray, r2)
        if p is None:
            continue
        miss = float(np.linalg.norm(np.asarray(p) - point))
        if best is None or miss < best[0]:
            best = (miss, c, p)
    if best is None:
        summary = {
            "detection_id": detection_id,
            "matched": False,
            "second_sweep": other,
            "angle_deg": round(angle),
        }
        _result(
            rid,
            "find_second_view",
            f"The second view from {other} does not show the same {_type_name(atype)}.",
            building_id,
            summary,
        )
        return summary
    _, cand, position = best
    (row2,) = db.insert(
        "detections",
        {
            "building_id": building_id,
            "sweep_id": other,
            "asset_type": atype,
            "tile_heading": heading,
            "tile_pitch": pitch,
            "bbox": cand.bbox,
            "confidence": cand.confidence,
            "verified_by": "first_pass",
            "status": "candidate",
        },
    )
    crop = _crop_for(row2, tile.image)
    verdict = vision_verify.verify_crop(crop.image, atype, run_id=rid)
    stored = _store_verdict(row2, verdict, crop, "second_pano", f"Second view of detection {detection_id}.")
    matched = verdict.confirmed
    if matched:
        db.update("detections", {"status": "confirmed", "verified_by": "second_pano"}, id=detection_id)
    summary = {
        "detection_id": detection_id,
        "matched": matched,
        "second_sweep": other,
        "second_detection_id": row2["id"],
        "angle_deg": round(angle),
        "position": [round(v, 2) for v in position] if matched else None,
        "crop_stored": stored["crop_stored"],
    }
    msg = (
        f"Second view from {other} confirms the {_type_name(atype)}; triangulated its position."
        if matched
        else f"Second view from {other} did not confirm the {_type_name(atype)}."
    )
    _result(rid, "find_second_view", msg, building_id, summary)
    return summary


# ---------------------------------------------------------------------------
# pin_asset
# ---------------------------------------------------------------------------


def _point_ray_distance(p: np.ndarray, ray: Ray) -> float:
    o, d = np.asarray(ray.origin), np.asarray(ray.direction)
    t = max(0.0, float((p - o) @ d))
    return float(np.linalg.norm(o + t * d - p))


def _nearest_sweep(nodes: dict[str, dict], p: tuple[float, float, float]) -> dict:
    return min(nodes.values(), key=lambda n: math.dist(_pos(n), p))


def _is_triangulated(asset: dict, nodes: dict[str, dict]) -> bool:
    n = nodes.get(asset.get("sweep_id"))
    if n is None or asset.get("x") is None:
        return False
    return not (asset["x"] == n["x"] and asset["y"] == n["y"] and asset["z"] == n["z"])


def pin_asset(detection_id: str, run_id: str | None = None, *, quiet: bool = False) -> dict:
    """Pin a confirmed detection as an ``assets`` row (source 'detected'), merging duplicates:
    the same type within MERGE_RADIUS_M (or two views whose rays meet) becomes one asset with all
    the detection ids. Position: triangulated when two views exist, else the viewing sweep."""
    rid = _run_id(run_id)
    det = db.fetch_one("detections", id=detection_id)
    if det is None:
        raise ValueError(f"detection {detection_id} not found")
    building_id, atype = det["building_id"], det["asset_type"]
    if not quiet:
        _tool_call(rid, "pin_asset", {"detection_id": detection_id}, building_id)
    if det.get("status") != "confirmed":
        summary = {"detection_id": detection_id, "pinned": False, "reason": f"status is {det.get('status')}"}
        if not quiet:
            _result(
                rid, "pin_asset", f"Did not pin {detection_id}: it is not confirmed.", building_id, summary
            )
        return summary

    nodes = _nodes(building_id)
    rot_cache: dict[str, Any] = {}

    def ray_of(d: dict) -> Ray | None:
        sid = d.get("sweep_id")
        if sid not in rot_cache:
            rot_cache[sid] = _rotation(building_id, sid)
        return _detection_ray(d, nodes, rot_cache[sid])

    ray = ray_of(det)
    blocked = (det.get("notes") or "").startswith(BLOCKED_PREFIX)

    # Position from a linked second view, if any.
    position: tuple[float, float, float] | None = None
    linked_ids = [detection_id]
    partner_id = _second_view_of(det)
    partners = db.fetch_all("detections", building_id=building_id, asset_type=atype, status="confirmed")
    for other in partners:
        if other["id"] == detection_id:
            continue
        if other["id"] == partner_id or _second_view_of(other) == detection_id:
            r2 = ray_of(other)
            if ray is not None and r2 is not None:
                position = triangulate(ray, r2) or position
            linked_ids.append(other["id"])

    existing = db.fetch_all("assets", building_id=building_id, type=atype, source="detected")
    for a in existing:
        if detection_id in (a.get("detection_ids") or []):
            summary = {"detection_id": detection_id, "pinned": True, "asset_id": a["id"], "merged": True}
            if not quiet:
                _result(
                    rid,
                    "pin_asset",
                    f"{_type_name(atype)} {detection_id} is already pinned.",
                    building_id,
                    summary,
                )
            return summary

    target = None
    for a in existing:
        apos = np.asarray([a["x"], a["y"], a["z"]], float) if a.get("x") is not None else None
        if position is not None and apos is not None and _is_triangulated(a, nodes):
            if math.dist(position, apos) <= MERGE_RADIUS_M:
                target = a
                break
            continue
        if ray is not None and apos is not None and _is_triangulated(a, nodes):
            if _point_ray_distance(apos, ray) <= MERGE_RADIUS_M:
                target = a
                break
            continue
        # Untriangulated asset: do any of its views meet this one?
        for did in a.get("detection_ids") or []:
            od = next((p for p in partners if p["id"] == did), None)
            r2 = ray_of(od) if od else None
            if ray is not None and r2 is not None:
                p = triangulate(ray, r2)
                if p is not None:
                    target, position = a, position or p
                    break
        if target is not None:
            break
        if position is not None and apos is not None and math.dist(position, apos) <= MERGE_RADIUS_M:
            target = a
            break

    if position is None and target is not None and _is_triangulated(target, nodes):
        position = (target["x"], target["y"], target["z"])
    if position is not None:
        near = _nearest_sweep(nodes, position)
        values = {
            "x": position[0],
            "y": position[1],
            "z": position[2],
            "sweep_id": near["sweep_id"],
            "floor": near.get("floor"),
        }
        where = near
    else:
        view = nodes.get(det["sweep_id"]) or {}
        values = {
            "x": view.get("x"),
            "y": view.get("y"),
            "z": view.get("z"),
            "sweep_id": det["sweep_id"],
            "floor": view.get("floor"),
        }
        where = view
    label = f"near {where['label']}" if where.get("label") else None

    if target is not None:
        ids = list(dict.fromkeys([*(target.get("detection_ids") or []), *linked_ids]))
        flags = sorted(set(target.get("flags") or []) | ({"blocked_exit"} if blocked else set()))
        update = {"detection_ids": ids, "flags": flags, "verified": True}
        if position is not None:
            update.update(values)
            update["label"] = label or target.get("label")
        db.update("assets", update, id=target["id"])
        asset_id, merged = target["id"], True
    else:
        (row,) = db.insert(
            "assets",
            {
                "building_id": building_id,
                "type": atype,
                "label": label,
                "source": "detected",
                "detection_ids": linked_ids,
                "verified": True,
                "flags": ["blocked_exit"] if blocked else [],
                **values,
            },
        )
        asset_id, merged = row["id"], False
    summary = {
        "detection_id": detection_id,
        "pinned": True,
        "asset_id": asset_id,
        "merged": merged,
        "triangulated": position is not None,
        "sweep_id": values["sweep_id"],
        "blocked_exit": blocked,
    }
    if not quiet:
        how = "merged with an existing" if merged else "pinned a new"
        where_txt = (
            "triangulated from two views" if position is not None else f"at sweep {values['sweep_id']}"
        )
        _result(
            rid, "pin_asset", f"{how.capitalize()} {_type_name(atype)}, {where_txt}.", building_id, summary
        )
    return summary
