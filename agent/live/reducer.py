"""The pure core of the live graph (spec section 3, medically reviewed: do not simplify).

``apply_signal(state, signal)`` turns one signal into state updates, timeline events and side
effects to perform (cancel a timer, hang up a call, stop the speaker). It never performs them.
Signals that no longer apply are ignored: a confirm after a false alarm, an accept after both
roles are filled, a timeout from a superseded timer, anything after resolve. This is what makes
races between the desk, vision, Twilio and timers safe.

``plan(state)`` names the nodes that must run next. ``classify(state)`` is the decision itself.

Rules encoded here, from spec section 3 and agent/DESIGN.md:

- Only the vision ``responsive`` event, from the victim's track, sets ``responsive``. Nothing else
  can make the voice check come out responsive.
- ``possible_seizure`` adds the ``seizure`` modifier and still escalates.
- The scene check (LLM) can only add modifiers from the allowlist, add hazards, and mark the scene
  unsafe. It cannot remove a modifier, mark an unsafe scene safe, cancel or delay anything.
  ``is_emergency=false`` is advice for the desk only.
- Classify when the voice check ends: unsafe scene -> stay back + police + no responders;
  responsive -> FALL; otherwise CARDIAC (+ modifiers). A false alarm ends the incident.
- External actions (responders, 911 briefing) are gated by CONFIRM: witnessed auto-proceeds after
  ``CONFIRM_AUTO_PROCEED_SECONDS``; found down needs a human confirm, and after
  ``FOUND_DOWN_ESCALATE_SECONDS`` gets the 911 briefing only, no strangers. The speaker is never
  gated.
- FALL: staff first; 911 briefing after ``FALL_911_CANCEL_SECONDS`` unless cancelled.
- Waves never hold up the 911 briefing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from agent.live.playbooks import desired_script, is_guide
from agent.live.responders import open_role, roles_filled
from agent.live.state import (
    DISPATCH_ENGAGED,
    DISPATCH_OPEN,
    MILESTONE_KINDS,
    MODIFIER_ALLOWLIST,
    TIMER_ANNOUNCE,
    TIMER_CONFIRM_AUTO,
    TIMER_FALL_911,
    TIMER_FOUND_DOWN,
    TIMER_GUIDE,
    TIMER_VOICE_CHECK,
    merge_state,
)

GATE_OPEN = ("confirmed", "auto")
BRIEFING_ALLOWED = ("confirmed", "auto", "escalated_911_only")
FIRST_NODES = ("verify", "request_confirm", "voice_check")
MAX_HAZARDS = 10
MAX_HAZARD_LEN = 80


@dataclass
class Transition:
    updates: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)  # {actor, kind, payload}
    effects: list[dict[str, Any]] = field(default_factory=list)  # cancel_timer | hangup | stop_audio
    applied: bool = True
    reason: str | None = None


def _ignored(reason: str) -> Transition:
    return Transition(applied=False, reason=reason)


def _event(actor: str, kind: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"actor": actor, "kind": kind, "payload": payload or {}}


def dispatch_payload(d: Mapping[str, Any], **changes: Any) -> dict[str, Any]:
    """docs/CONTRACTS.md section 3: ``{dispatch_id, responder_id, role, wave, channel, call_sid?}``."""
    row = {**d, **changes}
    payload = {"dispatch_id": row.get("id"), "responder_id": row.get("responder_id"), "role": row.get("role"),
               "wave": row.get("wave"), "channel": row.get("channel")}
    if row.get("call_sid"):
        payload["call_sid"] = row["call_sid"]
    return payload


def verify_payload(clean: Mapping[str, Any] | None, error: str | None = None) -> dict[str, Any]:
    """docs/CONTRACTS.md section 3: ``{is_emergency, scene_safe, hazards[], modifiers[], error?}``."""
    clean = clean or {}
    payload = {"is_emergency": clean.get("is_emergency"), "scene_safe": clean.get("scene_safe"),
               "hazards": list(clean.get("hazards") or []), "modifiers": list(clean.get("modifiers") or [])}
    if error:
        payload["error"] = error
    return payload


def _cancel(state: Mapping[str, Any], *names: str) -> tuple[dict[str, None], list[dict[str, Any]]]:
    """Timer updates and effects for cancelling the named timers that are active."""
    active = state.get("timers") or {}
    names = tuple(n for n in names if n in active)
    return {n: None for n in names}, [{"type": "cancel_timer", "name": n} for n in names]


def _cancel_all(state: Mapping[str, Any]) -> tuple[dict[str, None], list[dict[str, Any]]]:
    return _cancel(state, *(state.get("timers") or {}).keys())


def _find_dispatch(state: Mapping[str, Any], dispatch_id: str | None) -> dict[str, Any] | None:
    for d in state.get("dispatches") or []:
        if d.get("id") == dispatch_id:
            return d
    return None


def _release(
    state: Mapping[str, Any], statuses: tuple[str, ...], *, keep_ids: tuple[str, ...] = ()
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Release every dispatch in ``statuses`` (except ``keep_ids``) and hang up its call."""
    rows, events, effects = [], [], []
    for d in state.get("dispatches") or []:
        if d.get("status") not in statuses or d.get("id") in keep_ids:
            continue
        rows.append({"id": d["id"], "status": "released"})
        events.append(
            _event("system", "dispatch_released", dispatch_payload(d))
        )
        if d.get("call_sid"):
            effects.append({"type": "hangup", "call_sid": d["call_sid"], "dispatch_id": d["id"]})
    return rows, events, effects


def gate_open(state: Mapping[str, Any]) -> bool:
    return state.get("confirm") in GATE_OPEN


def _gate_event(state_after: Mapping[str, Any]) -> list[dict[str, Any]]:
    """``gate_opened`` once the incident is classified CARDIAC or unsafe and the confirm allows it."""
    if not state_after.get("classified") or state_after.get("playbook") not in ("cardiac", "unsafe"):
        return []
    confirm = state_after.get("confirm")
    if confirm in GATE_OPEN:
        return [_event("system", "gate_opened", {"mode": "full", "confirm": confirm})]
    if confirm == "escalated_911_only":
        return [_event("system", "gate_opened", {"mode": "911_only", "confirm": confirm})]
    return []


def _classified_event(state_after: Mapping[str, Any]) -> dict[str, Any]:
    return _event(
        "system",
        "classified",
        {
            "type": state_after.get("type"),
            "playbook": state_after.get("playbook"),
            "modifiers": list(state_after.get("modifiers") or []),
            "scene_safe": state_after.get("scene_safe"),
            "hazards": list(state_after.get("hazards") or []),
        },
    )


def _vision_track_matches(state: Mapping[str, Any], signal: Mapping[str, Any]) -> bool:
    return signal.get("victim_track_id") is not None and signal.get("victim_track_id") == state.get(
        "victim_track_id"
    )


# ---------------------------------------------------------------------------
# Scene check output (the one LLM call): sanitize before it touches the state
# ---------------------------------------------------------------------------


def sanitize_verification(raw: Any) -> dict[str, Any] | None:
    """Keep only well-typed fields. Modifiers are filtered through the allowlist. Returns None
    when nothing usable is left (junk output)."""
    if not isinstance(raw, Mapping):
        return None
    out: dict[str, Any] = {}
    if isinstance(raw.get("is_emergency"), bool):
        out["is_emergency"] = raw["is_emergency"]
    if isinstance(raw.get("scene_safe"), bool):
        out["scene_safe"] = raw["scene_safe"]
    hazards = raw.get("hazards")
    if isinstance(hazards, list):
        clean = []
        for h in hazards:
            if isinstance(h, str) and h.strip() and h.strip()[:MAX_HAZARD_LEN] not in clean:
                clean.append(h.strip()[:MAX_HAZARD_LEN])
        out["hazards"] = clean[:MAX_HAZARDS]
    modifiers = raw.get("modifiers")
    if isinstance(modifiers, list):
        out["modifiers"] = [m for m in MODIFIER_ALLOWLIST if m in modifiers]
    if not out:
        return None
    return out


# ---------------------------------------------------------------------------
# Signal handlers
# ---------------------------------------------------------------------------


def _on_responsive(state, sig) -> Transition:
    if state.get("voice_check_done"):
        return _ignored("voice check already over")
    if not _vision_track_matches(state, sig):
        return _ignored("not the victim's track")
    timers, effects = _cancel(state, TIMER_VOICE_CHECK)
    return Transition(
        updates={"responsive": True, "voice_check_done": True, "timers": timers},
        events=[_event("vision", "voice_check_result", {"responsive": True})],
        effects=effects,
    )


def _on_possible_seizure(state, sig) -> Transition:
    if not _vision_track_matches(state, sig):
        return _ignored("not the victim's track")
    if "seizure" in (state.get("modifiers") or []):
        return _ignored("seizure already noted")
    updates = {"modifiers": ["seizure"]}
    events = []
    if state.get("classified"):
        events.append(_classified_event(merge_state(state, updates)))
    return Transition(updates=updates, events=events)


def _on_vision_responder_arrived(state, sig) -> Transition:
    if (state.get("milestones") or {}).get("responder_arrived") is not None:
        return _ignored("responder already arrived")
    return Transition(
        updates={"milestones": {"responder_arrived": sig["ts"]}},
        events=[_event("vision", "responder_arrived", {"source": "vision"})],
    )


def _on_verify_result(state, sig) -> Transition:
    clean = sanitize_verification(sig.get("result"))
    if clean is None:
        return Transition(
            updates={"verification": {"error": "invalid output"}},
            events=[_event("llm", "verify_result", verify_payload(None, "invalid output"))],
        )
    updates: dict[str, Any] = {"verification": clean}
    events = [_event("llm", "verify_result", verify_payload(clean))]
    effects: list[dict[str, Any]] = []
    current = list(state.get("modifiers") or [])
    added = [m for m in clean.get("modifiers", []) if m not in current]
    if added:
        updates["modifiers"] = added
    if clean.get("hazards"):
        updates["hazards"] = clean["hazards"]
    unsafe_now = clean.get("scene_safe") is False and state.get("scene_safe") is not False
    if unsafe_now:
        updates["scene_safe"] = False
    elif clean.get("scene_safe") is True and state.get("scene_safe") is None:
        updates["scene_safe"] = True

    if state.get("classified"):
        if unsafe_now and state.get("playbook") != "unsafe":
            # Late "unsafe": stop sending people in. Everyone not yet released is told to stand down.
            updates["playbook"] = "unsafe"
            rows, rel_events, rel_effects = _release(state, DISPATCH_OPEN + DISPATCH_ENGAGED)
            if rows:
                updates["dispatches"] = rows
            events += rel_events
            effects += rel_effects
            wave_names = [n for n in (state.get("timers") or {}) if n.startswith("wave_")]
            timers, timer_effects = _cancel(state, TIMER_ANNOUNCE, TIMER_GUIDE, *wave_names)
            if timers:
                updates["timers"] = timers
            effects += timer_effects
        if added or unsafe_now or clean.get("hazards"):
            events.append(_classified_event(merge_state(state, updates)))
    return Transition(updates=updates, events=events, effects=effects)


def _on_verify_failed(state, sig) -> Transition:
    reason = str(sig.get("reason") or "failed")
    return Transition(
        updates={"verification": {"error": reason}},
        events=[_event("llm", "verify_result", verify_payload(None, reason))],
    )


def _on_confirm(state, sig) -> Transition:
    confirm = state.get("confirm")
    if confirm == "false_alarm":
        return _ignored("false alarm already declared")
    if confirm in GATE_OPEN:
        return _ignored("already confirmed")
    timers, effects = _cancel(state, TIMER_CONFIRM_AUTO, TIMER_FOUND_DOWN)
    updates = {
        "confirm": "confirmed",
        "confirmed_by": sig.get("by") or "desk",
        "confirmed_at": sig["ts"],
        "timers": timers,
    }
    events = [_event("desk", "confirmed", {"by": sig.get("by") or "desk"})]
    events += _gate_event(merge_state(state, updates))
    return Transition(updates=updates, events=events, effects=effects)


def _end(state, sig, *, false_alarm: bool) -> Transition:
    timers, effects = _cancel_all(state)
    effects = [{"type": "stop_audio"}] + effects
    # A false alarm stands everyone down. On resolve, responders who accepted keep their record.
    statuses = DISPATCH_OPEN + DISPATCH_ENGAGED if false_alarm else DISPATCH_OPEN
    if false_alarm:
        statuses = tuple(s for s in statuses if s != "arrived")
    rows, rel_events, rel_effects = _release(state, statuses)
    updates: dict[str, Any] = {
        "resolved": True,
        "resolved_at": sig["ts"],
        "resolved_by": sig.get("by") or "desk",
        "timers": timers,
    }
    if rows:
        updates["dispatches"] = rows
    if state.get("fall_911") == "armed":
        updates["fall_911"] = "cancelled"
    events = []
    if false_alarm:
        updates["confirm"] = "false_alarm"
        events.append(_event("desk", "false_alarm", {"by": sig.get("by") or "desk"}))
    return Transition(updates=updates, events=events + rel_events, effects=effects + rel_effects)


def _on_false_alarm(state, sig) -> Transition:
    return _end(state, sig, false_alarm=True)


def _on_resolve(state, sig) -> Transition:
    return _end(state, sig, false_alarm=False)


def _on_cancel_911(state, sig) -> Transition:
    if state.get("type") != "fall":
        return _ignored("cancel_911 applies to the FALL playbook only")
    if state.get("fall_911") != "armed":
        return _ignored(f"fall 911 timer is {state.get('fall_911')}")
    timers, effects = _cancel(state, TIMER_FALL_911)
    return Transition(
        updates={"fall_911": "cancelled", "timers": timers},
        events=[_event("desk", "fall_911_cancelled", {"by": sig.get("by") or "desk"})],
        effects=effects,
    )


def _on_milestone(state, sig) -> Transition:
    kind = sig.get("milestone")
    if kind not in MILESTONE_KINDS:
        return _ignored(f"unknown milestone {kind!r}")
    if (state.get("milestones") or {}).get(kind) is not None:
        return _ignored(f"{kind} already recorded")
    updates: dict[str, Any] = {"milestones": {kind: sig["ts"]}}
    effects: list[dict[str, Any]] = []
    if kind in ("cpr_started", "aed_arrived"):
        timers, effects = _cancel(state, TIMER_ANNOUNCE)
        if timers:
            updates["timers"] = timers
    events = [_event("desk", "milestone", {"kind": kind, "by": sig.get("by")})]
    return Transition(updates=updates, events=events, effects=effects)


def _responder_actor(d: Mapping[str, Any]) -> str:
    return f"responder:{d.get('responder_id')}"


def _on_accept(state, sig) -> Transition:
    d = _find_dispatch(state, sig.get("dispatch_id"))
    if d is None:
        return _ignored("unknown dispatch")
    status = d.get("status")
    if status in DISPATCH_ENGAGED:
        return _ignored("already accepted")
    if status not in DISPATCH_OPEN:
        return _ignored(f"dispatch is {status}")
    ts = sig["ts"]
    if d.get("role") == "staff":
        # A staff alert is acknowledged; it does not take a responder role.
        return Transition(
            updates={"dispatches": [{"id": d["id"], "status": "accepted", "responded_at": ts}]},
            events=[_event(_responder_actor(d), "dispatch_accepted", dispatch_payload(d))],
        )
    roles = state.get("roles") or {}
    role = None if state.get("playbook") == "unsafe" else open_role(roles)
    if role is None:
        effects = []
        if d.get("call_sid"):
            effects.append({"type": "hangup", "call_sid": d["call_sid"], "dispatch_id": d["id"]})
        return Transition(
            updates={"dispatches": [{"id": d["id"], "status": "released", "responded_at": ts}]},
            events=[_event("system", "dispatch_released", dispatch_payload(d))],
            effects=effects,
        )
    updates: dict[str, Any] = {
        "dispatches": [{"id": d["id"], "status": "accepted", "role": role, "responded_at": ts}],
        "roles": {role: d.get("responder_id")},
    }
    if state.get("first_accept_at") is None:
        updates["first_accept_at"] = ts
    events = [_event(_responder_actor(d), "dispatch_accepted", dispatch_payload(d, role=role))]
    effects: list[dict[str, Any]] = []
    after = merge_state(state, updates)
    if roles_filled(after.get("roles") or {}):
        # Both roles taken: everyone else still pending is released and their calls hung up.
        pending = merge_state(state, {"dispatches": updates["dispatches"]})
        wave_rows = [x for x in pending.get("dispatches") or [] if x.get("role") != "staff"]
        rows, rel_events, rel_effects = _release({"dispatches": wave_rows}, DISPATCH_OPEN)
        updates["dispatches"] = updates["dispatches"] + rows
        events += rel_events
        effects += rel_effects
        wave_names = [n for n in (state.get("timers") or {}) if n.startswith("wave_")]
        timers, timer_effects = _cancel(state, *wave_names)
        if timers:
            updates["timers"] = timers
        effects += timer_effects
    return Transition(updates=updates, events=events, effects=effects)


def _on_decline(state, sig) -> Transition:
    d = _find_dispatch(state, sig.get("dispatch_id"))
    if d is None:
        return _ignored("unknown dispatch")
    if d.get("status") not in DISPATCH_OPEN:
        return _ignored(f"dispatch is {d.get('status')}")
    effects = []
    if d.get("call_sid") and sig.get("source") != "twilio":
        effects.append({"type": "hangup", "call_sid": d["call_sid"], "dispatch_id": d["id"]})
    return Transition(
        updates={"dispatches": [{"id": d["id"], "status": "declined", "responded_at": sig["ts"]}]},
        events=[_event(_responder_actor(d), "dispatch_declined", dispatch_payload(d))],
        effects=effects,
    )


def _on_arrived(state, sig) -> Transition:
    d = _find_dispatch(state, sig.get("dispatch_id"))
    if d is None:
        return _ignored("unknown dispatch")
    if d.get("status") not in DISPATCH_ENGAGED:
        return _ignored(f"dispatch is {d.get('status')}")
    ts = sig["ts"]
    milestones = state.get("milestones") or {}
    with_aed = bool(sig.get("with_aed"))
    updates: dict[str, Any] = {}
    events = []
    new_milestones: dict[str, float] = {}
    if d.get("status") != "arrived":
        updates["dispatches"] = [{"id": d["id"], "status": "arrived"}]
        events.append(_event(_responder_actor(d), "responder_arrived",
                             {"dispatch_id": d["id"], "responder_id": d.get("responder_id"),
                              "with_aed": with_aed}))
        if milestones.get("responder_arrived") is None:
            new_milestones["responder_arrived"] = ts
    if with_aed and milestones.get("aed_arrived") is None:
        new_milestones["aed_arrived"] = ts
        events.append(_event(_responder_actor(d), "milestone", {"kind": "aed_arrived", "by": d.get("responder_id")}))
    if not updates and not new_milestones:
        return _ignored("already arrived")
    effects: list[dict[str, Any]] = []
    if new_milestones:
        updates["milestones"] = new_milestones
        if "aed_arrived" in new_milestones:
            timers, effects = _cancel(state, TIMER_ANNOUNCE)
            if timers:
                updates["timers"] = timers
    return Transition(updates=updates, events=events, effects=effects)


def _on_timeout(state, sig) -> Transition:
    name = sig.get("name")
    active = (state.get("timers") or {}).get(name)
    if active is None or active != sig.get("token"):
        return _ignored("stale or cancelled timer")
    ts = sig["ts"]
    updates: dict[str, Any] = {"timers": {name: None}}
    events = [_event("system", "timer_fired", {"timer": name})]
    if name == TIMER_VOICE_CHECK:
        if not state.get("voice_check_done"):
            updates["voice_check_done"] = True
            events.append(_event("system", "voice_check_result", {"responsive": bool(state.get("responsive"))}))
    elif name == TIMER_CONFIRM_AUTO:
        if state.get("confirm") == "pending" and state.get("witnessed"):
            updates.update(confirm="auto", confirmed_by="auto", confirmed_at=ts)
            events.append(_event("system", "confirmed", {"by": "auto", "auto": True}))
            events += _gate_event(merge_state(state, updates))
    elif name == TIMER_FOUND_DOWN:
        if state.get("confirm") == "pending" and not state.get("witnessed"):
            updates["confirm"] = "escalated_911_only"
            events += _gate_event(merge_state(state, updates))
    elif name.startswith("wave_"):
        try:
            n = int(name.split("_", 1)[1])
        except ValueError:
            return _ignored("bad wave timer name")
        if n == state.get("waves_sent") and (state.get("waves_closed") or 0) < n:
            rows = []
            for d in state.get("dispatches") or []:
                if d.get("wave") == n and d.get("status") == "sent" and d.get("role") != "staff":
                    rows.append({"id": d["id"], "status": "timeout"})
                    events.append(_event("system", "dispatch_timeout", dispatch_payload(d)))
            if rows:
                updates["dispatches"] = rows
            updates["waves_closed"] = n
    elif name == TIMER_FALL_911:
        if state.get("fall_911") == "armed":
            updates["fall_911"] = "fired"
    elif name in (TIMER_ANNOUNCE, TIMER_GUIDE):
        updates["speak_due"] = True
    return Transition(updates=updates, events=events)


_HANDLERS = {
    "responsive": _on_responsive,
    "possible_seizure": _on_possible_seizure,
    "responder_arrived": _on_vision_responder_arrived,
    "verify_result": _on_verify_result,
    "verify_failed": _on_verify_failed,
    "confirm": _on_confirm,
    "false_alarm": _on_false_alarm,
    "cancel_911": _on_cancel_911,
    "milestone": _on_milestone,
    "resolve": _on_resolve,
    "accept": _on_accept,
    "decline": _on_decline,
    "arrived": _on_arrived,
    "timeout": _on_timeout,
}


def apply_signal(state: Mapping[str, Any], signal: Mapping[str, Any]) -> Transition:
    """Pure: one signal in, state updates + events + effects out. ``signal["ts"]`` must be set."""
    if state.get("resolved"):
        return _ignored("incident is over")
    handler = _HANDLERS.get(signal.get("kind"))  # type: ignore[arg-type]
    if handler is None:
        return _ignored(f"unknown signal {signal.get('kind')!r}")
    return handler(state, signal)


# ---------------------------------------------------------------------------
# Decision and planning
# ---------------------------------------------------------------------------


def classify(state: Mapping[str, Any]) -> Transition:
    """Runs once, when the voice check ends. Order matters (agent/DESIGN.md):
    false alarm (handled by the reducer, the incident is already over) -> unsafe scene -> FALL
    (raised hand) -> CARDIAC with modifiers."""
    incident_type = "fall" if state.get("responsive") else "cardiac"
    playbook = "unsafe" if state.get("scene_safe") is False else incident_type
    updates = {"type": incident_type, "playbook": playbook, "classified": True}
    after = merge_state(state, updates)
    events = [_classified_event(after)] + _gate_event(after)
    return Transition(updates=updates, events=events)


def briefing_due(state: Mapping[str, Any]) -> bool:
    if state.get("ems_briefed") or not state.get("classified"):
        return False
    playbook = state.get("playbook")
    fall_fired = state.get("type") == "fall" and state.get("fall_911") == "fired"
    if playbook == "fall":
        return fall_fired
    if playbook in ("cardiac", "unsafe"):
        return state.get("confirm") in BRIEFING_ALLOWED or fall_fired
    return False


def dispatch_due(state: Mapping[str, Any]) -> bool:
    if state.get("playbook") != "cardiac" or state.get("scene_safe") is False:
        return False
    if not gate_open(state):
        return False
    if roles_filled(state.get("roles") or {}) or state.get("waves_exhausted"):
        return False
    sent = state.get("waves_sent") or 0
    closed = state.get("waves_closed") or 0
    return sent == closed and sent < int((state.get("cfg") or {}).get("max_waves", 3))


def police_due(state: Mapping[str, Any]) -> bool:
    if state.get("police_notified"):
        return False
    return bool(
        state.get("hazards")
        or "notify_police" in (state.get("modifiers") or [])
        or state.get("scene_safe") is False
    )


def staff_due(state: Mapping[str, Any]) -> bool:
    return not state.get("staff_alerted") and state.get("playbook") in ("cardiac", "fall")


def fall_timer_due(state: Mapping[str, Any]) -> bool:
    return state.get("type") == "fall" and state.get("fall_911") == "none"


def plan(state: Mapping[str, Any]) -> list[str]:
    """The nodes that must run next, in a stable order. Empty means: wait for a signal."""
    done = state.get("done") or {}
    if state.get("resolved"):
        return [] if done.get("handoff") else ["handoff"]
    first = [n for n in FIRST_NODES if not done.get(n)]
    if first:
        return first
    if not state.get("voice_check_done"):
        return []
    if not state.get("classified"):
        return ["classify"]
    out: list[str] = []
    want = desired_script(state)
    if state.get("speak_due") or want != list(state.get("spoken_key") or []):
        out.append("guide" if is_guide(want) else "announce")
    if police_due(state):
        out.append("police")
    if staff_due(state):
        out.append("staff")
    if fall_timer_due(state):
        out.append("fall_timer")
    if briefing_due(state):
        out.append("brief_911")
    if dispatch_due(state):
        out.append("dispatch")
    return out


def derive_status(state: Mapping[str, Any]) -> str:
    """The ``incidents.status`` enum value for this state."""
    if state.get("confirm") == "false_alarm":
        return "false_alarm"
    if state.get("resolved"):
        return "resolved"
    if not state.get("voice_check_done"):
        return "voice_check" if state.get("first_instruction_at") is not None else "detected"
    if state.get("dispatches") or state.get("ems_briefed") or state.get("playbook") == "fall":
        return "responding"
    if gate_open(state):
        return "confirmed"
    return "awaiting_confirm"
