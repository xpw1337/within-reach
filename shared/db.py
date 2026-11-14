"""Service-role Supabase access for Python (census, data, agent).

Only Python holds the service-role key (docs/ARCHITECTURE.md rule 2). Helpers raise on error
instead of returning it: postgrest raises ``postgrest.exceptions.APIError`` on a failed request,
and missing configuration raises ``MissingSettingError`` naming the variable.

Tests and offline tools swap the client with ``set_db(fake)`` (see ``shared/fakes.py``).
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from typing import Any

from shared.config import MissingSettingError, get_settings

_lock = threading.Lock()
_client: Any = None
_override: Any = None


def set_db(client: Any | None) -> None:
    """Use ``client`` for every later ``get_db()`` call (a fake in tests). ``None`` restores the real one."""
    global _override
    _override = client


def get_db() -> Any:
    """The cached service-role ``supabase.Client`` (or the override set with ``set_db``)."""
    global _client
    if _override is not None:
        return _override
    if _client is None:
        with _lock:
            if _client is None:
                s = get_settings()
                missing = [
                    name
                    for name, value in (
                        ("SUPABASE_URL", s.supabase_url),
                        ("SUPABASE_SERVICE_ROLE_KEY", s.supabase_service_role_key),
                    )
                    if not value
                ]
                if missing:
                    raise MissingSettingError(missing)
                from supabase import create_client

                _client = create_client(s.supabase_url, s.supabase_service_role_key)
    return _client


def _apply_filters(query: Any, filters: dict[str, Any]) -> Any:
    for column, value in filters.items():
        if value is None:
            query = query.is_(column, None)
        elif isinstance(value, (list, tuple, set, frozenset)):
            query = query.in_(column, list(value))
        else:
            query = query.eq(column, value)
    return query


PAGE_SIZE = 1000  # Supabase returns at most 1,000 rows per request by default

# Primary keys (supabase/migrations/0001_init.sql): the default sort, so paging is stable.
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


def fetch_all(
    table: str,
    *,
    columns: str = "*",
    order: str | None = None,
    desc: bool = False,
    limit: int | None = None,
    page_size: int = PAGE_SIZE,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Rows matching equality filters. A list or tuple value means ``in``; ``None`` means ``is null``.

    Pages with ``.range()`` past Supabase's 1,000-row response cap. Without ``order`` the rows are
    sorted by the table's primary key so pages never overlap.
    """
    out: list[dict[str, Any]] = []
    start = 0
    while True:
        want = page_size if limit is None else min(page_size, limit - len(out))
        if want <= 0:
            break
        query = _apply_filters(get_db().table(table).select(columns), filters)
        if order:
            query = query.order(order, desc=desc)
        else:
            for col in PRIMARY_KEYS.get(table, ()):
                query = query.order(col)
        rows = list(query.range(start, start + want - 1).execute().data or [])
        out.extend(rows)
        if len(rows) < want:
            break
        start += len(rows)
    return out


def fetch_one(table: str, *, columns: str = "*", **filters: Any) -> dict[str, Any] | None:
    """The first row matching the filters, or None."""
    rows = fetch_all(table, columns=columns, limit=1, **filters)
    return rows[0] if rows else None


def insert(table: str, rows: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert one row or many; returns the inserted rows."""
    if isinstance(rows, list) and not rows:
        return []
    return list(get_db().table(table).insert(rows).execute().data or [])


def upsert(
    table: str,
    rows: dict[str, Any] | list[dict[str, Any]],
    *,
    on_conflict: str | None = None,
    ignore_duplicates: bool = False,
) -> list[dict[str, Any]]:
    """Insert or update on the conflict columns (comma-separated; default: the primary key)."""
    if isinstance(rows, list) and not rows:
        return []
    kwargs: dict[str, Any] = {"ignore_duplicates": ignore_duplicates}
    if on_conflict:
        kwargs["on_conflict"] = on_conflict
    return list(get_db().table(table).upsert(rows, **kwargs).execute().data or [])


def update(table: str, values: dict[str, Any], **filters: Any) -> list[dict[str, Any]]:
    """Update rows matching the filters. Refuses to run with no filter."""
    if not filters:
        raise ValueError("update() needs at least one filter")
    query = _apply_filters(get_db().table(table).update(values), filters)
    return list(query.execute().data or [])


def delete(table: str, **filters: Any) -> list[dict[str, Any]]:
    """Delete rows matching the filters. Refuses to run with no filter."""
    if not filters:
        raise ValueError("delete() needs at least one filter")
    query = _apply_filters(get_db().table(table).delete(), filters)
    return list(query.execute().data or [])


def rpc(fn: str, params: dict[str, Any] | None = None) -> Any:
    """Call a Postgres function exposed through PostgREST."""
    return get_db().rpc(fn, params or {}).execute().data


def upload(bucket: str, path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to Storage (overwriting) and return the public URL (docs/CONTRACTS.md section 5)."""
    storage = get_db().storage.from_(bucket)
    storage.upload(path, data, {"content-type": content_type, "upsert": "true"})
    return public_url(bucket, path)


def public_url(bucket: str, path: str) -> str:
    return str(get_db().storage.from_(bucket).get_public_url(path)).rstrip("?")


def remove(bucket: str, paths: Iterable[str]) -> None:
    paths = list(paths)
    if paths:
        get_db().storage.from_(bucket).remove(paths)
