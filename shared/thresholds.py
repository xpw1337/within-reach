"""Red-zone rules (spec section 9.4). The single source for zones in Python.

Units (docs/ARCHITECTURE.md decision D4): ``coverage.time_s``, ``building_scores.*_worst_s`` and
``fixes.before_worst_s`` / ``after_worst_s`` hold ONE-WAY walking seconds. Every conversion lives
here:

- AED: the guideline is a round trip, so the red limit in one-way seconds is half the target and
  anything shown to a person as an AED time uses ``aed_display_seconds`` (2x one-way).
- Extinguisher and exit: the guideline is a one-way travel distance, so the limit in seconds is
  distance / walk speed, and ``travel_m`` turns seconds back into meters for display.

Threshold defaults are approximations, not verified guideline values (spec section 20). Each one
names its source and stays configurable through the environment:

- ``AED_ROUNDTRIP_TARGET_S`` = 180 s round trip. Source: spec section 9.4 default ("check the
  guideline"); a ~3 minute collapse-to-shock retrieval target. UNVERIFIED.
- ``EXT_MAX_TRAVEL_M`` = 22.9 m (75 ft). Source: spec section 9.4, NFPA 10 maximum travel distance
  to a Class A extinguisher. UNVERIFIED.
- ``EXIT_MAX_TRAVEL_M`` = 61 m (200 ft). Source: spec section 9.4, IBC exit access travel distance;
  the real limit varies by occupancy and sprinklers. UNVERIFIED.
- ``WALK_SPEED_MPS`` = 1.4 m/s. Source: spec section 9.4 default walking speed. UNVERIFIED.
"""

from __future__ import annotations

from typing import Any

from shared.config import Settings, get_settings
from shared.types import Zone

# Fraction of the red limit where yellow starts. A display choice only, not a guideline.
YELLOW_FRACTION = 2 / 3

ZONED_TYPES: tuple[str, ...] = ("aed", "extinguisher", "exit")


def _s(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def limit_seconds(asset_type: str, settings: Settings | None = None) -> float:
    """The red limit for ``asset_type`` expressed as one-way walking seconds."""
    s = _s(settings)
    if asset_type == "aed":
        return s.aed_roundtrip_target_s / 2
    if asset_type == "extinguisher":
        return s.ext_max_travel_m / s.walk_speed_mps
    if asset_type == "exit":
        return s.exit_max_travel_m / s.walk_speed_mps
    raise ValueError(f"No red-zone rule for asset type {asset_type!r}; expected one of {ZONED_TYPES}")


def zone(asset_type: str, time_s: float | None, settings: Settings | None = None) -> Zone:
    """Zone for one sweep given its one-way walking time to the nearest asset of that type.

    ``None`` means no asset of that type is visible in the scan (or it is unreachable): "unknown".
    Strictly above the limit is red; strictly above ``YELLOW_FRACTION`` of the limit is yellow.
    """
    limit = limit_seconds(asset_type, settings)
    if time_s is None:
        return "unknown"
    if time_s > limit:
        return "red"
    if time_s > YELLOW_FRACTION * limit:
        return "yellow"
    return "green"


def is_red(asset_type: str, time_s: float | None, settings: Settings | None = None) -> bool:
    return zone(asset_type, time_s, settings) == "red"


def aed_display_seconds(one_way_s: float | None) -> float | None:
    """AED round-trip seconds for display (decision D4): 2x the stored one-way seconds."""
    return None if one_way_s is None else 2 * one_way_s


def display_seconds(asset_type: str, one_way_s: float | None) -> float | None:
    """Seconds as a person should see them: round trip for AEDs, one-way for everything else."""
    if asset_type == "aed":
        return aed_display_seconds(one_way_s)
    return one_way_s


def travel_m(time_s: float | None, settings: Settings | None = None) -> float | None:
    """One-way travel distance in meters for a one-way walking time."""
    return None if time_s is None else time_s * _s(settings).walk_speed_mps


def seconds_for_distance(distance_m: float, settings: Settings | None = None) -> float:
    """One-way walking seconds for a distance in meters."""
    return distance_m / _s(settings).walk_speed_mps


def thresholds_payload(settings: Settings | None = None) -> dict[str, Any]:
    """Body of ``GET /config/thresholds`` (docs/CONTRACTS.md section 2)."""
    s = _s(settings)
    return {
        "walk_speed_mps": s.walk_speed_mps,
        "aed_roundtrip_target_s": s.aed_roundtrip_target_s,
        "ext_max_travel_m": s.ext_max_travel_m,
        "exit_max_travel_m": s.exit_max_travel_m,
        "yellow_fraction": YELLOW_FRACTION,
    }
