"""announce (playbook script, repeats every 20 s until CPR starts) and guide (CPR coaching loop)."""

from __future__ import annotations

from typing import Any

from agent.live.persist import sync
from agent.live.playbooks import desired_script, renderable_scripts, repeat_seconds
from agent.live.state import TIMER_ANNOUNCE, TIMER_GUIDE
from agent.live.store import iso

SCRIPT_TARGET = {"cardiac_main": "aed", "mod_overdose": "naloxone"}


def make(rt) -> dict[str, Any]:
    async def speak(state: dict, timer_name: str) -> dict:
        incident_id = state["incident_id"]
        camera = state.get("camera") or {}
        routes = state.get("routes") or {}
        want = desired_script(state)
        timers: dict[str, Any] = {}
        events: list[dict[str, Any]] = []
        for name in (TIMER_ANNOUNCE, TIMER_GUIDE):
            if name in (state.get("timers") or {}):
                rt.timers.cancel(incident_id, name)
                timers[name] = None
        if want:
            await rt.speaker.play(want, state["camera_id"])
            texts = renderable_scripts(camera, routes)
            urls = camera.get("audio_urls") or {}
            for script_id in want:
                payload = {"script_id": script_id, "text": texts.get(script_id),
                           "audio_url": urls.get(script_id)}
                target = SCRIPT_TARGET.get(script_id)
                if target:
                    payload["target"] = target
                    payload["audio_url"] = payload["audio_url"] or (routes.get(target) or {}).get("audio_url")
                events.append({"actor": "system", "kind": "speak", "payload": payload})
            interval = repeat_seconds(want, state["cfg"])
            if interval:
                token, fires_at = rt.timers.start(incident_id, timer_name, interval)
                timers[timer_name] = token
                events.append({"actor": "system", "kind": "timer_started",
                               "payload": {"timer": timer_name, "fires_at": iso(fires_at)}})
        elif state.get("spoken_key"):
            await rt.speaker.stop()
        updates: dict[str, Any] = {"spoken_key": want, "speak_due": False}
        if timers:
            updates["timers"] = timers
        await sync(rt.store, state, updates, events)
        return updates

    async def announce(state: dict) -> dict:
        return await speak(state, TIMER_ANNOUNCE)

    async def guide(state: dict) -> dict:
        return await speak(state, TIMER_GUIDE)

    return {"announce": announce, "guide": guide}
