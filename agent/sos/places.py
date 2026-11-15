"""AEDs and fire extinguishers near a point, from OpenStreetMap (Overpass API) plus pins the team
added on the dashboard. Works for any location; coverage is whatever OpenStreetMap has mapped.

OSM tags: ``emergency=defibrillator`` (AED) and ``emergency=fire_extinguisher``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from agent.sos.geo import haversine_m
from agent.sos.settings import SosSettings

log = logging.getLogger(__name__)

KINDS = {"aed": "defibrillator", "extinguisher": "fire_extinguisher"}
CACHE_S = 6 * 3600


def overpass_query(lat: float, lng: float, radius_m: float) -> str:
    parts = "".join(
        f'node["emergency"="{tag}"](around:{int(radius_m)},{lat:.6f},{lng:.6f});'
        f'way["emergency"="{tag}"](around:{int(radius_m)},{lat:.6f},{lng:.6f});'
        for tag in KINDS.values()
    )
    return f"[out:json][timeout:25];({parts});out center tags;"


def parse_overpass(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    by_tag = {v: k for k, v in KINDS.items()}
    for el in data.get("elements") or []:
        tags = el.get("tags") or {}
        kind = by_tag.get(tags.get("emergency"))
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lng = el.get("lon", (el.get("center") or {}).get("lon"))
        if kind is None or lat is None or lng is None:
            continue
        where = tags.get("defibrillator:location") or tags.get("location") or tags.get("description")
        name = tags.get("name") or tags.get("operator")
        label = ", ".join(x for x in (name, where) if x) or ("AED" if kind == "aed" else "Fire extinguisher")
        out.append({
            "id": f"osm-{el.get('type', 'node')}-{el.get('id')}",
            "kind": kind,
            "lat": float(lat),
            "lng": float(lng),
            "label": label,
            "indoor": tags.get("indoor") == "yes" or "level" in tags,
            "level": tags.get("level"),
            "access": tags.get("access"),
            "hours": tags.get("opening_hours"),
            "source": "openstreetmap",
        })
    return out


class Places:
    """OpenStreetMap lookups with a cache that survives restarts (``cache`` is saved by the hub).

    Public Overpass servers are often at capacity, so every mirror is asked at once and the first
    good answer wins; results are kept for ``CACHE_S`` and reused when every mirror fails.
    """

    def __init__(self, settings: SosSettings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client
        # "lat,lng" rounded to ~100 m -> {"t": epoch seconds, "items": [...]}
        self.cache: dict[str, dict[str, Any]] = {}

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30, headers={"User-Agent": self.s.user_agent})
        return self._client

    @staticmethod
    def key(lat: float, lng: float) -> str:
        return f"{lat:.3f},{lng:.3f}"

    def cached(self, lat: float, lng: float) -> list[dict[str, Any]] | None:
        hit = self.cache.get(self.key(lat, lng))
        return None if hit is None else list(hit["items"])

    async def osm(self, lat: float, lng: float, *, max_age_s: float = CACHE_S) -> list[dict[str, Any]]:
        """OpenStreetMap AEDs and extinguishers within ``places_radius_m``.

        Fresh cache first; else every mirror at once; else a stale cache; else raises."""
        if self.s.offline:
            return []
        k = self.key(lat, lng)
        hit = self.cache.get(k)
        if hit and time.time() - hit["t"] < max_age_s:
            return list(hit["items"])
        q = overpass_query(lat, lng, self.s.places_radius_m)
        http = await self._http()

        async def ask(url: str) -> list[dict[str, Any]]:
            r = await http.get(url, params={"data": q})
            r.raise_for_status()
            return parse_overpass(r.json())

        tasks = [asyncio.ensure_future(ask(u)) for u in self.s.overpass_urls]
        errors: list[str] = []
        try:
            for fut in asyncio.as_completed(tasks):
                try:
                    found = await fut
                except Exception as exc:  # noqa: BLE001 - the next mirror may answer
                    errors.append(f"{type(exc).__name__}: {exc}"[:120])
                    continue
                self.cache[k] = {"t": time.time(), "items": found}
                return found
        finally:
            for t in tasks:
                t.cancel()
        if hit:
            log.warning("OpenStreetMap unreachable, using a cached lookup (%s)", "; ".join(errors))
            return list(hit["items"])
        raise RuntimeError("OpenStreetMap lookup failed: " + "; ".join(errors))

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def nearest(items: list[dict[str, Any]], lat: float, lng: float) -> list[dict[str, Any]]:
    """Copies of ``items`` with ``distance_m`` from (lat, lng), nearest first."""
    out = [{**it, "distance_m": round(haversine_m(lat, lng, it["lat"], it["lng"]), 1)} for it in items]
    return sorted(out, key=lambda it: it["distance_m"])
