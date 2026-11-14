"""The live runtime and ``deliver``: the single entry point that resumes the graph.

``deliver(incident_id, signal)`` serializes per incident with an ``asyncio.Lock`` so two resumes
never interleave (measured: two unlocked concurrent resumes on one thread lose a signal).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from typing import Any

from langgraph.types import Command

from agent.live.config import LiveConfig
from agent.live.graph import build_graph
from agent.live.reducer import Transition
from agent.live.state import initial_state
from agent.live.timers import Clock, TimerRegistry

log = logging.getLogger(__name__)


class LiveRuntime:
    def __init__(self, *, cfg: LiveConfig, store, speaker, telephony, verifier, clock: Clock,
                 checkpointer) -> None:
        self.cfg = cfg
        self.store = store
        self.speaker = speaker
        self.telephony = telephony
        self.verifier = verifier
        self.clock = clock
        self.checkpointer = checkpointer
        self.timers = TimerRegistry(clock, self.deliver)
        self.graph = build_graph(self).compile(checkpointer=checkpointer)
        self.frames: dict[str, bytes] = {}
        self.open_by_camera: dict[str, str] = {}
        self.known_incidents: set[str] = set()
        self.last_transition: dict[str, Transition] = {}
        self.metrics: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._camera_locks: dict[str, asyncio.Lock] = {}
        self._ctx_cache: dict[str, tuple[dict, dict, dict]] = {}
        self._tasks: dict[asyncio.Task, str | None] = {}
        if hasattr(clock, "settle"):
            clock.settle = self.settle  # FakeClock: let background work finish between timer fires

    # -- plumbing ----------------------------------------------------------

    def _config(self, incident_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": incident_id}, "recursion_limit": 100}

    def _lock(self, key: str, table: dict[str, asyncio.Lock]) -> asyncio.Lock:
        if key not in table:
            table[key] = asyncio.Lock()
        return table[key]

    def spawn(self, coro: Coroutine, incident_id: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._tasks[task] = incident_id
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.pop(task, None)
        if not task.cancelled() and task.exception() is not None:
            log.error("background task failed", exc_info=task.exception())

    async def settle(self) -> None:
        """Wait until tracked background tasks stop making progress (tests). Tasks blocked on the
        fake clock stay pending; they resume when the clock advances."""
        for _ in range(200):
            await asyncio.sleep(0)
            pending = [t for t in self._tasks if not t.done()]
            if not pending:
                return
            done, _ = await asyncio.wait(pending, timeout=0.05)
            if not done:
                return

    async def camera_context(self, camera_id: str, refresh: bool = False) -> tuple[dict, dict, dict]:
        """cameras row (+ available audio), building row, routes by target. Cached: warm-up fills it so
        the hot path does not read the network."""
        if refresh or camera_id not in self._ctx_cache:
            camera = await self.store.get_camera(camera_id) or {"id": camera_id}
            building = {}
            if camera.get("building_id"):
                building = await self.store.get_building(camera["building_id"]) or {}
            routes = await self.store.get_camera_routes(camera_id)
            self._ctx_cache[camera_id] = (camera, building, routes)
        camera, building, routes = self._ctx_cache[camera_id]
        camera = dict(camera, scripts=self.speaker.available(camera_id))
        return camera, dict(building), {k: dict(v) for k, v in routes.items()}

    def set_audio_urls(self, camera_id: str, urls: dict[str, str]) -> None:
        if camera_id in self._ctx_cache:
            camera, building, routes = self._ctx_cache[camera_id]
            self._ctx_cache[camera_id] = (dict(camera, audio_urls=urls), building, routes)

    # -- entry points ------------------------------------------------------

    async def start_incident(self, *, camera_id: str, victim_track_id: int, witnessed: bool,
                             event_ts: float | None = None, frame: bytes | None = None) -> tuple[str, dict]:
        """``person_down``. One open incident per camera: a repeat returns the open one."""
        async with self._lock(camera_id, self._camera_locks):
            existing = self.open_by_camera.get(camera_id)
            if existing:
                return existing, await self.get_state(existing) or {}
            now = self.clock.now()
            ts = now if event_ts is None else float(event_ts)
            incident_id = str(uuid.uuid4())
            state = initial_state(
                incident_id=incident_id, camera_id=camera_id, victim_track_id=int(victim_track_id),
                witnessed=bool(witnessed), detected_at=now,
                # witnessed: the drop happened DOWN_SECONDS before the down timer finished
                collapse_at=(ts - self.cfg.down_seconds) if witnessed else None,
                cfg=self.cfg.as_state(),
            )
            self.open_by_camera[camera_id] = incident_id
            self.known_incidents.add(incident_id)
            if frame:
                self.frames[incident_id] = frame
            async with self._lock(incident_id, self._locks):
                out = await self.graph.ainvoke(state, self._config(incident_id))
            if frame:
                self.spawn(self._upload_snapshot(incident_id, frame), incident_id)
            return incident_id, _clean(out)

    async def deliver(self, incident_id: str, signal: dict[str, Any]) -> dict[str, Any] | None:
        signal = dict(signal)
        signal.setdefault("ts", self.clock.now())
        async with self._lock(incident_id, self._locks):
            snap = await self.graph.aget_state(self._config(incident_id))
            if not snap.values:
                return None
            if not snap.next:  # finished (resolved): nothing applies any more
                self.last_transition[incident_id] = Transition(applied=False, reason="incident is over")
                return _clean(snap.values)
            out = await self.graph.ainvoke(Command(resume=signal), self._config(incident_id))
            return _clean(out)

    async def get_state(self, incident_id: str) -> dict[str, Any] | None:
        snap = await self.graph.aget_state(self._config(incident_id))
        return _clean(snap.values) if snap.values else None

    async def find_dispatch(self, dispatch_id: str) -> tuple[str | None, dict[str, Any] | None]:
        """(incident_id, dispatch) for a dispatch id, from the graph state."""
        for incident_id in list(self.known_incidents):
            state = await self.get_state(incident_id) or {}
            for d in state.get("dispatches") or []:
                if d.get("id") == dispatch_id:
                    return incident_id, d
        row = await self.store.get_dispatch(dispatch_id)
        if row and row.get("incident_id"):
            state = await self.get_state(row["incident_id"]) or {}
            for d in state.get("dispatches") or []:
                if d.get("id") == dispatch_id:
                    return row["incident_id"], d
        return None, None

    def incident_closed(self, incident_id: str, camera_id: str) -> None:
        if self.open_by_camera.get(camera_id) == incident_id:
            del self.open_by_camera[camera_id]
        self.timers.cancel_incident(incident_id)
        self.frames.pop(incident_id, None)

    # -- side effects ------------------------------------------------------

    async def run_effects(self, state: dict[str, Any], effects: list[dict[str, Any]]) -> None:
        incident_id = state["incident_id"]
        for eff in effects:
            kind = eff.get("type")
            if kind == "cancel_timer":
                self.timers.cancel(incident_id, eff["name"])
            elif kind == "stop_audio":
                await self.speaker.stop()
            elif kind == "hangup":
                self.spawn(self._hangup(eff["call_sid"]), incident_id)

    async def _hangup(self, call_sid: str) -> None:
        try:
            await self.telephony.hangup(call_sid)
        except Exception as exc:  # noqa: BLE001
            log.warning("hangup %s failed: %s", call_sid, exc)

    async def run_verify(self, incident_id: str, frame: bytes | None, landmark: str | None) -> None:
        try:
            result = await self.verifier.verify(frame, landmark)
        except Exception as exc:  # noqa: BLE001 - the graph proceeds without the scene check
            await self.deliver(incident_id, {"kind": "verify_failed", "source": "llm", "reason": str(exc)})
            return
        await self.deliver(incident_id, {"kind": "verify_result", "source": "llm", "result": result})

    async def _upload_snapshot(self, incident_id: str, frame: bytes) -> None:
        try:
            url = await self.store.upload_snapshot(incident_id, frame)
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot upload failed: %s", exc)
            return
        if url:
            await self.store.update_incident(incident_id, {"snapshot_url": url})

    async def reset(self) -> None:
        """Cancel timers and background work, hang up calls, stop audio, clear incidents and checkpoints."""
        self.timers.cancel_all()
        current = asyncio.current_task()
        for task in list(self._tasks):
            if task is not current and not task.done():
                task.cancel()
        sids = []
        for incident_id in list(self.known_incidents):
            state = await self.get_state(incident_id) or {}
            sids += [d["call_sid"] for d in state.get("dispatches") or []
                     if d.get("call_sid") and d.get("status") in ("sent", "accepted", "timeout", "arrived")]
            if state.get("briefing_call_sid") and not state.get("resolved"):
                sids.append(state["briefing_call_sid"])
            await self.checkpointer.adelete_thread(incident_id)
        for sid in sids:
            await self._hangup(sid)
        await self.speaker.stop()
        await self.store.reset()
        self.frames.clear()
        self.open_by_camera.clear()
        self.known_incidents.clear()
        self.last_transition.clear()
        self._locks.clear()
        self._ctx_cache.clear()


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if k != "__interrupt__"}
