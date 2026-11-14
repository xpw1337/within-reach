"""Mirror state changes to the database rows that dashboard and mobile read (docs/CONTRACTS.md section 3).

The incident row, its events and its dispatches are the public view of the graph state. Every
node writes through ``sync`` so the row update and the matching ``incident_events`` rows go out
together.
"""

from __future__ import annotations

from typing import Any

from agent.live.reducer import derive_status
from agent.live.state import merge_state
from agent.live.store import LiveStore, iso


def incident_row(state: dict[str, Any]) -> dict[str, Any]:
    m = state.get("milestones") or {}
    return {
        "type": state.get("type") or "unknown",
        "status": derive_status(state),
        "camera_id": state.get("camera_id"),
        "building_id": state.get("building_id"),
        "witnessed": state.get("witnessed"),
        "modifiers": list(state.get("modifiers") or []),
        "scene_safe": state.get("scene_safe"),
        "hazards": list(state.get("hazards") or []),
        "verification": state.get("verification"),
        "confirmed_by": state.get("confirmed_by"),
        "collapse_at": iso(state.get("collapse_at")),
        "first_instruction_at": iso(state.get("first_instruction_at")),
        "confirmed_at": iso(state.get("confirmed_at")),
        "ems_notified_at": iso(state.get("ems_notified_at")),
        "first_accept_at": iso(state.get("first_accept_at")),
        "responder_arrived_at": iso(m.get("responder_arrived")),
        "cpr_started_at": iso(m.get("cpr_started")),
        "aed_arrived_at": iso(m.get("aed_arrived")),
        "resolved_at": iso(state.get("resolved_at")),
    }


def changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    a, b = incident_row(before), incident_row(after)
    return {k: v for k, v in b.items() if a.get(k) != v}


async def sync(
    store: LiveStore,
    before: dict[str, Any],
    updates: dict[str, Any],
    events: list[dict[str, Any]] = (),  # type: ignore[assignment]
) -> dict[str, Any]:
    """Write the row changes implied by ``updates`` and emit ``events``. Returns the merged state."""
    after = merge_state(before, updates)
    incident_id = after["incident_id"]
    fields = changed_fields(before, after)
    if fields:
        await store.update_incident(incident_id, fields)
    if updates.get("dispatches"):
        ids = {d["id"] for d in updates["dispatches"]}
        rows = [dict(d, incident_id=incident_id) for d in after.get("dispatches") or [] if d["id"] in ids]
        await store.upsert_dispatches(rows)
    for e in events:
        await store.add_event(incident_id, e["actor"], e["kind"], e.get("payload") or {})
    return after
