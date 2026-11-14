"""In-memory stand-ins for Supabase, for offline tests in any package.

``FakeSupabase`` mimics the subset of the supabase-py client that ``shared/db.py`` and the tools
use: ``table(...).select/insert/upsert/update/delete`` with ``eq``, ``is_``, ``in_``, ``order``,
``limit`` and ``execute()``; ``rpc(...)``; and ``storage.from_(bucket)``. It enforces primary keys
and the ``buildings.costar_property_id`` unique constraint like Postgres would, fills the column
defaults that code relies on, and generates UUID / serial ids.

Usage::

    from shared import db
    from shared.fakes import FakeSupabase

    fake = FakeSupabase()
    db.set_db(fake)
    ...
    db.set_db(None)
"""

from __future__ import annotations

import copy
import itertools
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Primary keys per table (supabase/migrations/0001_init.sql).
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
    "responders": ("id",),
    "incidents": ("id",),
    "incident_events": ("id",),
    "dispatches": ("id",),
}
UNIQUE: dict[str, list[tuple[str, ...]]] = {"buildings": [("costar_property_id",)]}
UUID_ID_TABLES = {
    "buildings",
    "detections",
    "assets",
    "fixes",
    "documents",
    "runs",
    "responders",
    "incidents",
    "dispatches",
}
SERIAL_ID_TABLES = {"agent_events", "incident_events"}
DEFAULTS: dict[str, dict[str, Any]] = {
    "buildings": {"geofence_m": 60, "contacts": [], "census_status": "pending"},
    "twin_nodes": {"neighbors": [], "is_elevator": False, "is_stairs": False},
    "panos": {"tiles_done": False},
    "detections": {"status": "candidate"},
    "assets": {"source": "detected", "detection_ids": [], "verified": False, "flags": []},
    "coverage": {"scenario": "current"},
    "runs": {"buildings_done": 0, "panos_done": 0, "est_cost_usd": 0.0, "status": "running"},
    "agent_events": {"payload": {}},
    "incident_events": {"payload": {}},
    "cameras": {"has_speaker": True},
    "responders": {
        "callable": False,
        "cpr_trained": False,
        "role": "public",
        "consent_location": False,
        "consent_calls": False,
        "on_duty": True,
    },
}


class FakeDBError(Exception):
    """Raised where Postgres would raise (duplicate key, unknown function, injected failure)."""


@dataclass
class _Response:
    data: Any
    count: int | None = None


class _Query:
    def __init__(self, fake: FakeSupabase, table: str) -> None:
        self._fake = fake
        self._table = table
        self._op = "select"
        self._payload: Any = None
        self._filters: list[Callable[[dict], bool]] = []
        self._order: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._on_conflict: tuple[str, ...] | None = None
        self._ignore_duplicates = False
        self._columns = "*"

    # --- operations ---
    def select(self, *columns: str, **_: Any) -> _Query:
        self._columns = ",".join(columns) if columns else "*"
        return self

    def insert(self, rows: Any, **_: Any) -> _Query:
        self._op, self._payload = "insert", rows
        return self

    def upsert(
        self, rows: Any, *, on_conflict: str = "", ignore_duplicates: bool = False, **_: Any
    ) -> _Query:
        self._op, self._payload = "upsert", rows
        self._on_conflict = tuple(c.strip() for c in on_conflict.split(",") if c.strip()) or None
        self._ignore_duplicates = ignore_duplicates
        return self

    def update(self, values: dict, **_: Any) -> _Query:
        self._op, self._payload = "update", values
        return self

    def delete(self, **_: Any) -> _Query:
        self._op = "delete"
        return self

    # --- filters ---
    def eq(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) == value)
        return self

    def neq(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) != value)
        return self

    def is_(self, column: str, value: Any) -> _Query:
        if value in (None, "null"):
            self._filters.append(lambda r: r.get(column) is None)
        else:
            want = value if isinstance(value, bool) else str(value).lower() == "true"
            self._filters.append(lambda r: r.get(column) is want)
        return self

    def in_(self, column: str, values: Any) -> _Query:
        vals = list(values)
        self._filters.append(lambda r: r.get(column) in vals)
        return self

    def gt(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) is not None and r.get(column) > value)
        return self

    def gte(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) is not None and r.get(column) >= value)
        return self

    def lt(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) is not None and r.get(column) < value)
        return self

    def lte(self, column: str, value: Any) -> _Query:
        self._filters.append(lambda r: r.get(column) is not None and r.get(column) <= value)
        return self

    def order(self, column: str, *, desc: bool = False, **_: Any) -> _Query:
        self._order.append((column, desc))
        return self

    def limit(self, size: int, **_: Any) -> _Query:
        self._limit = size
        return self

    # --- run ---
    def _matches(self, row: dict) -> bool:
        return all(f(row) for f in self._filters)

    def _project(self, row: dict) -> dict:
        if self._columns.strip() in ("", "*"):
            return copy.deepcopy(row)
        cols = [c.strip() for c in self._columns.split(",")]
        return {c: copy.deepcopy(row.get(c)) for c in cols}

    def execute(self) -> _Response:
        self._fake._check_failure(self._table, self._op)
        rows = self._fake.tables.setdefault(self._table, [])
        if self._op == "select":
            out = [r for r in rows if self._matches(r)]
            for column, desc in reversed(self._order):
                out.sort(key=lambda r: (r.get(column) is None, r.get(column)), reverse=desc)
            if self._limit is not None:
                out = out[: self._limit]
            return _Response([self._project(r) for r in out])
        if self._op == "insert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Response([copy.deepcopy(self._fake._insert(self._table, p)) for p in payload])
        if self._op == "upsert":
            payload = self._payload if isinstance(self._payload, list) else [self._payload]
            out = []
            for p in payload:
                r = self._fake._upsert(self._table, p, self._on_conflict, self._ignore_duplicates)
                if r is not None:
                    out.append(copy.deepcopy(r))
            return _Response(out)
        if self._op == "update":
            out = []
            for r in rows:
                if self._matches(r):
                    r.update(copy.deepcopy(self._payload))
                    out.append(copy.deepcopy(r))
            return _Response(out)
        if self._op == "delete":
            keep, gone = [], []
            for r in rows:
                (gone if self._matches(r) else keep).append(r)
            self._fake.tables[self._table] = keep
            return _Response(gone)
        raise FakeDBError(f"unknown op {self._op}")


class _RPC:
    def __init__(self, fake: FakeSupabase, fn: str, params: dict) -> None:
        self._fake, self._fn, self._params = fake, fn, params

    def execute(self) -> _Response:
        self._fake._check_failure(f"rpc:{self._fn}", "rpc")
        handler = self._fake.rpcs.get(self._fn)
        if handler is None:
            raise FakeDBError(f"function {self._fn} does not exist")
        return _Response(handler(self._fake, **self._params))


class _Bucket:
    def __init__(self, fake: FakeSupabase, bucket: str) -> None:
        self._fake, self._bucket = fake, bucket

    def upload(self, path: str, file: Any, file_options: dict | None = None) -> dict:
        self._fake._check_failure(f"storage:{self._bucket}", "upload")
        if isinstance(file, (bytes, bytearray)):
            data = bytes(file)
        else:
            with open(file, "rb") as fh:
                data = fh.read()
        opts = file_options or {}
        objects = self._fake.storage_objects.setdefault(self._bucket, {})
        if path in objects and str(opts.get("upsert", "false")).lower() != "true":
            raise FakeDBError(f"object {self._bucket}/{path} already exists")
        objects[path] = {"data": bytes(data), "content_type": opts.get("content-type")}
        return {"path": path, "Key": f"{self._bucket}/{path}"}

    def get_public_url(self, path: str, options: dict | None = None) -> str:
        return f"{self._fake.url}/storage/v1/object/public/{self._bucket}/{path}"

    def remove(self, paths: list[str]) -> list[dict]:
        objects = self._fake.storage_objects.setdefault(self._bucket, {})
        return [{"name": p} for p in paths if objects.pop(p, None) is not None]


class _Storage:
    def __init__(self, fake: FakeSupabase) -> None:
        self._fake = fake

    def from_(self, bucket: str) -> _Bucket:
        return _Bucket(self._fake, bucket)


def _rpc_add_run_cost(fake: FakeSupabase, p_run_id: str, p_delta: float) -> float | None:
    for r in fake.tables.get("runs", []):
        if r.get("id") == p_run_id:
            r["est_cost_usd"] = (r.get("est_cost_usd") or 0.0) + p_delta
            return r["est_cost_usd"]
    return None


class FakeSupabase:
    """An in-memory Supabase client. ``tables`` maps table name to a list of row dicts."""

    url = "https://fake.supabase.local"

    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {}
        self.storage_objects: dict[str, dict[str, dict[str, Any]]] = {}
        self.rpcs: dict[str, Callable[..., Any]] = {"add_run_cost": _rpc_add_run_cost}
        self.storage = _Storage(self)
        self._serial = itertools.count(1)
        self._failures: dict[str, Exception] = {}

    # --- client surface ---
    def table(self, name: str) -> _Query:
        return _Query(self, name)

    from_ = table

    def rpc(self, fn: str, params: dict | None = None, **_: Any) -> _RPC:
        return _RPC(self, fn, params or {})

    # --- test helpers ---
    def fail(self, target: str, exc: Exception | None = None) -> None:
        """Make every later operation on ``target`` raise (a table name, ``rpc:<fn>`` or ``storage:<bucket>``)."""
        self._failures[target] = exc or FakeDBError(f"injected failure on {target}")

    def heal(self, target: str) -> None:
        self._failures.pop(target, None)

    def rows(self, table: str) -> list[dict[str, Any]]:
        return copy.deepcopy(self.tables.get(table, []))

    # --- internals ---
    def _check_failure(self, target: str, op: str) -> None:
        exc = self._failures.get(target)
        if exc is not None:
            raise exc

    def _with_defaults(self, table: str, row: dict) -> dict:
        new = copy.deepcopy(DEFAULTS.get(table, {}))
        new.update(copy.deepcopy(row))
        if "id" not in new or new["id"] is None:
            if table in UUID_ID_TABLES:
                new["id"] = str(uuid.uuid4())
            elif table in SERIAL_ID_TABLES:
                new["id"] = next(self._serial)
        return new

    def _find(self, table: str, cols: tuple[str, ...], row: dict) -> dict | None:
        if any(row.get(c) is None for c in cols):
            return None  # NULLs never conflict in Postgres
        for r in self.tables.get(table, []):
            if all(r.get(c) == row.get(c) for c in cols):
                return r
        return None

    def _check_unique(self, table: str, row: dict, ignore: dict | None = None) -> None:
        keys = [PRIMARY_KEYS.get(table, ("id",))] + UNIQUE.get(table, [])
        for cols in keys:
            hit = self._find(table, cols, row)
            if hit is not None and hit is not ignore:
                raise FakeDBError(
                    f"duplicate key value violates unique constraint on {table}({', '.join(cols)})"
                )

    def _insert(self, table: str, row: dict) -> dict:
        new = self._with_defaults(table, row)
        self._check_unique(table, new)
        self.tables.setdefault(table, []).append(new)
        return new

    def _upsert(
        self, table: str, row: dict, on_conflict: tuple[str, ...] | None, ignore_duplicates: bool
    ) -> dict | None:
        cols = on_conflict or PRIMARY_KEYS.get(table, ("id",))
        existing = self._find(table, cols, row)
        if existing is None:
            return self._insert(table, row)
        if ignore_duplicates:
            return None
        merged = {**existing, **copy.deepcopy(row)}
        self._check_unique(table, merged, ignore=existing)
        existing.update(merged)
        return existing


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


@dataclass
class FakeBlock:
    type: str
    text: str = ""


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 20
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_creation: Any = None


@dataclass
class FakeMessage:
    content: list[FakeBlock]
    stop_reason: str = "end_turn"
    usage: FakeUsage | None = None


def fake_json_message(
    data: Any, *, stop_reason: str = "end_turn", usage: FakeUsage | None = None
) -> FakeMessage:
    """A response whose text block is ``data`` as JSON (or ``data`` itself when it is a str)."""
    text = data if isinstance(data, str) else __import__("json").dumps(data)
    return FakeMessage(
        content=[FakeBlock("thinking"), FakeBlock("text", text)],
        stop_reason=stop_reason,
        usage=usage or FakeUsage(),
    )


class _FakeMessages:
    def __init__(self, owner: FakeAnthropic) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        self._owner.calls.append(kwargs)
        if self._owner.error is not None:
            raise self._owner.error
        if self._owner.handler is not None:
            return self._owner.handler(kwargs)
        if not self._owner.responses:
            return fake_json_message({})
        return self._owner.responses.pop(0)


class FakeAnthropic:
    """Stands in for ``anthropic.Anthropic`` / ``AnthropicBedrockMantle`` (``messages.create`` only).

    Give it scripted ``responses`` (popped in order), a ``handler(kwargs) -> message``, or an
    ``error`` to raise. Every call's kwargs are kept in ``calls``.
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        handler: Callable[[dict], Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.responses = list(responses or [])
        self.handler = handler
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(self)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def isolate_settings(monkeypatch: Any, **env: Any) -> Any:
    """Make ``get_settings()`` ignore the real ``.env`` and environment, then apply ``env``.

    ``monkeypatch`` is pytest's fixture; everything is undone after the test. Returns the settings.
    """
    from shared.config import Settings, get_settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key.upper(), str(value))
    get_settings.cache_clear()
    return get_settings()
