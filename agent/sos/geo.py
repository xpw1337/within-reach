"""Small geodesy helpers (WGS84 sphere approximation, fine at walking distances)."""

from __future__ import annotations

import itertools
import math

EARTH_R = 6_371_000.0
COMPASS = ("north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west")


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from true north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass_word(bearing: float) -> str:
    return COMPASS[round(bearing / 45) % 8]


def offset(lat: float, lng: float, bearing: float, dist_m: float) -> tuple[float, float]:
    """Point ``dist_m`` from (lat, lng) along ``bearing``."""
    d = dist_m / EARTH_R
    b = math.radians(bearing)
    p1, l1 = math.radians(lat), math.radians(lng)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def circle(lat: float, lng: float, radius_m: float, n: int = 16) -> list[tuple[float, float]]:
    """Closed polygon approximating a circle, as (lat, lng) points."""
    pts = [offset(lat, lng, 360 * i / n, radius_m) for i in range(n)]
    return [*pts, pts[0]]


def segment_distance_m(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from point p to segment a-b (local flat projection)."""
    lat0 = math.radians(p[0])
    kx = math.cos(lat0) * EARTH_R * math.pi / 180
    ky = EARTH_R * math.pi / 180

    def xy(q: tuple[float, float]) -> tuple[float, float]:
        return (q[1] - p[1]) * kx, (q[0] - p[0]) * ky

    ax, ay = xy(a)
    bx, by = xy(b)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx, cy)


def path_hits_circle(path: list[tuple[float, float]], center: tuple[float, float], radius_m: float) -> bool:
    if len(path) == 1:
        return haversine_m(*path[0], *center) <= radius_m
    return any(segment_distance_m(center, a, b) <= radius_m for a, b in itertools.pairwise(path))


def decode_polyline(encoded: str, precision: int = 6) -> list[tuple[float, float]]:
    """Decode a Google-style encoded polyline (Valhalla uses precision 6)."""
    coords: list[tuple[float, float]] = []
    index = lat = lng = 0
    factor = 10**precision
    while index < len(encoded):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += delta
            else:
                lng += delta
        coords.append((lat / factor, lng / factor))
    return coords
