"""Handoff: the Utstein-style card (spec section 9.10), built from the incident timestamps only."""

from __future__ import annotations

from typing import Any

from agent.live.persist import sync
from agent.live.store import iso


def build_handoff(state: dict[str, Any]) -> dict[str, Any]:
    m = state.get("milestones") or {}
    collapse = state.get("collapse_at")
    first = state.get("first_instruction_at")
    origin = collapse if collapse is not None else state.get("detected_at")

    def after(ts: float | None) -> float | None:
        return None if ts is None or origin is None else round(ts - origin, 1)

    return {
        "type": state.get("type"),
        "witnessed": state.get("witnessed"),
        "collapse_at": iso(collapse),  # None for found down: "found down, time unknown"
        "found_down_time_unknown": collapse is None,
        "detected_at": iso(state.get("detected_at")),
        # measured from the collapse when known, otherwise from detection
        "seconds_measured_from": "collapse" if collapse is not None else "detection",
        "first_instruction_s": after(first),
        "ems_notified_s": after(state.get("ems_notified_at")),
        "first_accept_s": after(state.get("first_accept_at")),
        "responder_arrived_s": after(m.get("responder_arrived")),
        "cpr_started_s": after(m.get("cpr_started")),
        "aed_arrived_s": after(m.get("aed_arrived")),
        "modifiers": list(state.get("modifiers") or []),
    }


def make(rt) -> dict[str, Any]:
    async def handoff(state: dict) -> dict:
        updates = {"done": {"handoff": True}}
        events = []
        if state.get("confirm") != "false_alarm":
            events.append({"actor": "desk", "kind": "resolved", "payload": {
                "by": state.get("resolved_by"), "handoff": build_handoff(state)}})
        if "all_clear" in ((state.get("camera") or {}).get("scripts") or []):
            await rt.speaker.play(["all_clear"], state["camera_id"])
        await sync(rt.store, state, updates, events)
        rt.incident_closed(state["incident_id"], state["camera_id"])
        return updates

    return {"handoff": handoff}
