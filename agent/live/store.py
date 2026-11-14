"""Database access for the live path, behind a small interface so the graph runs offline.

``MemoryStore`` keeps rows in dicts (tests, and local runs with no Supabase project).
``SupabaseStore`` writes through ``shared.db``. Its writes go through one ordered background
queue: the hot path never waits on the network, and rows land in order (the incident row before
its events and dispatches, which reference it). Reads are awaited in a worker thread.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from datetime import UTC, datetime
from typing import Any, Protocol

log = logging.getLogger(__name__)

INCIDENT_COLUMNS = (
    "id", "type", "status", "camera_id", "building_id", "witnessed", "modifiers", "scene_safe", "hazards",
    "verification", "confirmed_by", "snapshot_url", "collapse_at", "first_instruction_at", "confirmed_at",
    "ems_notified_at", "first_accept_at", "responder_arrived_at", "cpr_started_at", "aed_arrived_at",
    "resolved_at",
)
DISPATCH_COLUMNS = ("id", "incident_id", "responder_id", "channel", "role", "wave", "status", "call_sid",
                    "sent_at", "responded_at")


def iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, tz=UTC).isoformat()


def dispatch_row(d: dict[str, Any]) -> dict[str, Any]:
    row = {k: d[k] for k in DISPATCH_COLUMNS if k in d}
    for k in ("sent_at", "responded_at"):
        if isinstance(row.get(k), (int, float)):
            row[k] = iso(row[k])
    return row


class LiveStore(Protocol):
    async def get_camera(self, camera_id: str) -> dict[str, Any] | None: ...
    async def get_camera_routes(self, camera_id: str) -> dict[str, dict[str, Any]]: ...
    async def get_building(self, building_id: str) -> dict[str, Any] | None: ...
    async def list_responders(self) -> list[dict[str, Any]]: ...
    async def insert_incident(self, row: dict[str, Any]) -> None: ...
    async def update_incident(self, incident_id: str, fields: dict[str, Any]) -> None: ...
    async def add_event(self, incident_id: str, actor: str, kind: str, payload: dict[str, Any]) -> None: ...
    async def upsert_dispatches(self, rows: list[dict[str, Any]]) -> None: ...
    async def get_dispatch(self, dispatch_id: str) -> dict[str, Any] | None: ...
    async def upload_snapshot(self, incident_id: str, jpeg: bytes) -> str | None: ...
    async def set_route_audio_url(self, camera_id: str, target: str, url: str) -> None: ...
    async def reset(self) -> None: ...
    async def flush(self) -> None: ...


class MemoryStore:
    def __init__(
        self,
        *,
        cameras: list[dict[str, Any]] | None = None,
        routes: list[dict[str, Any]] | None = None,
        buildings: list[dict[str, Any]] | None = None,
        responders: list[dict[str, Any]] | None = None,
    ) -> None:
        self.cameras = {c["id"]: dict(c) for c in cameras or []}
        self.routes: dict[tuple[str, str], dict[str, Any]] = {
            (r["camera_id"], r["target"]): dict(r) for r in routes or []
        }
        self.buildings = {b["id"]: dict(b) for b in buildings or []}
        self.responders = {r["id"]: dict(r) for r in responders or []}
        self.incidents: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.dispatches: dict[str, dict[str, Any]] = {}
        self.snapshots: dict[str, bytes] = {}

    async def get_camera(self, camera_id):
        c = self.cameras.get(camera_id)
        return copy.deepcopy(c) if c else None

    async def get_camera_routes(self, camera_id):
        return {t: copy.deepcopy(r) for (cid, t), r in self.routes.items() if cid == camera_id}

    async def get_building(self, building_id):
        b = self.buildings.get(building_id)
        return copy.deepcopy(b) if b else None

    async def list_responders(self):
        return [copy.deepcopy(r) for r in self.responders.values()]

    async def insert_incident(self, row):
        self.incidents[row["id"]] = dict(row)

    async def update_incident(self, incident_id, fields):
        if incident_id in self.incidents:
            self.incidents[incident_id].update(fields)

    async def add_event(self, incident_id, actor, kind, payload):
        self.events.append({"id": len(self.events) + 1, "incident_id": incident_id, "ts": iso(None),
                            "actor": actor, "kind": kind, "payload": payload})

    async def upsert_dispatches(self, rows):
        for row in rows:
            self.dispatches.setdefault(row["id"], {}).update(dispatch_row(row))

    async def get_dispatch(self, dispatch_id):
        d = self.dispatches.get(dispatch_id)
        return dict(d) if d else None

    async def upload_snapshot(self, incident_id, jpeg):
        self.snapshots[incident_id] = jpeg
        return f"memory://snapshots/{incident_id}.jpg"

    async def set_route_audio_url(self, camera_id, target, url):
        if (camera_id, target) in self.routes:
            self.routes[(camera_id, target)]["audio_url"] = url

    async def reset(self):
        self.incidents.clear()
        self.events.clear()
        self.dispatches.clear()
        self.snapshots.clear()

    async def flush(self):
        return None

    # test helpers
    def events_of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]


class SupabaseStore:
    """Not verified: there is no Supabase project yet."""

    def __init__(self) -> None:
        from shared import db

        self.db = db
        self._queue: asyncio.Queue | None = None
        self._worker: asyncio.Task | None = None
        self._cameras: dict[str, dict[str, Any]] = {}

    def _ensure_worker(self) -> asyncio.Queue:
        if self._queue is None:
            self._queue = asyncio.Queue()
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._drain())
        return self._queue

    async def _drain(self) -> None:
        assert self._queue is not None
        while True:
            fn, args, kwargs = await self._queue.get()
            try:
                await asyncio.to_thread(fn, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - a failed write must not break the live path
                log.warning("supabase write failed (%s): %s", getattr(fn, "__name__", fn), exc)
            finally:
                self._queue.task_done()

    def _write(self, fn, *args, **kwargs) -> None:
        self._ensure_worker().put_nowait((fn, args, kwargs))

    async def flush(self) -> None:
        if self._queue is not None:
            await self._queue.join()

    async def _read(self, fn, *args, **kwargs):
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def get_camera(self, camera_id):
        if camera_id not in self._cameras:
            row = await self._read(self.db.fetch_one, "cameras", id=camera_id)
            if row:
                self._cameras[camera_id] = row
        c = self._cameras.get(camera_id)
        return dict(c) if c else None

    async def get_camera_routes(self, camera_id):
        rows = await self._read(self.db.fetch_all, "camera_routes", camera_id=camera_id)
        return {r["target"]: r for r in rows}

    async def get_building(self, building_id):
        return await self._read(self.db.fetch_one, "buildings", id=building_id)

    async def list_responders(self):
        return await self._read(self.db.fetch_all, "responders")

    async def insert_incident(self, row):
        self._write(self.db.insert, "incidents", row)

    async def update_incident(self, incident_id, fields):
        self._write(self.db.update, "incidents", fields, id=incident_id)

    async def add_event(self, incident_id, actor, kind, payload):
        self._write(self.db.insert, "incident_events",
                    {"incident_id": incident_id, "actor": actor, "kind": kind, "payload": payload})

    async def upsert_dispatches(self, rows):
        if rows:
            self._write(self.db.upsert, "dispatches", [dispatch_row(r) for r in rows])

    async def get_dispatch(self, dispatch_id):
        return await self._read(self.db.fetch_one, "dispatches", id=dispatch_id)

    async def upload_snapshot(self, incident_id, jpeg):
        return await self._read(self.db.upload, "snapshots", f"{incident_id}.jpg", jpeg, "image/jpeg")

    async def set_route_audio_url(self, camera_id, target, url):
        self._write(self.db.update, "camera_routes", {"audio_url": url}, camera_id=camera_id, target=target)

    async def reset(self):
        await self.flush()
        rows = await self._read(self.db.fetch_all, "incidents", columns="id")
        ids = [r["id"] for r in rows]
        if ids:
            await self._read(self.db.delete, "incidents", id=ids)  # cascades events and dispatches
            try:
                await self._read(self.db.remove, "snapshots", [f"{i}.jpg" for i in ids])
            except Exception as exc:  # noqa: BLE001
                log.warning("snapshot cleanup failed: %s", exc)
        self._cameras.clear()
