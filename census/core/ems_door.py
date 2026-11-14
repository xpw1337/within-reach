"""Pick the EMS door, staging spot and nearest hydrant (spec section 9.7). Pure.

The door is the entrance with ambulance access closest to the building's highest-risk zone.
"Closest" is measured on the scan's walking graph when an entrance is linked to a scan position
(its ``sweep_id``): the tools layer passes, per entrance, the mean walking meters from that
position to the risk-zone positions. Without that link the choice falls back to the entrance
nearest an ambulance parking spot, then to the first listed entrance, and the reason says so.
"""

from __future__ import annotations

import math
from typing import Any

EARTH_RADIUS_M = 6_371_000.0


def _haversine_m(a: dict, b: dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _has_point(p: dict) -> bool:
    return p.get("lat") is not None and p.get("lng") is not None


def _nearest(origin: dict, points: list[dict]) -> dict | None:
    pts = [p for p in points if _has_point(p)]
    if not pts or not _has_point(origin):
        return None
    best = min(pts, key=lambda p: _haversine_m(origin, p))
    return {"lat": best["lat"], "lng": best["lng"], "desc": best.get("desc"),
            "distance_m": round(_haversine_m(origin, best), 1)}


def _desc(e: dict, i: int) -> str:
    return e.get("desc") or f"entrance {i + 1}"


def pick_ems_door(
    entrances: list[dict[str, Any]],
    ambulance_parking: list[dict[str, Any]],
    hydrants: list[dict[str, Any]],
    walk_m_to_risk: dict[int, float] | None = None,
    risk_zone: str | None = None,
) -> dict[str, Any] | None:
    """The ``buildings.ems_door`` value: ``{lat, lng, desc, reason, method, staging, hydrant}``.

    ``walk_m_to_risk`` maps an index into ``entrances`` to the mean walking meters from that
    entrance's scan position to the risk zone (described by ``risk_zone``). Returns None when
    there are no entrances.
    """
    if not entrances:
        return None
    indexed = list(enumerate(entrances))
    access = [(i, e) for i, e in indexed if e.get("ambulance_access") is True]
    access_note = "with ambulance access"
    if not access:
        access = [(i, e) for i, e in indexed if e.get("ambulance_access") is not False]
        access_note = "(ambulance access not marked in the outside data)"
    if not access:
        access = indexed
        access_note = "(no entrance is marked with ambulance access)"

    walk = {i: d for i, d in (walk_m_to_risk or {}).items() if any(i == j for j, _ in access)}
    if walk:
        idx = min(walk, key=lambda i: (walk[i], i))
        method = "walking_graph"
        reason = (f"Entrance {access_note} closest on foot to the highest-risk zone"
                  f"{f' ({risk_zone})' if risk_zone else ''}: about {round(walk[idx])} m on average.")
    else:
        parked = [(i, e, _nearest(e, ambulance_parking)) for i, e in access]
        parked = [(i, e, p) for i, e, p in parked if p is not None]
        if parked:
            idx, _, p = min(parked, key=lambda t: (t[2]["distance_m"], t[0]))
            method = "nearest_parking"
            reason = (f"Entrance {access_note} nearest to ambulance parking (about {round(p['distance_m'])} m); "
                      "entrances are not linked to scan positions, so distance to the risk zone was not measured.")
        else:
            idx = access[0][0]
            method = "first_listed"
            reason = (f"First entrance {access_note}; no position or parking data to compare entrances.")

    door = entrances[idx]
    return {
        "lat": door.get("lat"), "lng": door.get("lng"), "desc": _desc(door, idx),
        "reason": reason, "method": method, "entrance_index": idx, "sweep_id": door.get("sweep_id"),
        "staging": _nearest(door, ambulance_parking),
        "hydrant": _nearest(door, hydrants),
    }
