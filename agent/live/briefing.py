"""The 911 briefing text, in the order of spec section 9.10. Pure functions.

1. type ("possible cardiac arrest, witnessed collapse")
2. address + floor + landmark
3. time since collapse
4. CPR / AED status
5. modifiers
6. EMS door + staging spot (Vexcel)
7. caller-of-record callback (``monitoring_callback``)

The text goes to ``DISPATCH_SIM_NUMBER`` only (a teammate's phone), spoken twice by the TwiML in
``agent/api/twilio.py``. Every value comes from the incident state and the census rows; nothing is
estimated here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent.live.playbooks import format_distance_m

TYPE_PHRASES = {
    "cardiac": "Possible cardiac arrest",
    "fall": "Fall, the person is responsive",
    "unknown": "Person down",
}

MODIFIER_PHRASES = {
    "breathing": "the scene check suggests the person may be breathing",
    "seizure": "possible seizure",
    "overdose": "possible overdose",
    "notify_police": "police requested",
}


def spoken_duration(seconds: float) -> str:
    seconds = max(0, round(seconds))
    minutes, secs = divmod(seconds, 60)
    sec_word = "second" if secs == 1 else "seconds"
    if minutes == 0:
        return f"{secs} {sec_word}"
    min_word = "minute" if minutes == 1 else "minutes"
    return f"{minutes} {min_word} {secs} {sec_word}"


def spoken_digits(number: str) -> str:
    """Read a phone number digit by digit."""
    return " ".join(ch for ch in number if ch.isdigit())


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith(".") else text + "."


def part_type(state: Mapping[str, Any]) -> str:
    kind = state.get("type") or "unknown"
    phrase = TYPE_PHRASES.get(kind, TYPE_PHRASES["unknown"])
    how = "witnessed collapse" if state.get("witnessed") else "found down"
    return _sentence(f"{phrase}, {how}")


def part_location(state: Mapping[str, Any]) -> str:
    building = state.get("building") or {}
    camera = state.get("camera") or {}
    bits = []
    if building.get("address"):
        bits.append(str(building["address"]))
    elif building.get("name"):
        bits.append(str(building["name"]))
    if camera.get("floor") is not None:
        bits.append(f"floor {camera['floor']}")
    if camera.get("landmark"):
        bits.append(f"by {camera['landmark']}")  # same phrasing as the speaker script
    if not bits:
        return "Location: not on file."
    return _sentence("Location: " + ", ".join(bits))


def part_time(state: Mapping[str, Any], now: float) -> str:
    collapse_at = state.get("collapse_at")
    if collapse_at is not None:
        return _sentence(f"Collapse {spoken_duration(now - collapse_at)} ago")
    detected_at = state.get("detected_at")
    if detected_at is not None:
        return _sentence(
            f"Time of collapse unknown, found down {spoken_duration(now - detected_at)} ago"
        )
    return "Time of collapse unknown."


def part_cpr_aed(state: Mapping[str, Any], now: float) -> str:
    milestones = state.get("milestones") or {}
    roles = state.get("roles") or {}
    routes = state.get("routes") or {}
    if milestones.get("cpr_started") is not None:
        cpr = f"CPR started {spoken_duration(now - milestones['cpr_started'])} ago"
    else:
        cpr = "CPR not confirmed yet"
    if milestones.get("aed_arrived") is not None:
        aed = "AED is on scene"
    elif roles.get("aed_runner"):
        aed = "a responder is bringing the AED"
    elif (routes.get("aed") or {}).get("distance_m") is not None:
        aed = f"nearest AED visible in the scan is {format_distance_m(routes['aed']['distance_m'])} meters away"
    else:
        aed = "no AED visible in the scan near this camera"
    return _sentence(f"{cpr}, {aed}")


def part_modifiers(state: Mapping[str, Any]) -> str:
    bits = [MODIFIER_PHRASES[m] for m in state.get("modifiers") or [] if m in MODIFIER_PHRASES]
    if state.get("scene_safe") is False:
        bits.append("scene reported unsafe, bystanders told to stay back")
    hazards = [str(h) for h in state.get("hazards") or []]
    if hazards:
        bits.append("hazards reported: " + ", ".join(hazards))
    if not bits:
        return "No other findings."
    text = "; ".join(bits)
    return _sentence(text[0].upper() + text[1:])


def _staging(building: Mapping[str, Any]) -> str | None:
    door = building.get("ems_door") or {}
    staging = door.get("staging")
    if isinstance(staging, Mapping) and staging.get("desc"):
        return str(staging["desc"])
    if isinstance(staging, str) and staging:
        return staging
    parking = (building.get("vexcel") or {}).get("ambulance_parking") or []
    for spot in parking:
        if isinstance(spot, Mapping) and spot.get("desc"):
            return str(spot["desc"])
    return None


def part_ems_door(state: Mapping[str, Any]) -> str:
    building = state.get("building") or {}
    door = building.get("ems_door") or {}
    bits = []
    if door.get("desc"):
        bits.append(f"EMS entrance: {door['desc']}")
    else:
        bits.append("EMS entrance not mapped")
    staging = _staging(building)
    if staging:
        bits.append(f"ambulance staging: {staging}")
    return _sentence(", ".join(bits))


def part_callback(state: Mapping[str, Any]) -> str:
    callback = (state.get("building") or {}).get("monitoring_callback")
    if callback:
        return _sentence(f"Callback for the caller of record: {spoken_digits(str(callback))}")
    return "No callback number on file."


def briefing_parts(state: Mapping[str, Any], now: float) -> list[str]:
    """The seven parts, in spec order."""
    return [
        part_type(state),
        part_location(state),
        part_time(state, now),
        part_cpr_aed(state, now),
        part_modifiers(state),
        part_ems_door(state),
        part_callback(state),
    ]


def build_briefing(state: Mapping[str, Any], now: float) -> str:
    return " ".join(briefing_parts(state, now))
