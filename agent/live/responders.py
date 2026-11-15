"""Responder eligibility, priority, waves and roles (spec section 9.10). Pure functions.

- Eligible: consent (location) + on duty + seen in the last 10 minutes + inside the building
  geofence.
- Two pools: on-duty staff and security of the building get the ungated staff alert
  (``staff_to_alert``, dispatch role ``staff``: go to the person); every other eligible responder
  is in the helper pool for the waves.
- Nearest first (team lead, 2026-11-14): inside each pool the order is distance to the incident
  (the camera's lat/lng, else the building's), then CPR-trained first for cardiac, then id. With
  no incident coordinates the order is the earlier one: staff, security, tenants, then public;
  CPR-trained first for cardiac; then id. A responder with no position sorts last.
- Waves of ``WAVE_SIZE``; nobody is sent twice. The phone is called only when the responder is
  ``callable`` and gave ``consent_calls``.
- Roles (team lead, 2026-11-14, replaces "first accept = patient, second = AED runner"): when an
  AED route is mapped for the camera (a ``camera_routes`` row with target ``aed``), the first
  helper accept is the AED runner (gets the AED, then brings it to the person) and the second
  goes to the person (``patient``). With no AED route the first accept is ``patient`` and there is
  no AED runner. Once the roles are filled, everyone else is released.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

ROLE_RANK = {"staff": 0, "security": 1, "tenant": 2, "public": 3}
STAFF_ROLES = ("staff", "security")
# Roles a helper (wave) accept can take, in assignment order (team lead, 2026-11-14).
ROLE_ORDER_WITH_AED = ("aed_runner", "patient")
ROLE_ORDER_NO_AED = ("patient",)
HELPER_ROLES = ("aed_runner", "patient")
Origin = tuple[float, float]


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


def incident_origin(camera: Mapping[str, Any] | None, building: Mapping[str, Any] | None) -> Origin | None:
    """Where the incident is: the camera's lat/lng when set, else the building's, else None."""
    for place in (camera or {}, building or {}):
        lat, lng = place.get("lat"), place.get("lng")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    return None


def distance_to_origin_m(responder: Mapping[str, Any], origin: Origin) -> float | None:
    lat, lng = responder.get("last_lat"), responder.get("last_lng")
    if lat is None or lng is None:
        return None
    return haversine_m(float(lat), float(lng), origin[0], origin[1])


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


def priority_key(
    responder: Mapping[str, Any], building: Mapping[str, Any], cardiac: bool, origin: Origin | None = None
) -> tuple:
    """Nearest first when the incident has coordinates, else the role order (module docstring)."""
    cpr_rank = 0 if (cardiac and responder.get("cpr_trained")) else 1
    if origin is not None:
        distance = distance_to_origin_m(responder, origin)
        return (math.inf if distance is None else distance, cpr_rank, str(responder.get("id")))
    role_rank = ROLE_RANK.get(responder.get("role") or "public", len(ROLE_RANK))
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
    origin: Origin | None = None,
) -> list[Mapping[str, Any]]:
    excluded = set(exclude_ids)
    pool = [
        r
        for r in responders
        if r.get("id") not in excluded and is_eligible(r, building, now, seen_window_s)
    ]
    return sorted(pool, key=lambda r: priority_key(r, building, cardiac, origin))


def next_wave(
    responders: Iterable[Mapping[str, Any]],
    building: Mapping[str, Any],
    now: float,
    *,
    cardiac: bool,
    wave_size: int,
    seen_window_s: float,
    already_sent: Iterable[str],
    origin: Origin | None = None,
) -> list[Mapping[str, Any]]:
    """The next ``wave_size`` helpers by priority who have not been sent a dispatch yet. The
    building's staff alert targets are never in a wave: they are the staff pool."""
    responders = list(responders)
    staff_ids = [r.get("id") for r in staff_to_alert(responders, building)]
    ranked = rank_eligible(
        responders, building, now, cardiac=cardiac, seen_window_s=seen_window_s,
        exclude_ids=[*already_sent, *staff_ids], origin=origin,
    )
    return ranked[: max(0, int(wave_size))]


def staff_to_alert(
    responders: Iterable[Mapping[str, Any]],
    building: Mapping[str, Any],
    *,
    origin: Origin | None = None,
    cardiac: bool = False,
) -> list[Mapping[str, Any]]:
    """On-duty staff and security of the incident's building (app alert, no call). All of them are
    alerted; the order is nearest first when the incident has coordinates."""
    out = [
        r
        for r in responders
        if r.get("role") in STAFF_ROLES
        and r.get("on_duty")
        and building.get("id") is not None
        and r.get("building_id") == building.get("id")
    ]
    if origin is not None:
        return sorted(out, key=lambda r: priority_key(r, building, cardiac, origin))
    return sorted(out, key=lambda r: (ROLE_RANK[r["role"]], str(r.get("id"))))


def aed_route_mapped(routes: Mapping[str, Any] | None) -> bool:
    """A ``camera_routes`` row with target ``aed`` exists for the incident's camera."""
    return bool((routes or {}).get("aed"))


def role_order(routes: Mapping[str, Any] | None) -> tuple[str, ...]:
    return ROLE_ORDER_WITH_AED if aed_route_mapped(routes) else ROLE_ORDER_NO_AED


def open_role(roles: Mapping[str, Any], routes: Mapping[str, Any] | None) -> str | None:
    """The role the next helper accept gets. With an AED route: AED runner, then patient. Without
    one: patient only. None once the roles are filled."""
    for role in role_order(routes):
        if not roles.get(role):
            return role
    return None


def roles_filled(roles: Mapping[str, Any], routes: Mapping[str, Any] | None) -> bool:
    return open_role(roles, routes) is None
