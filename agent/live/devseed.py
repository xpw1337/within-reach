"""In-memory rows for local runs with no Supabase project (``MemoryStore``).

LOCAL DEV FIXTURE, NOT MEASURED. The camera and building come from ``demo/fallback/building.json``
(itself a fixture). The AED route is a placeholder until ``census.tools.routes`` writes real
``camera_routes``: its distance and wording are the spec's own demo-script example. The responders
are fictional, with 555 numbers. None of this reaches the dashboard: it exists only in process
memory when ``SUPABASE_URL`` is unset.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
FALLBACK = REPO_ROOT / "demo" / "fallback" / "building.json"
BUILDING_ID = "00000000-0000-4000-8000-000000000001"

FIXTURE_AED_ROUTE = {"distance_m": 14.0, "directions": "left of the elevators"}  # spec section 11 example


def dev_rows(now: float) -> dict[str, list[dict[str, Any]]]:
    data: dict[str, Any] = {}
    if FALLBACK.exists():
        data = json.loads(FALLBACK.read_text(encoding="utf-8"))
    b = data.get("building") or {}
    cam = data.get("camera") or {"id": "cam-lobby-1", "sweep_id": "s1", "floor": 0, "landmark": "east elevators"}
    building = {"id": BUILDING_ID, "name": b.get("name"), "address": b.get("address"), "lat": b.get("lat"),
                "lng": b.get("lng"), "geofence_m": 60, "vexcel": data.get("vexcel"), "ems_door": None,
                "monitoring_callback": None}
    camera = {**cam, "building_id": BUILDING_ID, "has_speaker": True}
    routes = [{"camera_id": camera["id"], "target": "aed", "path": [], "audio_url": None, **FIXTURE_AED_ROUTE}]
    lat, lng = building["lat"] or 0.0, building["lng"] or 0.0

    def person(i: int, role: str, cpr: bool, callable_: bool) -> dict[str, Any]:
        return {"id": f"00000000-0000-4000-8000-00000000010{i}", "name": f"Fixture responder {i}",
                "phone": f"+1555010000{i}", "callable": callable_, "consent_calls": callable_,
                "cpr_trained": cpr, "role": role, "building_id": BUILDING_ID, "last_lat": lat,
                "last_lng": lng, "last_seen_at": now, "consent_location": True, "on_duty": True}

    responders = [person(1, "staff", True, True), person(2, "public", False, True)]
    responders += [person(i, "public", i % 2 == 0, False) for i in range(3, 7)]
    log.warning("using the in-memory LOCAL DEV FIXTURE (no SUPABASE_URL): routes are not measured")
    return {"cameras": [camera], "routes": routes, "buildings": [building], "responders": responders}
