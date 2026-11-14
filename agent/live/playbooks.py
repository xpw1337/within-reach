"""Speaker scripts (spec section 3, verbatim) and which script plays when.

Text rule: the wording below is copied from the spec templates. The only edit is that each
em-dash in the spec is replaced by a comma (a spoken pause), because the team bans the em-dash
character in code. Bold markers from the spec table are markup, not text, and are dropped.

Script IDs are the stable list in docs/CONTRACTS.md section 6. Three of them have no wording in the
spec yet (``cardiac_aed_arrived``, ``unsafe_stay_back``, ``all_clear``). Their text is ``None``
until a human supplies it: they are never rendered, and the graph falls back as described in
``desired_script``. Do not write medical wording here that is not in the spec.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

SCRIPT_IDS: tuple[str, ...] = (
    "voice_check",
    "cardiac_main",
    "cardiac_cpr_coach",
    "cardiac_aed_arrived",
    "mod_breathing",
    "mod_seizure",
    "mod_overdose",
    "fall_main",
    "unsafe_stay_back",
    "all_clear",
)

SCRIPTS: dict[str, str | None] = {
    # spec section 3, decision tree
    "voice_check": "Are you okay? If you can hear me, raise your hand.",
    # spec section 3, CARDIAC row (em-dash before the AED distance replaced by a comma)
    "cardiac_main": (
        "Emergency: someone has collapsed by {landmark}. Go to them, tap their shoulder and shout. "
        "If they don't respond and aren't breathing normally, call 911 on speaker and start CPR: "
        "push hard and fast in the center of the chest. "
        "Someone else: get the AED, {aed_distance} meters, {aed_directions}."
    ),
    # spec section 3, CARDIAC row, "After CPR starts"
    "cardiac_cpr_coach": (
        "Push at least 2 inches deep, 100 to 120 times a minute, let the chest come back up. "
        "When the AED arrives, turn it on and follow its voice."
    ),
    # not in the spec: wording needed from a human
    "cardiac_aed_arrived": None,
    # spec section 3, "+ breathing" row
    "mod_breathing": "If they are breathing, roll them onto their side and stay with them.",
    # spec section 3, "+ seizure" row (em-dash after "check breathing" replaced by a comma)
    "mod_seizure": (
        "If they're shaking, don't hold them down or put anything in their mouth. "
        "Move hard objects away. "
        "When it stops, check breathing, if they're not breathing normally, start CPR."
    ),
    # spec section 3, "+ overdose" row. Only if naloxone is mapped for the camera.
    "mod_overdose": "Naloxone is in {naloxone_location}. Spray one dose in a nostril.",
    # spec section 3, FALL row
    "fall_main": "Help is on the way. Try not to move. Staff have been notified.",
    # not in the spec: wording needed from a human
    "unsafe_stay_back": None,
    # not in the spec: wording needed from a human
    "all_clear": None,
}

# Modifier -> script, in the order they are spoken after the main CARDIAC script.
# notify_police has no script: it only triggers the police node.
MODIFIER_SCRIPTS: tuple[tuple[str, str], ...] = (
    ("breathing", "mod_breathing"),
    ("seizure", "mod_seizure"),
    ("overdose", "mod_overdose"),
)

# Scripts that repeat, and the config key holding the repeat interval. spec section 3: the CARDIAC
# script repeats every 20 s; the coaching loop (spec section 9.8 node 7) reuses the same interval.
REPEAT_INTERVAL_KEY: dict[str, str] = {
    "cardiac_main": "announce_repeat_seconds",
    "cardiac_cpr_coach": "guide_repeat_seconds",
    "cardiac_aed_arrived": "guide_repeat_seconds",
}

GUIDE_SCRIPTS = ("cardiac_cpr_coach", "cardiac_aed_arrived")


class MissingPlaceholder(ValueError):
    """A template needs a value the census map does not have for this camera."""


def has_text(script_id: str) -> bool:
    return SCRIPTS.get(script_id) is not None


def format_distance_m(distance_m: float | None) -> str | None:
    if distance_m is None:
        return None
    return str(round(float(distance_m)))


def camera_context(camera: Mapping[str, Any], routes: Mapping[str, Any]) -> dict[str, str | None]:
    """Placeholder values for one camera, from the ``cameras`` and ``camera_routes`` rows."""
    aed = routes.get("aed") or {}
    naloxone = routes.get("naloxone") or {}
    return {
        "landmark": camera.get("landmark"),
        "aed_distance": format_distance_m(aed.get("distance_m")),
        "aed_directions": aed.get("directions"),
        # docs/CONTRACTS.md section 6 fills {naloxone_location} from camera_routes; the
        # naloxone route's directions are the only location text that table holds.
        "naloxone_location": naloxone.get("directions"),
    }


def naloxone_mapped(routes: Mapping[str, Any]) -> bool:
    return bool((routes.get("naloxone") or {}).get("directions"))


def render(script_id: str, ctx: Mapping[str, Any]) -> str | None:
    """Fill a template. Returns None for scripts with no wording yet. Raises MissingPlaceholder
    when the camera has no value for a placeholder the template uses."""
    if script_id not in SCRIPTS:
        raise KeyError(script_id)
    template = SCRIPTS[script_id]
    if template is None:
        return None
    needed = [name for name in ("landmark", "aed_distance", "aed_directions", "naloxone_location")
              if "{" + name + "}" in template]
    missing = [name for name in needed if not ctx.get(name)]
    if missing:
        raise MissingPlaceholder(f"{script_id} needs {', '.join(missing)}")
    return template.format(**{name: ctx[name] for name in needed})


def renderable_scripts(camera: Mapping[str, Any], routes: Mapping[str, Any]) -> dict[str, str]:
    """Every script that can be rendered for this camera, with its text. ``mod_overdose`` only
    when naloxone is mapped; scripts with missing wording or missing placeholders are left out."""
    ctx = camera_context(camera, routes)
    out: dict[str, str] = {}
    for script_id in SCRIPT_IDS:
        if script_id == "mod_overdose" and not naloxone_mapped(routes):
            continue
        try:
            text = render(script_id, ctx)
        except MissingPlaceholder:
            continue
        if text is not None:
            out[script_id] = text
    return out


def desired_script(state: Mapping[str, Any], available: Iterable[str] | None = None) -> list[str]:
    """The script sequence that should be on the speaker now, after classification.

    ``available`` is the set of script ids that have audio for this camera (defaults to
    ``state["camera"]["scripts"]``). A script without audio is skipped; for the AED-arrived script
    the coaching script (which already says what to do with the AED) keeps playing instead. An
    unsafe scene never falls back to the CARDIAC script: if there is no stay-back audio the speaker
    goes quiet rather than telling people to go to the victim.
    """
    if available is None:
        available = (state.get("camera") or {}).get("scripts") or []
    avail = set(available)
    playbook = state.get("playbook")
    milestones = state.get("milestones") or {}

    def only(script_id: str) -> list[str]:
        return [script_id] if script_id in avail else []

    if playbook == "unsafe":
        return only("unsafe_stay_back")
    if playbook == "fall":
        return only("fall_main")
    if playbook != "cardiac":
        return []
    if milestones.get("aed_arrived") and "cardiac_aed_arrived" in avail:
        return ["cardiac_aed_arrived"]
    if milestones.get("cpr_started") or milestones.get("aed_arrived"):
        return only("cardiac_cpr_coach")
    seq = only("cardiac_main")
    if not seq:
        return []
    modifiers = state.get("modifiers") or []
    routes = state.get("routes") or {}
    for modifier, script_id in MODIFIER_SCRIPTS:
        if modifier not in modifiers or script_id not in avail:
            continue
        if script_id == "mod_overdose" and not naloxone_mapped(routes):
            continue
        seq.append(script_id)
    return seq


def is_guide(seq: list[str]) -> bool:
    """True when the sequence belongs to the CPR coaching loop (the ``guide`` node)."""
    return bool(seq) and seq[0] in GUIDE_SCRIPTS


def repeat_seconds(seq: list[str], cfg: Mapping[str, Any]) -> float | None:
    if not seq:
        return None
    key = REPEAT_INTERVAL_KEY.get(seq[0])
    return float(cfg[key]) if key else None
