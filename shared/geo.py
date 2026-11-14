"""Small geographic helpers used by census Outside and live responder selection."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8  # IUGG mean Earth radius


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters between two WGS84 points given in degrees."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def within_geofence(
    lat: float | None,
    lng: float | None,
    center_lat: float | None,
    center_lng: float | None,
    radius_m: float,
) -> bool:
    """True when the point is within ``radius_m`` of the center. Missing coordinates are outside."""
    if lat is None or lng is None or center_lat is None or center_lng is None:
        return False
    return haversine_m(lat, lng, center_lat, center_lng) <= radius_m


def nearest(
    lat: float, lng: float, points: list[dict], *, lat_key: str = "lat", lng_key: str = "lng"
) -> tuple[dict, float] | None:
    """The point in ``points`` closest to (lat, lng) and its distance in meters, or None if empty.

    Points missing coordinates are skipped.
    """
    best: tuple[dict, float] | None = None
    for p in points:
        plat, plng = p.get(lat_key), p.get(lng_key)
        if plat is None or plng is None:
            continue
        d = haversine_m(lat, lng, plat, plng)
        if best is None or d < best[1]:
            best = (p, d)
    return best
