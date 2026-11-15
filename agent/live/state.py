"""Incident state for the live graph, the signals that wake it, and the channel reducers.

The state is plain JSON-friendly data (str, float, bool, list, dict) so it serializes into the
SQLite checkpointer without custom types. Times are epoch seconds (floats) inside the state and
ISO 8601 UTC in the database.

Three keys use reducers so that parallel nodes (the Send fan-out) can write them in one superstep,
and so that the "only add" rules are structural:

- ``modifiers`` and ``hazards`` are ordered unions: nothing can ever remove an entry.
- ``dispatches`` is upserted by ``id``.
- ``timers``, ``milestones``, ``roles`` and ``done`` are merged dicts; for ``timers`` a ``None``
  value deletes the entry (the timer was cancelled or has fired).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

# spec section 3: "The modifier allowlist is [breathing, seizure, overdose, notify_police]."
MODIFIER_ALLOWLIST: tuple[str, ...] = ("breathing", "seizure", "overdose", "notify_police")

IncidentType = Literal["unknown", "cardiac", "fall"]
Playbook = Literal["cardiac", "fall", "unsafe"]
ConfirmState = Literal["pending", "confirmed", "false_alarm", "auto", "escalated_911_only"]
FallBriefing = Literal["none", "armed", "cancelled", "fired"]
# aed_picked_up (the AED runner has the AED) and aed_help_started (the app asked for spoken AED
# instructions) are recorded on the timeline only (team lead, 2026-11-14): no column, no script switch.
MilestoneKind = Literal["cpr_started", "aed_arrived", "responder_arrived", "aed_picked_up", "aed_help_started"]
MILESTONE_KINDS: tuple[str, ...] = (
    "cpr_started", "aed_arrived", "responder_arrived", "aed_picked_up", "aed_help_started")

# Dispatch statuses (enum dispatch_status in 0001_init.sql)
DISPATCH_OPEN = ("sent", "timeout")  # can still be accepted
DISPATCH_ENGAGED = ("accepted", "arrived")

# Timer names (agent/DESIGN.md "Signals and interrupts")
TIMER_VOICE_CHECK = "voice_check"
TIMER_CONFIRM_AUTO = "confirm_auto"
TIMER_FOUND_DOWN = "found_down_escalate"
TIMER_FALL_911 = "fall_911"
TIMER_ANNOUNCE = "announce_repeat"
TIMER_GUIDE = "guide_tick"


def wave_timer(n: int) -> str:
    return f"wave_{n}"


# ---------------------------------------------------------------------------
# Reducers
# ---------------------------------------------------------------------------


def union_list(current: list[str] | None, new: list[str] | None) -> list[str]:
    """Ordered union. Used for modifiers and hazards so an update can only add."""
    out = list(current or [])
    for item in new or []:
        if item not in out:
            out.append(item)
    return out


def merge_dict(current: dict | None, new: dict | None) -> dict:
    """Shallow merge. A ``None`` value deletes the key (used to cancel timers)."""
    out = dict(current or {})
    for key, value in (new or {}).items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def upsert_by_id(current: list[dict] | None, new: list[dict] | None) -> list[dict]:
    """Replace items with the same ``id`` (merging fields), append the others, keep order."""
    out = [dict(d) for d in current or []]
    index = {d["id"]: i for i, d in enumerate(out)}
    for item in new or []:
        if item["id"] in index:
            out[index[item["id"]]] = {**out[index[item["id"]]], **item}
        else:
            index[item["id"]] = len(out)
            out.append(dict(item))
    return out


REDUCERS = {
    "modifiers": union_list,
    "hazards": union_list,
    "dispatches": upsert_by_id,
    "timers": merge_dict,
    "milestones": merge_dict,
    "roles": merge_dict,
    "done": merge_dict,
}


def merge_state(state: dict, updates: dict) -> dict:
    """Apply node or reducer updates to a state dict the way the graph channels do."""
    out = dict(state)
    for key, value in updates.items():
        reducer = REDUCERS.get(key)
        out[key] = reducer(state.get(key), value) if reducer else value
    return out


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class IncidentState(TypedDict, total=False):
    # identity and context (set by ingest)
    incident_id: str
    camera_id: str
    building_id: str | None
    victim_track_id: int
    witnessed: bool
    cfg: dict[str, Any]  # LiveConfig.as_state()
    camera: dict[str, Any]  # cameras row (landmark, floor, has_speaker) + available script ids
    building: dict[str, Any]  # buildings row subset: name, address, lat, lng, geofence_m, ems_door, ...
    routes: dict[str, Any]  # target -> {distance_m, directions, audio_url, path}

    # times (epoch seconds)
    detected_at: float  # when the agent received person_down
    collapse_at: float | None  # witnessed: event ts minus DOWN_SECONDS; found down: None
    first_instruction_at: float | None
    confirmed_at: float | None
    ems_notified_at: float | None
    first_accept_at: float | None
    resolved_at: float | None

    # triage (spec section 3)
    type: IncidentType
    playbook: Playbook | None
    classified: bool
    modifiers: Annotated[list[str], union_list]  # subset of MODIFIER_ALLOWLIST, add-only
    scene_safe: bool | None
    hazards: Annotated[list[str], union_list]
    verification: dict[str, Any] | None
    responsive: bool  # set only by a vision "responsive" event from the victim's track
    voice_check_done: bool

    # gate
    confirm: ConfirmState
    confirmed_by: str | None

    # responders (spec section 9.10)
    dispatches: Annotated[list[dict[str, Any]], upsert_by_id]
    waves_sent: int
    waves_closed: int
    waves_exhausted: bool  # no eligible responder was left for the next wave
    roles: Annotated[dict[str, str], merge_dict]  # "aed_runner" | "patient" -> responder_id

    # actions
    milestones: Annotated[dict[str, float], merge_dict]  # MILESTONE_KINDS -> ts
    ems_briefed: bool
    briefing_call_sid: str | None
    fall_911: FallBriefing
    police_notified: bool
    staff_alerted: bool
    spoken_key: list[str]  # the script sequence currently on the speaker
    speak_due: bool  # a repeat timer fired
    timers: Annotated[dict[str, str], merge_dict]  # active timer name -> token
    done: Annotated[dict[str, bool], merge_dict]  # one-shot nodes that already ran

    resolved: bool
    resolved_by: str | None
    status: str  # incident_status enum, derived


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

SignalKind = Literal[
    # vision
    "responsive",
    "possible_seizure",
    "responder_arrived",
    # desk
    "confirm",
    "false_alarm",
    "cancel_911",
    "milestone",
    "resolve",
    # dispatch (app or Twilio digits)
    "accept",
    "decline",
    "arrived",
    # timers
    "timeout",
    # the one LLM call (io/verify.py)
    "verify_result",
    "verify_failed",
]


class Signal(TypedDict, total=False):
    kind: SignalKind
    source: str  # vision | desk | app | twilio | timer | llm
    ts: float  # epoch seconds, set by signals.deliver when missing
    by: str | None
    victim_track_id: int | None  # vision signals
    milestone: MilestoneKind  # kind == "milestone"
    dispatch_id: str  # accept | decline | arrived
    with_aed: bool  # arrived
    name: str  # timeout: timer name
    token: str  # timeout: the token the timer was started with
    result: Any  # verify_result: raw model output, sanitized by the reducer
    reason: str  # verify_failed


def initial_state(
    *,
    incident_id: str,
    camera_id: str,
    victim_track_id: int,
    witnessed: bool,
    detected_at: float,
    collapse_at: float | None,
    cfg: dict[str, Any],
) -> IncidentState:
    """Every key the reducer and planner read, with its starting value."""
    return IncidentState(
        incident_id=incident_id,
        camera_id=camera_id,
        building_id=None,
        victim_track_id=victim_track_id,
        witnessed=witnessed,
        cfg=cfg,
        camera={},
        building={},
        routes={},
        detected_at=detected_at,
        collapse_at=collapse_at,
        first_instruction_at=None,
        confirmed_at=None,
        ems_notified_at=None,
        first_accept_at=None,
        resolved_at=None,
        type="unknown",
        playbook=None,
        classified=False,
        modifiers=[],
        scene_safe=None,
        hazards=[],
        verification=None,
        responsive=False,
        voice_check_done=False,
        confirm="pending",
        confirmed_by=None,
        dispatches=[],
        waves_sent=0,
        waves_closed=0,
        waves_exhausted=False,
        roles={},
        milestones={},
        ems_briefed=False,
        briefing_call_sid=None,
        fall_911="none",
        police_notified=False,
        staff_alerted=False,
        spoken_key=[],
        speak_due=False,
        timers={},
        done={},
        resolved=False,
        resolved_by=None,
        status="detected",
    )
