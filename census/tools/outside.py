"""Outside subagent tools: get_vexcel, pick_ems_door (spec sections 9.2, 9.7).

Writes ``buildings.vexcel`` and ``buildings.ems_door``. The highest-risk zone is the set of scan
positions in the AED red zone (cardiac arrest is what EMS races); with none red it is the single
position farthest from an AED; with no AED visible in the scan it is every position.
"""

from __future__ import annotations

import logging
from dataclasses import asdict

import networkx as nx

from census.core.ems_door import pick_ems_door as core_pick
from census.core.graph import WEIGHT, walking_time_map
from census.core.scoring import red_sweeps
from census.tools import db
from census.tools.context import ctx
from census.tools.events import decision, result, tool_call, warning
from census.tools.mapper import load, source_sweeps
from shared.types import BuildingRecord, from_row

log = logging.getLogger(__name__)

AGENT = "outside"


def get_vexcel(building_id: str) -> dict:
    """Entrances, ambulance parking and hydrants from the dataset adapter (or the stored copy)."""
    tool_call(AGENT, "get_vexcel", {"building_id": building_id}, building_id)
    row = db.load_building(building_id)
    if row is None:
        raise ValueError(f"building {building_id} not found")
    info = None
    adapter_factory = ctx().get_adapter
    if adapter_factory is not None:
        try:
            adapter = adapter_factory()
            info = adapter.get_vexcel(from_row(BuildingRecord, row)) if adapter is not None else None
        except Exception as exc:  # noqa: BLE001 - outside data is optional; keep the stored copy
            log.warning("get_vexcel adapter failed: %s", exc)
            warning(AGENT, "vexcel_unavailable",
                    "Outside data could not be fetched from the dataset; using the stored copy if any.",
                    building_id, {"error": type(exc).__name__})
    vexcel = asdict(info) if info is not None else (row.get("vexcel") or None)
    if info is not None:
        db.set_building(building_id, vexcel=vexcel)
    if not vexcel:
        warning(AGENT, "no_vexcel", "No outside data for this building; the EMS door cannot be chosen.",
                building_id)
        return {"entrances": 0, "ambulance_parking": 0, "hydrants": 0}
    counts = {k: len(vexcel.get(k) or []) for k in ("entrances", "ambulance_parking", "hydrants")}
    result(AGENT, "get_vexcel",
           f"Outside data: {counts['entrances']} entrances, {counts['ambulance_parking']} ambulance "
           f"parking spots, {counts['hydrants']} hydrants.", building_id, counts)
    return counts


def _risk_zone(graph: nx.Graph, aed_times: dict[str, float], limit_s: float) -> tuple[list[str], str]:
    sweeps = sorted(graph.nodes)
    if not aed_times:
        return sweeps, "the whole scan, since no AED is visible in the scan"
    red = red_sweeps(aed_times, sweeps, limit_s)
    if red:
        return red, "the AED red zone"
    worst = max(aed_times, key=lambda s: (aed_times[s], s))
    label = graph.nodes[worst].get("label")
    return [worst], f"the position farthest from an AED{f', {label}' if label else ''}"


def pick_ems_door(building_id: str) -> dict:
    """Choose the ambulance entrance, staging spot and nearest hydrant; writes buildings.ems_door."""
    tool_call(AGENT, "pick_ems_door", {"building_id": building_id}, building_id)
    loaded = load(building_id)
    vexcel = loaded.building.get("vexcel") or {}
    entrances = vexcel.get("entrances") or []
    if not entrances:
        warning(AGENT, "no_entrances", "No entrances in the outside data, so no EMS door was chosen.",
                building_id)
        return {"ems_door": None}

    aed_times = walking_time_map(loaded.graph, source_sweeps(loaded, "aed")[0], ctx().walk_speed_mps)
    zone, zone_desc = _risk_zone(loaded.graph, aed_times, ctx().limit_seconds("aed"))
    walk: dict[int, float] = {}
    for i, e in enumerate(entrances):
        sweep = e.get("sweep_id")
        if sweep not in loaded.graph:
            continue
        lengths = nx.single_source_dijkstra_path_length(loaded.graph, sweep, weight=WEIGHT)
        reached = [lengths[s] for s in zone if s in lengths]
        if reached:
            walk[i] = sum(reached) / len(reached)

    door = core_pick(entrances, vexcel.get("ambulance_parking") or [], vexcel.get("hydrants") or [],
                     walk, zone_desc)
    db.set_building(building_id, ems_door=door)
    decision(AGENT, f"EMS door: {door['desc']}.", door["reason"], building_id,
             options=[e.get("desc") for e in entrances], method=door["method"])
    staging = (door.get("staging") or {}).get("desc") or "--"
    hydrant = (door.get("hydrant") or {}).get("desc") or "--"
    result(AGENT, "pick_ems_door", f"Saved the EMS door; staging at {staging}, nearest hydrant {hydrant}.",
           building_id, {"method": door["method"], "entrance_index": door["entrance_index"]})
    return {"ems_door": door}
