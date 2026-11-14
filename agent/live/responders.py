"""Responder eligibility, priority, waves and roles (spec section 9.10). Pure functions.

- Eligible: consent (location) + on duty + seen in the last 10 minutes + inside the building
  geofence.
- Priority: staff, security, tenants, then opted-in public; CPR-trained first for cardiac.
  Ties are broken by distance to the building, then by id, so waves are deterministic.
- Waves of ``WAVE_SIZE``; nobody is sent twice. The phone is called only when the responder is
  ``callable`` and gave ``consent_calls``.
- Roles: first accept is the patient, second the AED runner, everyone else is released.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

ROLE_RANK = {"staff": 0, "security": 1, "tenant": 2, "public": 3}
STAFF_ROLES = ("staff", "security")
ROLE_ORDER = ("patient", "aed_runner")


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371008.8  # mean Earth radius in meters
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


try:  # shared.geo is the shared helper once it exists (shared/DESIGN.md)
    from shared.geo import haversine_m  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - fallback until shared/geo.py lands
    haversine_m = _haversine_m


def to_epoch(value: Any) -> float | None:
    """Accept epoch seconds, a datetime, or an ISO 8601 string (as the database returns it)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    return None


def distance_to_building_m(responder: Mapping[str, Any], building: Mapping[str, Any]) -> float | None:
    lat, lng = responder.get("last_lat"), responder.get("last_lng")
    blat, blng = building.get("lat"), building.get("lng")
    if None in (lat, lng, blat, blng):
        return None
    return haversine_m(float(lat), float(lng), float(blat), float(blng))


def in_geofence(responder: Mapping[str, Any], building: Mapping[str, Any]) -> bool:
    """Inside the building geofence (``buildings.geofence_m``, schema default 60 m).

    When the building has no coordinates, a responder registered to that building counts as inside.
    """
    distance = distance_to_building_m(responder, building)
    if distance is not None:
        geofence = building.get("geofence_m")
        geofence = 60 if geofence is None else geofence  # schema default (0001_init.sql)
        return distance <= float(geofence)
    if building.get("lat") is None or building.get("lng") is None:
        return bool(building.get("id")) and responder.get("building_id") == building.get("id")
    return False


def is_eligible(
    responder: Mapping[str, Any], building: Mapping[str, Any], now: float, seen_window_s: float
) -> bool:
    if not responder.get("consent_location"):
        return False
    if not responder.get("on_duty"):
        return False
    seen = to_epoch(responder.get("last_seen_at"))
    if seen is None or now - seen >= seen_window_s:
        return False
    return in_geofence(responder, building)


def can_call(responder: Mapping[str, Any]) -> bool:
    return bool(responder.get("callable") and responder.get("consent_calls") and responder.get("phone"))


def priority_key(responder: Mapping[str, Any], building: Mapping[str, Any], cardiac: bool) -> tuple:
    role_rank = ROLE_RANK.get(responder.get("role") or "public", len(ROLE_RANK))
    cpr_rank = 0 if (cardiac and responder.get("cpr_trained")) else 1
    distance = distance_to_building_m(responder, building)
    return (role_rank, cpr_rank, math.inf if distance is None else distance, str(responder.get("id")))


def rank_eligible(
    responders: Iterable[Mapping[str, Any]],
    building: Mapping[str, Any],
    now: float,
    *,
    cardiac: bool,
    seen_window_s: float,
    exclude_ids: Iterable[str] = (),
) -> list[Mapping[str, Any]]:
    excluded = set(exclude_ids)
    pool = [
        r
        for r in responders
        if r.get("id") not in excluded and is_eligible(r, building, now, seen_window_s)
    ]
    return sorted(pool, key=lambda r: priority_key(r, building, cardiac))


def next_wave(
    responders: Iterable[Mapping[str, Any]],
    building: Mapping[str, Any],
    now: float,
    *,
    cardiac: bool,
    wave_size: int,
    seen_window_s: float,
    already_sent: Iterable[str],
) -> list[Mapping[str, Any]]:
    """The next ``wave_size`` responders by priority who have not been sent a wave dispatch yet."""
    ranked = rank_eligible(
        responders, building, now, cardiac=cardiac, seen_window_s=seen_window_s, exclude_ids=already_sent
    )
    return ranked[: max(0, int(wave_size))]


def staff_to_alert(
    responders: Iterable[Mapping[str, Any]], building: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    """On-duty staff and security of the incident's building (app alert, no call)."""
    out = [
        r
        for r in responders
        if r.get("role") in STAFF_ROLES
        and r.get("on_duty")
        and building.get("id") is not None
        and r.get("building_id") == building.get("id")
    ]
    return sorted(out, key=lambda r: (ROLE_RANK[r["role"]], str(r.get("id"))))


def open_role(roles: Mapping[str, Any]) -> str | None:
    """The role the next accept gets: patient first, then AED runner, then none."""
    for role in ROLE_ORDER:
        if not roles.get(role):
            return role
    return None


def roles_filled(roles: Mapping[str, Any]) -> bool:
    return open_role(roles) is None
