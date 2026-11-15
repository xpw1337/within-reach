"""The first nodes: ingest, local first response (the hot path), and the three parallel starts."""

from __future__ import annotations

from typing import Any

from agent.live.persist import incident_row, sync
from agent.live.playbooks import renderable_scripts
from agent.live.state import TIMER_CONFIRM_AUTO, TIMER_FOUND_DOWN, TIMER_VOICE_CHECK
from agent.live.store import iso


def make(rt) -> dict[str, Any]:
    async def ingest(state: dict) -> dict:
        camera, building, routes = await rt.camera_context(state["camera_id"])
        updates = {
            "camera": camera,
            "building": building,
            "routes": routes,
            "building_id": camera.get("building_id"),
        }
        merged = {**state, **updates}
        row = {"id": state["incident_id"], **incident_row(merged)}
        await rt.store.insert_incident(row)
        await rt.store.add_event(state["incident_id"], "vision", "detected", {
            "camera_id": state["camera_id"], "witnessed": state.get("witnessed"),
            "victim_track_id": state.get("victim_track_id")})
        return updates

    async def first_response(state: dict) -> dict:
        """Hot path: play the pre-rendered voice check. No LLM, TTS, Twilio or Storage call."""
        camera = state.get("camera") or {}
        if "voice_check" not in (camera.get("scripts") or []):
            # No audio on disk: say so on the timeline rather than claim an instruction was given.
            await rt.store.add_event(state["incident_id"], "system", "speak",
                                     {"script_id": "voice_check", "error": "no audio for this camera"})
            return {"spoken_key": []}
        await rt.speaker.play(["voice_check"], state["camera_id"])
        now = rt.clock.now()
        rt.metrics["last_event_to_audio_s"] = now - state["detected_at"]
        texts = renderable_scripts(camera, state.get("routes") or {})
        updates = {"first_instruction_at": now, "spoken_key": ["voice_check"]}
        events = [{"actor": "system", "kind": "speak", "payload": {
            "script_id": "voice_check", "text": texts.get("voice_check"),
            "audio_url": (camera.get("audio_urls") or {}).get("voice_check")}}]
        await sync(rt.store, state, updates, events)
        return updates

    async def verify(state: dict) -> dict:
        frame = rt.frames.pop(state["incident_id"], None)
        rt.spawn(rt.run_verify(state["incident_id"], frame, (state.get("camera") or {}).get("landmark")),
                 incident_id=state["incident_id"])
        return {"done": {"verify": True}}

    async def request_confirm(state: dict) -> dict:
        cfg = state["cfg"]
        incident_id = state["incident_id"]
        if not cfg.get("require_confirm", True):
            # REQUIRE_CONFIRM=false: no desk confirm; the gate opens at once and responders go out as
            # soon as the voice check classifies the incident.
            name, delay, key = TIMER_CONFIRM_AUTO, 0.0, "auto_proceed_at"
        elif state.get("witnessed"):
            name, delay, key = TIMER_CONFIRM_AUTO, cfg["confirm_auto_proceed_seconds"], "auto_proceed_at"
        else:
            name, delay, key = TIMER_FOUND_DOWN, cfg["found_down_escalate_seconds"], "escalate_at"
        token, fires_at = rt.timers.start(incident_id, name, delay)
        events = [
            {"actor": "system", "kind": "confirm_requested", "payload": {key: iso(fires_at)}},
            {"actor": "system", "kind": "timer_started", "payload": {"timer": name, "fires_at": iso(fires_at)}},
        ]
        updates = {"timers": {name: token}, "done": {"request_confirm": True}}
        await sync(rt.store, state, updates, events)
        return updates

    async def voice_check(state: dict) -> dict:
        token, fires_at = rt.timers.start(state["incident_id"], TIMER_VOICE_CHECK,
                                          state["cfg"]["voice_check_seconds"])
        updates = {"timers": {TIMER_VOICE_CHECK: token}, "done": {"voice_check": True}}
        await sync(rt.store, state, updates, [{"actor": "system", "kind": "timer_started", "payload": {
            "timer": TIMER_VOICE_CHECK, "fires_at": iso(fires_at)}}])
        return updates

    return {
        "ingest": ingest,
        "first_response": first_response,
        "verify": verify,
        "request_confirm": request_confirm,
        "voice_check": voice_check,
    }
