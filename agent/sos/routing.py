"""Walking routes: Valhalla pedestrian routing on OpenStreetMap, with the fire zone excluded.

Short hops (under ``direct_route_m``, typically the same building) get a straight heading instead:
street routing snaps both ends to the nearest footpath, which is meaningless indoors. If Valhalla is
unreachable the route falls back to a straight line, marked ``source: "direct"``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from agent.sos.geo import (
    bearing_deg,
    circle,
    compass_word,
    decode_polyline,
    haversine_m,
    path_hits_circle,
)
from agent.sos.settings import SosSettings

log = logging.getLogger(__name__)

WALK_MPS = 1.4  # typical walking speed, for the straight-line estimate only
Point = tuple[float, float]


def direct_leg(a: Point, b: Point, *, note: str | None = None) -> dict[str, Any]:
    d = haversine_m(*a, *b)
    heading = bearing_deg(*a, *b)
    text = f"Head {compass_word(heading)} for about {max(1, round(d))} m"
    steps = [{"text": text, "distance_m": round(d, 1)}]
    if note:
        steps.append({"text": note, "distance_m": 0})
    return {
        "geometry": [list(a), list(b)],
        "distance_m": round(d, 1),
        "duration_s": round(d / WALK_MPS),
        "steps": steps,
        "bearing_deg": round(heading),
        "source": "direct",
    }


class Router:
    def __init__(self, settings: SosSettings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=6, headers={"User-Agent": self.s.user_agent})
        return self._client

    async def route(self, a: Point, b: Point, fire: dict[str, Any] | None = None) -> dict[str, Any]:
        """A walking leg from a to b. ``fire`` is ``{lat, lng, radius_m}``; the route avoids it when
        neither end is inside it, and says when it cannot."""
        zone = (fire["lat"], fire["lng"]) if fire else None
        radius = float(fire.get("radius_m") or self.s.fire_radius_m) if fire else 0.0
        a_in = zone is not None and haversine_m(*a, *zone) <= radius
        b_in = zone is not None and haversine_m(*b, *zone) <= radius
        if haversine_m(*a, *b) < self.s.direct_route_m or self.s.offline:
            leg = direct_leg(a, b)
        else:
            exclude = zone is not None and not a_in and not b_in
            leg = await self._valhalla(a, b, circle(*zone, radius) if exclude and zone else None)
            if leg is None:
                leg = direct_leg(a, b)
        crosses = zone is not None and path_hits_circle([tuple(p) for p in leg["geometry"]], zone, radius)
        leg["avoids_fire"] = bool(zone is not None and not crosses)
        leg["fire_on_route"] = bool(crosses)
        if b_in:
            leg["steps"].append({"text": "The fire is at this spot: approach with the extinguisher, "
                                         "stay low and keep your exit behind you", "distance_m": 0})
        elif crosses:
            leg["steps"].insert(0, {"text": "Fire on the direct path: go around it, keep your distance",
                                    "distance_m": 0})
        return leg

    async def _valhalla(self, a: Point, b: Point, exclude: list[Point] | None) -> dict[str, Any] | None:
        body: dict[str, Any] = {
            "locations": [{"lat": a[0], "lon": a[1]}, {"lat": b[0], "lon": b[1]}],
            "costing": "pedestrian",
            "directions_options": {"units": "kilometers"},
        }
        if exclude:
            body["exclude_polygons"] = [[[lng, lat] for lat, lng in exclude]]
        try:
            http = await self._http()
            r = await http.post(f"{self.s.valhalla_url}/route", json=body)
            if r.status_code >= 400:
                log.warning("valhalla %d: %s", r.status_code, r.text[:200])
                return None
            trip = r.json()["trip"]
            leg = trip["legs"][0]
            geometry = [list(p) for p in decode_polyline(leg["shape"], 6)]
            steps = [{"text": m.get("instruction", ""), "distance_m": round(float(m.get("length", 0)) * 1000, 1)}
                     for m in leg.get("maneuvers") or []]
            summary = trip.get("summary") or {}
            return {
                "geometry": geometry,
                "distance_m": round(float(summary.get("length", 0)) * 1000, 1),
                "duration_s": round(float(summary.get("time", 0))),
                "steps": steps,
                "bearing_deg": round(bearing_deg(*a, *b)),
                "source": "valhalla",
            }
        except Exception as exc:  # noqa: BLE001 - fall back to a straight line
            log.warning("valhalla route failed: %s", exc)
            return None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
