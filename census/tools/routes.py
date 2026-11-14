"""Precompute camera routes for the live path (docs/CONTRACTS.md section 4, census/DESIGN.md).

For a camera, the route from its sweep to the nearest AED, exit, extinguisher and naloxone that
exist today (proposed assets are excluded: the live path only sends people to real equipment).
Writes ``camera_routes`` with ``audio_url = NULL``; agent/io/tts.py renders the audio.

``directions`` holds the landmark phrase only, without the distance, because the CARDIAC speaker
template already reads "{aed_distance} meters, {aed_directions}". ``distance_m`` is the walking
distance in meters along ``path``.
"""

from __future__ import annotations

from census.core.directions import describe_route
from census.core.graph import shortest_route
from census.tools import db
from census.tools.events import result, tool_call, warning
from census.tools.mapper import load

AGENT = "mapper"
TARGETS = ("aed", "exit", "extinguisher", "naloxone")


def precompute_camera_routes(camera_id: str) -> None:
    tool_call(AGENT, "precompute_camera_routes", {"camera_id": camera_id})
    cam = db.fetch_one("cameras", filters=[("eq", "id", camera_id)])
    if cam is None:
        raise ValueError(f"camera {camera_id} not found")
    building_id = cam.get("building_id")
    loaded = load(building_id)
    src = cam.get("sweep_id")
    if src not in loaded.graph:
        warning(AGENT, "camera_off_twin", f"Camera {camera_id} is not on a scan position; no routes written.",
                building_id, {"camera_id": camera_id, "sweep_id": src})
        raise ValueError(f"camera {camera_id} sweep {src!r} is not in the twin")

    rows, missing = [], []
    for target in TARGETS:
        assets = [a for a in loaded.assets if a.get("type") == target and a.get("sweep_id") in loaded.graph]
        route = shortest_route(loaded.graph, src, [a["sweep_id"] for a in assets])
        if route is None:
            missing.append(target)
            continue
        dest = next(a for a in assets if a["sweep_id"] == route.path[-1])
        rows.append({"camera_id": camera_id, "target": target, "path": route.path,
                     "distance_m": round(route.distance_m, 1),
                     "directions": describe_route(loaded.graph, route, dest.get("label")),
                     "audio_url": None})
    if rows:
        db.upsert("camera_routes", rows, on_conflict="camera_id,target")
    if missing:
        db.delete("camera_routes", filters=[("eq", "camera_id", camera_id), ("in", "target", missing)])
    aed = next((r for r in rows if r["target"] == "aed"), None)
    message = (f"Camera {camera_id}: nearest AED is {round(aed['distance_m'])} meters away, {aed['directions']}."
               if aed else f"Camera {camera_id}: no reachable AED visible in the scan.")
    result(AGENT, "precompute_camera_routes", message, building_id,
           {"camera_id": camera_id, "targets": [r["target"] for r in rows], "missing": missing})
