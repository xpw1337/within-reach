"""Fan-out actions after classify and the gate: dispatch waves, 911 briefing, police, staff, FALL timer."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from agent.live import responders as rs
from agent.live.briefing import build_briefing
from agent.live.persist import sync
from agent.live.reducer import dispatch_payload
from agent.live.state import TIMER_FALL_911, wave_timer
from agent.live.store import iso

log = logging.getLogger(__name__)


def make(rt) -> dict[str, Any]:
    async def dispatch(state: dict) -> dict:
        """One wave (spec section 9.10): app alert (the dispatches row) and a call to callable
        phones at the same time, then an accept timeout."""
        incident_id = state["incident_id"]
        cfg = state["cfg"]
        now = rt.clock.now()
        n = int(state.get("waves_sent") or 0) + 1
        everyone = await rt.store.list_responders()
        by_id = {r["id"]: r for r in everyone}
        # Nobody gets two alerts: anyone already dispatched, staff alert included, is skipped.
        already = [d["responder_id"] for d in state.get("dispatches") or []]
        wave = rs.next_wave(everyone, state.get("building") or {}, now, cardiac=state.get("type") == "cardiac",
                            wave_size=cfg["wave_size"], seen_window_s=cfg["responder_seen_seconds"],
                            already_sent=already)
        if not wave:
            updates = {"waves_exhausted": True}
            await sync(rt.store, state, updates)
            return updates
        rows = [{
            "id": str(uuid.uuid4()), "incident_id": incident_id, "responder_id": r["id"],
            "channel": "call" if rs.can_call(r) else "app", "role": None, "wave": n, "status": "sent",
            "call_sid": None, "sent_at": now, "responded_at": None,
        } for r in wave]
        await rt.store.upsert_dispatches(rows)  # the app alert goes out now, before the calls connect
        # The iMessage alert goes out alongside (background task: never waits, never delays a call).
        texted = {r["id"] for r in rows if rt.imessage.alert(state, r, by_id[r["responder_id"]])}

        async def call(row: dict) -> None:
            try:
                row["call_sid"] = await rt.telephony.call_responder(row, by_id[row["responder_id"]])
            except Exception as exc:  # noqa: BLE001 - a failed call leaves the app alert in place
                log.warning("responder call failed for dispatch %s: %s", row["id"], exc)

        await asyncio.gather(*(call(r) for r in rows if r["channel"] == "call"))
        for r in rows:  # docs/CONTRACTS.md: channel is imessage only when no call was placed
            if r["id"] in texted and not r.get("call_sid"):
                r["channel"] = "imessage"
        token, fires_at = rt.timers.start(incident_id, wave_timer(n), cfg["accept_timeout_seconds"])
        # dispatches.call_sid is set on the row when a call was placed (first-ring latency source)
        events = [{"actor": "system", "kind": "dispatch_sent", "payload": dispatch_payload(r)} for r in rows]
        events.append({"actor": "system", "kind": "timer_started",
                       "payload": {"timer": wave_timer(n), "fires_at": iso(fires_at)}})
        updates = {"dispatches": rows, "waves_sent": n, "timers": {wave_timer(n): token}}
        await sync(rt.store, state, updates, events)
        return updates

    async def brief_911(state: dict) -> dict:
        """Call DISPATCH_SIM_NUMBER (never a real emergency number); TwiML speaks the briefing twice.
        Never waits for responder waves."""
        now = rt.clock.now()
        text = build_briefing(state, now)
        sid = None
        error = None
        try:
            sid = await rt.telephony.call_briefing(state["incident_id"])
        except Exception as exc:  # noqa: BLE001 - recorded on the timeline, not retried
            error = f"{type(exc).__name__}: {exc}"
            log.warning("briefing call failed: %s", error)
        updates: dict[str, Any] = {"ems_briefed": True, "briefing_call_sid": sid}
        if sid:
            updates["ems_notified_at"] = now
        payload = {"briefing_text": text, "ems_door": (state.get("building") or {}).get("ems_door"),
                   "call_placed": bool(sid)}
        if error:
            payload["error"] = error
        await sync(rt.store, state, updates, [{"actor": "twilio", "kind": "ems_briefed", "payload": payload}])
        # The same briefing as text to DISPATCH_SIM_NUMBER, after it is spoken (background).
        rt.imessage.briefing_placed(state, text, call_placed=bool(sid))
        return updates

    async def police(state: dict) -> dict:
        """Demo: a timeline event only, no call (agent/DESIGN.md)."""
        updates = {"police_notified": True}
        await sync(rt.store, state, updates, [{"actor": "system", "kind": "police_notified", "payload": {
            "hazards": list(state.get("hazards") or []), "modifiers": list(state.get("modifiers") or []),
            "scene_safe": state.get("scene_safe")}}])
        return updates

    async def staff(state: dict) -> dict:
        """Staff alert: dispatches with role ``staff`` to on-duty staff and security of the building
        (app alert, plus an iMessage when the staff member is ``callable`` with ``consent_calls``)."""
        now = rt.clock.now()
        everyone = await rt.store.list_responders()
        targets = rs.staff_to_alert(everyone, state.get("building") or {})
        rows = [{
            "id": str(uuid.uuid4()), "incident_id": state["incident_id"], "responder_id": r["id"],
            "channel": "app", "role": "staff", "wave": 0, "status": "sent", "call_sid": None,
            "sent_at": now, "responded_at": None,
        } for r in targets]
        for row, r in zip(rows, targets, strict=True):  # staff are never called: a text makes it imessage
            if rt.imessage.alert(state, row, r, staff=True):
                row["channel"] = "imessage"
        updates: dict[str, Any] = {"staff_alerted": True}
        if rows:
            updates["dispatches"] = rows
        events = [{"actor": "system", "kind": "dispatch_sent", "payload": dispatch_payload(r)} for r in rows]
        events.append({"actor": "system", "kind": "staff_alerted",
                       "payload": {"responder_ids": [r["id"] for r in targets]}})
        await sync(rt.store, state, updates, events)
        return updates

    async def fall_timer(state: dict) -> dict:
        token, fires_at = rt.timers.start(state["incident_id"], TIMER_FALL_911,
                                          state["cfg"]["fall_911_cancel_seconds"])
        updates = {"fall_911": "armed", "timers": {TIMER_FALL_911: token}}
        await sync(rt.store, state, updates, [{"actor": "system", "kind": "timer_started", "payload": {
            "timer": TIMER_FALL_911, "fires_at": iso(fires_at)}}])
        return updates

    return {"dispatch": dispatch, "brief_911": brief_911, "police": police, "staff": staff,
            "fall_timer": fall_timer}
