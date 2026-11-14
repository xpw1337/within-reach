"""Normalize dataset adapter output into ``buildings``, ``twin_nodes`` and ``panos`` (spec section 9.1).

    python -m data.load --fallback
    python -m data.load --city Houston --types gym,office --limit 100
    python -m data.load --ids <costar_property_id> ...

Idempotent: upserts on ``buildings.costar_property_id`` and on the ``twin_nodes`` / ``panos``
primary keys, so running it twice makes no duplicates. Only dataset columns are written to
``buildings``; columns the census owns (occupancy_est, vexcel, ems_door, census_status,
priority_score) are never touched. Panoramas are not downloaded here: ``panos.image_uri`` records
where to fetch each one and ``fetch_pano`` downloads lazily.

Normalization: neighbors made symmetric (the fix count is logged), unknown and self neighbors
dropped, floors forced to integers (clustered from ``y`` when missing), stairs and elevators set
from room types and labels, and as a last resort stairs inferred from edges that change floor.
With ``--fallback`` the fixture's ``assets`` and ``cameras`` rows are written too.
"""

from __future__ import annotations

import argparse
import logging
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any

from data.adapter import DatasetAdapter, get_adapter
from shared import db
from shared.types import BuildingRecord, TwinNode

log = logging.getLogger("data.load")

_STAIRS_RE = re.compile(r"\bstair")
_ELEVATOR_RE = re.compile(r"\b(elevator|lift)s?\b")
FLOOR_GAP_M = 2.0  # sweeps whose heights differ by more than this are on different floors
CHUNK = 500
_ASSET_NS = uuid.UUID("6f1c2b8e-7a51-4c1e-9a0b-3f7d2e5c1a90")  # namespace for stable fixture asset ids


@dataclass
class NormalizeReport:
    neighbor_fixes: int = 0  # missing back-links added
    dropped_neighbors: int = 0  # links to unknown sweeps or to self
    floors_clustered: bool = False
    stairs_inferred: int = 0


@dataclass
class LoadSummary:
    costar_property_id: str
    building_id: str
    twin_nodes: int
    panos: int
    assets: int = 0
    cameras: int = 0
    report: NormalizeReport = field(default_factory=NormalizeReport)


# ---------------------------------------------------------------------------
# Normalization (pure)
# ---------------------------------------------------------------------------


def cluster_floors(heights: Iterable[float], gap: float = FLOOR_GAP_M) -> dict[float, int]:
    """Map each height to a floor index: sorted heights split wherever consecutive values differ by > gap."""
    floors: dict[float, int] = {}
    level, prev = 0, None
    for h in sorted(set(heights)):
        if prev is not None and h - prev > gap:
            level += 1
        floors[h] = level
        prev = h
    return floors


def _int_floor(value: Any) -> int | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else None


def normalize_twin(nodes: list[TwinNode]) -> tuple[list[TwinNode], NormalizeReport]:
    rep = NormalizeReport()
    nodes = [replace(n, neighbors=list(n.neighbors or [])) for n in nodes]
    ids = {n.sweep_id for n in nodes}

    # Integer floors; cluster y when any floor is missing or not integral.
    floors = [_int_floor(n.floor) for n in nodes]
    if any(f is None for f in floors):
        mapping = cluster_floors(n.y for n in nodes)
        for n in nodes:
            n.floor = mapping[n.y]
        rep.floors_clustered = True
    else:
        for n, f in zip(nodes, floors, strict=True):
            n.floor = f

    # Clean and symmetrize neighbors.
    by_id = {n.sweep_id: n for n in nodes}
    for n in nodes:
        clean = []
        for m in n.neighbors:
            if m == n.sweep_id or m not in ids:
                rep.dropped_neighbors += 1
            elif m not in clean:
                clean.append(m)
        n.neighbors = clean
    for n in nodes:
        for m in n.neighbors:
            other = by_id[m]
            if n.sweep_id not in other.neighbors:
                other.neighbors.append(n.sweep_id)
                rep.neighbor_fixes += 1

    # Stairs and elevators from what the dataset offers.
    for n in nodes:
        text = f"{n.room_type or ''} {n.label or ''}".lower()
        if _STAIRS_RE.search(text):
            n.is_stairs = True
        if _ELEVATOR_RE.search(text):
            n.is_elevator = True
    if not any(n.is_stairs or n.is_elevator for n in nodes):
        for n in nodes:
            for m in n.neighbors:
                other = by_id[m]
                if other.floor != n.floor and not n.is_stairs:
                    n.is_stairs = True
                    rep.stairs_inferred += 1
                    break
    return nodes, rep


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

_BUILDING_COLUMNS = (
    "costar_property_id",
    "matterport_model_id",
    "name",
    "address",
    "city",
    "lat",
    "lng",
    "property_type",
    "floors",
    "size_sqft",
    "tenants_count",
    "manager",
    "contacts",
)


def building_row(rec: BuildingRecord) -> dict[str, Any]:
    row = {c: getattr(rec, c) for c in _BUILDING_COLUMNS}
    row["contacts"] = row["contacts"] or []
    return row


def node_row(building_id: str, n: TwinNode) -> dict[str, Any]:
    return {
        "building_id": building_id,
        "sweep_id": n.sweep_id,
        "floor": n.floor,
        "x": float(n.x),
        "y": float(n.y),
        "z": float(n.z),
        "neighbors": list(n.neighbors),
        "room_type": n.room_type,
        "label": n.label,
        "is_elevator": bool(n.is_elevator),
        "is_stairs": bool(n.is_stairs),
    }


def asset_id(costar_property_id: str, a: dict[str, Any]) -> str:
    """Stable id for a fixture asset, so reloading updates it instead of adding a copy."""
    key = f"{costar_property_id}|{a['type']}|{a.get('sweep_id')}|{a.get('label')}"
    return str(uuid.uuid5(_ASSET_NS, key))


def _chunks(rows: list[dict[str, Any]]) -> Iterable[list[dict[str, Any]]]:
    for i in range(0, len(rows), CHUNK):
        yield rows[i : i + CHUNK]


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def load_building(
    adapter: DatasetAdapter, rec: BuildingRecord, *, with_fixture_rows: bool = False
) -> LoadSummary:
    (b,) = db.upsert("buildings", building_row(rec), on_conflict="costar_property_id")
    building_id = b["id"]
    rec.id = building_id

    nodes, rep = normalize_twin(adapter.get_twin(rec))
    for chunk in _chunks([node_row(building_id, n) for n in nodes]):
        db.upsert("twin_nodes", chunk, on_conflict="building_id,sweep_id")

    pano_rows = [
        {"building_id": building_id, "sweep_id": p.sweep_id, "image_uri": p.image_uri}
        for p in adapter.list_panos(rec)
    ]
    for chunk in _chunks(pano_rows):
        db.upsert("panos", chunk, on_conflict="building_id,sweep_id")

    summary = LoadSummary(rec.costar_property_id, building_id, len(nodes), len(pano_rows), report=rep)
    if rep.neighbor_fixes or rep.dropped_neighbors:
        log.warning(
            "%s: added %d missing neighbor back-links, dropped %d invalid neighbors",
            rec.costar_property_id,
            rep.neighbor_fixes,
            rep.dropped_neighbors,
        )
    if rep.floors_clustered:
        log.warning("%s: floors clustered from sweep heights", rec.costar_property_id)
    if rep.stairs_inferred:
        log.warning(
            "%s: %d stairs nodes inferred from floor-changing edges",
            rec.costar_property_id,
            rep.stairs_inferred,
        )

    if with_fixture_rows:
        summary.assets, summary.cameras = _load_fixture_rows(
            adapter, rec, building_id, {n.sweep_id: n for n in nodes}
        )
    return summary


def _load_fixture_rows(
    adapter: Any, rec: BuildingRecord, building_id: str, nodes: dict[str, TwinNode]
) -> tuple[int, int]:
    assets = []
    for a in getattr(adapter, "get_assets", lambda _r: [])(rec):
        n = nodes.get(a.get("sweep_id"))
        source = a.get("source", "manual")
        assets.append(
            {
                "id": asset_id(rec.costar_property_id, a),
                "building_id": building_id,
                "type": a["type"],
                "sweep_id": a.get("sweep_id"),
                "floor": a.get("floor", n.floor if n else None),
                "label": a.get("label"),
                "x": a.get("x", n.x if n else None),
                "y": a.get("y", n.y if n else None),
                "z": a.get("z", n.z if n else None),
                "source": source,
                "verified": a.get("verified", source in ("manual", "tag")),
                "flags": a.get("flags", []),
            }
        )
    if assets:
        db.upsert("assets", assets)

    cameras = 0
    cam = getattr(adapter, "get_camera", lambda _r: None)(rec)
    if cam:
        n = nodes.get(cam.get("sweep_id"))
        db.upsert(
            "cameras",
            {
                "id": cam["id"],
                "name": cam.get("name", "Lobby camera 1" if cam["id"] == "cam-lobby-1" else cam["id"]),
                "building_id": building_id,
                "sweep_id": cam.get("sweep_id"),
                "floor": cam.get("floor", n.floor if n else None),
                "landmark": cam.get("landmark"),
                "lat": cam.get("lat", rec.lat),
                "lng": cam.get("lng", rec.lng),
                "has_speaker": cam.get("has_speaker", True),
            },
        )
        cameras = 1
    return len(assets), cameras


def load(
    adapter: DatasetAdapter,
    *,
    city: str | None = None,
    types: list[str] | None = None,
    ids: list[str] | None = None,
    limit: int | None = None,
    with_fixture_rows: bool = False,
) -> list[LoadSummary]:
    out: list[LoadSummary] = []
    for rec in adapter.list_buildings(city=city, types=types):
        if ids and rec.costar_property_id not in ids:
            continue
        out.append(load_building(adapter, rec, with_fixture_rows=with_fixture_rows))
        log.info("loaded %s (%d sweeps, %d panos)", rec.costar_property_id, out[-1].twin_nodes, out[-1].panos)
        if limit is not None and len(out) >= limit:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m data.load", description=__doc__.split("\n")[0])
    ap.add_argument(
        "--fallback", action="store_true", help="load demo/fallback/building.json with its assets and camera"
    )
    ap.add_argument("--city", help="Houston | Los Angeles")
    ap.add_argument("--types", help="comma-separated property types, e.g. gym,office")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", nargs="*", help="costar_property_id values")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.fallback:
        from data.fallback import FallbackAdapter

        adapter: DatasetAdapter = FallbackAdapter()
    else:
        adapter = get_adapter()
    types = [t.strip() for t in args.types.split(",")] if args.types else None
    summaries = load(
        adapter, city=args.city, types=types, ids=args.ids, limit=args.limit, with_fixture_rows=args.fallback
    )
    for s in summaries:
        print(
            f"{s.costar_property_id}: building {s.building_id}, {s.twin_nodes} sweeps, {s.panos} panos, "
            f"{s.assets} assets, {s.cameras} cameras, {s.report.neighbor_fixes} neighbor fixes"
        )
    if not summaries:
        print("no buildings matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
