"""Small row helpers over the Supabase (PostgREST) client on the active tool context.

Filters are tuples ``(op, column, value)`` with ``op`` in ``eq | neq | in | is``. Reads page
through results because PostgREST caps a response (1000 rows on Supabase by default). Writes go
in chunks so one building's coverage never becomes one oversized request.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from census.tools.context import ctx
from shared.types import TwinNode, from_row

Filter = tuple[str, str, Any]

PAGE_SIZE = 1000
WRITE_CHUNK = 500


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _apply(query: Any, filters: Iterable[Filter]) -> Any:
    for op, column, value in filters:
        if op == "eq":
            query = query.eq(column, value)
        elif op == "neq":
            query = query.neq(column, value)
        elif op == "in":
            query = query.in_(column, list(value))
        elif op == "is":
            query = query.is_(column, value)
        else:
            raise ValueError(f"unsupported filter op {op!r}")
    return query


def fetch_all(table: str, *, columns: str = "*", filters: Sequence[Filter] = (),
              order: str | None = None, desc: bool = False) -> list[dict]:
    rows: list[dict] = []
    start = 0
    while True:
        query = _apply(ctx().db.table(table).select(columns), filters)
        if order:
            query = query.order(order, desc=desc)
        page = query.range(start, start + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


ID_CHUNK = 150  # ids per `in` filter: keeps the request URL short


def fetch_by_ids(table: str, ids: Sequence[str], *, column: str = "id", columns: str = "*",
                 filters: Sequence[Filter] = ()) -> list[dict]:
    rows: list[dict] = []
    unique = list(dict.fromkeys(ids))
    for i in range(0, len(unique), ID_CHUNK):
        rows.extend(fetch_all(table, columns=columns,
                              filters=[*filters, ("in", column, unique[i:i + ID_CHUNK])]))
    return rows


def fetch_one(table: str, *, columns: str = "*", filters: Sequence[Filter] = ()) -> dict | None:
    data = _apply(ctx().db.table(table).select(columns), filters).limit(1).execute().data or []
    return data[0] if data else None


def insert(table: str, rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(rows), WRITE_CHUNK):
        out.extend(ctx().db.table(table).insert(rows[i:i + WRITE_CHUNK]).execute().data or [])
    return out


def upsert(table: str, rows: list[dict], *, on_conflict: str) -> None:
    for i in range(0, len(rows), WRITE_CHUNK):
        ctx().db.table(table).upsert(rows[i:i + WRITE_CHUNK], on_conflict=on_conflict).execute()


def update(table: str, values: dict, *, filters: Sequence[Filter]) -> None:
    if not filters:
        raise ValueError("refusing an update without a filter")
    _apply(ctx().db.table(table).update(values), filters).execute()


def delete(table: str, *, filters: Sequence[Filter]) -> None:
    if not filters:
        raise ValueError("refusing a delete without a filter")
    _apply(ctx().db.table(table).delete(), filters).execute()


# ---------------------------------------------------------------------------
# Census row loaders
# ---------------------------------------------------------------------------

# Asset sources that count as equipment that exists today. 'proposed' assets are the Fixer's
# suggestions and only feed coverage(scenario='proposed').
CURRENT_SOURCES = ("detected", "tag", "manual")


def load_building(building_id: str) -> dict | None:
    return fetch_one("buildings", filters=[("eq", "id", building_id)])


def load_twin_nodes(building_id: str) -> list[TwinNode]:
    rows = fetch_all("twin_nodes", filters=[("eq", "building_id", building_id)], order="sweep_id")
    nodes = []
    for row in rows:
        node = from_row(TwinNode, row)
        node.neighbors = list(node.neighbors or [])
        node.is_elevator = bool(node.is_elevator)
        node.is_stairs = bool(node.is_stairs)
        nodes.append(node)
    return nodes


def load_assets(building_id: str, types: Sequence[str] | None = None,
                sources: Sequence[str] = CURRENT_SOURCES) -> list[dict]:
    filters: list[Filter] = [("eq", "building_id", building_id), ("in", "source", list(sources))]
    if types is not None:
        filters.append(("in", "type", list(types)))
    return fetch_all("assets", filters=filters, order="id")


def set_building(building_id: str, **values: Any) -> None:
    update("buildings", values, filters=[("eq", "id", building_id)])
