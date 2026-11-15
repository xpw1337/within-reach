"""Settings for the live SOS path, read from the environment (root ``.env`` is loaded if present)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

try:
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    pass


def _f(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _opt(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else None


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name, "").strip()
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()] if raw else default


@dataclass
class SosSettings:
    # Seconds a responder has to accept before the alert moves to the next nearest person.
    accept_timeout_s: float = field(default_factory=lambda: _f("ACCEPT_TIMEOUT_SECONDS", 20))
    # When the alert also rings the responder's phone, they get longer to answer.
    accept_timeout_call_s: float = field(default_factory=lambda: _f("ACCEPT_TIMEOUT_CALL_SECONDS", 45))
    # A responder with the app closed is still phoned if their location is at most this old.
    call_reach_s: float = field(default_factory=lambda: _f("CALL_REACH_SECONDS", 1800))
    # A connected phone that has not sent anything for this long is not alerted.
    responder_stale_s: float = field(default_factory=lambda: _f("RESPONDER_STALE_SECONDS", 120))
    # Search radius for AEDs and extinguishers around the incident.
    places_radius_m: float = field(default_factory=lambda: _f("PLACES_RADIUS_M", 1000))
    # Grab the AED on the way only if it adds at most this much walking.
    aed_max_detour_m: float = field(default_factory=lambda: _f("AED_MAX_DETOUR_M", 400))
    # Danger zone kept clear around a fire.
    fire_radius_m: float = field(default_factory=lambda: _f("FIRE_RADIUS_M", 15))
    # Below this straight-line distance, give a direct heading instead of a street route.
    direct_route_m: float = field(default_factory=lambda: _f("DIRECT_ROUTE_M", 60))
    # Optional fixed camera position (otherwise the dashboard sends the laptop's location).
    camera_lat: float | None = field(default_factory=lambda: _opt("CAMERA_LAT"))
    camera_lng: float | None = field(default_factory=lambda: _opt("CAMERA_LNG"))
    camera_label: str = field(default_factory=lambda: os.environ.get("CAMERA_LABEL", "").strip())
    valhalla_url: str = field(
        default_factory=lambda: os.environ.get("VALHALLA_URL", "https://valhalla1.openstreetmap.de").rstrip("/"))
    overpass_urls: list[str] = field(default_factory=lambda: _list("OVERPASS_URLS", [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]))
    nominatim_url: str = field(
        default_factory=lambda: os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/"))
    # Generic client name for the public OpenStreetMap services (they ask for one).
    user_agent: str = "within-reach-demo/1.0"
    # Turn off every outside network call (tests, offline demos).
    offline: bool = field(default_factory=lambda: os.environ.get("SOS_OFFLINE", "").lower() in ("1", "true"))
    state_file: Path = field(default_factory=lambda: REPO_ROOT / ".cache" / "sos_state.json")
