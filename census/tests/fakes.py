"""In-memory stand-ins for Supabase, the event sink and the LLM, so census tools run offline.

``FakeSupabase`` implements the slice of the postgrest builder API the census tools use:
``table(name).select/insert/upsert/update/delete`` with ``eq/neq/in_/is_/order/range/limit`` and
``execute()``. It applies the column defaults from 0001_init.sql that the tools rely on. It does
not emulate PostgREST error semantics: real-database checks are pending credentials.
"""

from __future__ import annotations

import copy
import itertools
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from census.tools.context import ToolContext

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "buildings": ("id",),
    "twin_nodes": ("building_id", "sweep_id"),
    "panos": ("building_id", "sweep_id"),
    "detections": ("id",),
    "assets": ("id",),
    "coverage": ("building_id", "sweep_id", "asset_type", "scenario"),
    "building_scores": ("building_id",),
    "fixes": ("id",),
    "documents": ("id",),
    "runs": ("id",),
    "agent_events": ("id",),
    "cameras": ("id",),
    "camera_routes": ("camera_id", "target"),
}
UUID_ID_TABLES = {"buildings", "detections", "assets", "fixes", "documents", "runs"}
SERIAL_ID_TABLES = {"agent_events"}
DEFAULTS: dict[str, dict[str, Any]] = {
    "buildings": {"census_status": "pending", "contacts": [], "geofence_m": 60},
    "twin_nodes": {"neighbors": [], "is_elevator": False, "is_stairs": False},
    "panos": {"tiles_done": False},
    "detections": {"status": "candidate"},
    "assets": {"source": "detected", "detection_ids": [], "verified": False, "flags": []},
    "coverage": {"scenario": "current"},
    "runs": {"buildings_done": 0, "panos_done": 0, "est_cost_usd": 0, "status": "running"},
    "agent_events": {"payload": {}},
}


@dataclass
class _Response:
    data: Any
    count: int | None = None


class _Query:
    def __init__(self, db: FakeSupabase, table: str):
        self.db, self.table = db, table
        self.op = "select"
        self.payload: Any = None
        self.on_conflict = ""
        self.filters: list[tuple[str, str, Any]] = []
        self.orders: list[tuple[str, bool]] = []
        self.window: tuple[int, int] | None = None
        self.max_rows: int | None = None

    # -- verbs
    def select(self, *columns: str, count=None, head=None):
        self.op = "select"
        return self

    def insert(self, json_rows, **_kw):
        self.op, self.payload = "insert", json_rows
        return self

    def upsert(self, json_rows, *, on_conflict: str = "", **_kw):
        self.op, self.payload, self.on_conflict = "upsert", json_rows, on_conflict
        return self

    def update(self, values, **_kw):
        self.op, self.payload = "update", values
        return self

    def delete(self, **_kw):
        self.op = "delete"
        return self

    # -- filters and modifiers
    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def neq(self, column, value):
        self.filters.append(("neq", column, value))
        return self

    def in_(self, column, values):
        self.filters.append(("in", column, list(values)))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def order(self, column, *, desc=False, nullsfirst=None, foreign_table=None):
        self.orders.append((column, desc))
        return self

    def range(self, start, end, foreign_table=None):
        self.window = (start, end)
        return self

    def limit(self, size, *, foreign_table=None):
        self.max_rows = size
        return self

    # -- execution
    def _match(self, row: dict) -> bool:
        for op, column, value in self.filters:
            have = row.get(column)
            if op == "eq" and have != value:
                return False
            if op == "neq" and have == value:
                return False
            if op == "in" and have not in value:
                return False
            if op == "is":
                want = None if value in (None, "null") else value
                if have is not want and have != want:
                    return False
        return True

    def execute(self) -> _Response:
        self.db.calls.append((self.table, self.op))
        if self.db.fail_on and self.db.fail_on(self.table, self.op, self.payload):
            raise RuntimeError(f"forced failure on {self.op} {self.table}")
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "select":
            out = [r for r in rows if self._match(r)]
            for column, desc in reversed(self.orders):
                out.sort(key=lambda r: (r.get(column) is None, r.get(column) if r.get(column) is not None else 0),
                         reverse=desc)
            if self.window:
                out = out[self.window[0]:self.window[1] + 1]
            if self.max_rows is not None:
                out = out[: self.max_rows]
            return _Response(copy.deepcopy(out))
        if self.op in ("insert", "upsert"):
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            written = [self.db._write(self.table, dict(r), upsert=self.op == "upsert",
                                      on_conflict=self.on_conflict) for r in payload]
            return _Response(copy.deepcopy(written))
        if self.op == "update":
            hit = [r for r in rows if self._match(r)]
            for r in hit:
                r.update(_jsonable(self.payload))
            return _Response(copy.deepcopy(hit))
        if self.op == "delete":
            hit = [r for r in rows if self._match(r)]
            self.db.tables[self.table] = [r for r in rows if not self._match(r)]
            return _Response(copy.deepcopy(hit))
        raise AssertionError(self.op)


def _jsonable(value: Any) -> Any:
    """Round-trip through JSON, as the real client does, so non-serializable payloads fail here too."""
    return json.loads(json.dumps(value))


class FakeSupabase:
    def __init__(self, fail_on=None):
        self.tables: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_on = fail_on  # callable(table, op, payload) -> bool, to force errors in tests
        self._serial = itertools.count(1)

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rows(self, table: str, **eq: Any) -> list[dict]:
        return [r for r in self.tables.get(table, []) if all(r.get(k) == v for k, v in eq.items())]

    def _write(self, table: str, row: dict, *, upsert: bool, on_conflict: str) -> dict:
        row = _jsonable(row)
        rows = self.tables.setdefault(table, [])
        keys = tuple(k.strip() for k in on_conflict.split(",") if k.strip()) or PRIMARY_KEYS.get(table, ())
        if upsert and keys and all(k in row for k in keys):
            for existing in rows:
                if all(existing.get(k) == row[k] for k in keys):
                    existing.update(row)
                    return existing
        full = dict(DEFAULTS.get(table, {}))
        full.update(row)
        if table in UUID_ID_TABLES and not full.get("id"):
            full["id"] = str(uuid.uuid4())
        if table in SERIAL_ID_TABLES and not full.get("id"):
            full["id"] = next(self._serial)
        pk = PRIMARY_KEYS.get(table, ())
        if pk and all(k in full for k in pk):
            for existing in rows:
                if all(existing.get(k) == full[k] for k in pk):
                    raise RuntimeError(f"duplicate key in {table}: {[full[k] for k in pk]}")
        rows.append(full)
        return full


@dataclass
class EventSink:
    """Collects agent_events the way shared.events.emit_agent_event would insert them."""

    events: list[dict] = field(default_factory=list)

    def __call__(self, run_id, agent, kind, message, building_id=None, payload=None):
        assert isinstance(message, str) and message, "console messages must be non-empty sentences"
        json.dumps(payload or {})  # payloads must be JSON
        self.events.append({"run_id": run_id, "agent": agent, "kind": kind, "message": message,
                            "building_id": building_id, "payload": payload or {}})

    def kinds(self, agent: str | None = None) -> list[str]:
        return [e["kind"] for e in self.events if agent is None or e["agent"] == agent]

    def messages(self, kind: str | None = None) -> list[str]:
        return [e["message"] for e in self.events if kind is None or e["kind"] == kind]


@dataclass
class FakeLLM:
    """Returns queued responses for complete_json and records each call."""

    responses: list[Any] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError("FakeLLM has no response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


# Unverified test-only stand-ins for the shared/thresholds.py defaults (spec section 9.4), so the
# tool tests do not depend on settings. Values follow .env.example: AED 180 s round trip,
# extinguisher 22.9 m, exit 61 m, at 1.4 m/s.
TEST_WALK_SPEED = 1.4
TEST_LIMITS_S = {"aed": 180 / 2, "extinguisher": 22.9 / TEST_WALK_SPEED, "exit": 61 / TEST_WALK_SPEED}


def make_context(db: FakeSupabase | None = None, events: EventSink | None = None,
                 llm: FakeLLM | None = None, run_id: str | None = None, adapter=None) -> ToolContext:
    return ToolContext(
        db=db if db is not None else FakeSupabase(),
        emit=events if events is not None else EventSink(),
        limit_seconds=lambda t: TEST_LIMITS_S[t],
        display_seconds=lambda t, s: None if s is None else (2 * s if t == "aed" else s),
        walk_speed_mps=TEST_WALK_SPEED,
        complete_json=llm,
        get_adapter=(lambda: adapter) if adapter is not None else None,
        run_id=run_id,
    )
