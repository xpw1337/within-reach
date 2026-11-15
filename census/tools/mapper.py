"""Mapper subagent tools: build_graph, walking_time_map, flag_routes (spec sections 9.2, 9.4).

Reads ``twin_nodes`` and ``assets``; writes ``coverage(scenario='current')``,
``building_scores`` and ``buildings.census_status='mapped'``; emits console events. Each tool
returns a short JSON-serializable summary, never bulk data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import networkx as nx

from census.core import graph as core_graph
from census.core.scoring import score_building, type_stats
from census.tools import db
from census.tools.context import ctx
from census.tools.events import GAP_NAMES, decision, pct, result, time_phrase, tool_call, warning
from shared.types import GAP_TYPES, BuildingScore, CoverageByType, Flags, TimeMap

AGENT = "mapper"

# Which asset types feed each walking-time map. Exit maps count exit doors and exit signs, since
# the Scanner finds signs, not doors (docs/CONTRACTS.md section 1). Directional signs count too,
# so exit distances are an approximation; the wording is "exit sign visible in the scan".
SOURCE_ASSET_TYPES: dict[str, tuple[str, ...]] = {
    "aed": ("aed",),
    "extinguisher": ("extinguisher",),
    "exit": ("exit", "exit_sign"),
}
# "No ... visible in the scan" wording per gap type.
NOT_VISIBLE = {"aed": "No AED", "extinguisher": "No extinguisher", "exit": "No exit sign"}


def not_connected_phrase(n: int) -> str:
    """'3 positions not connected in the scan were left out.' or '' (CONTRACTS section 1)."""
    if not n:
        return ""
    return f"{n} position{'s' if n != 1 else ''} not connected in the scan {'were' if n != 1 else 'was'} left out."
BLOCKED_EXIT_FLAG = "blocked_exit"
# A disclosed demo prop placed by the team (demo/PLANTED_AED.md). It feeds this building's own
# walking-time maps and camera routes, but documents never present it as found in the scan, and
# the building it sits in is a demo venue excluded from every census number by its id prefix.
SIMULATED_FLAG = "simulated"


def is_simulated(asset: dict) -> bool:
    return SIMULATED_FLAG in (asset.get("flags") or [])


class MapperError(RuntimeError):
    pass


@dataclass
class LoadedBuilding:
    building: dict
    graph: nx.Graph
    assets: list[dict]  # current (non-proposed) assets

    @property
    def id(self) -> str:
        return self.building["id"]


def load(building_id: str) -> LoadedBuilding:
    """Building row, sweep graph and current assets. Raises MapperError (after a console
    warning) when the building is missing or has no twin nodes."""
    building = db.load_building(building_id)
    if building is None:
        warning(AGENT, "building_missing", f"Building {building_id} does not exist; skipping it.", None,
                {"building_id": building_id})
        raise MapperError(f"building {building_id} not found")
    nodes = db.load_twin_nodes(building_id)
    if not nodes:
        warning(AGENT, "no_twin_nodes",
                f"{_name(building)} has no scan positions loaded, so it cannot be mapped.", building_id)
        raise MapperError(f"building {building_id} has no twin nodes")
    assets = db.load_assets(building_id)
    return LoadedBuilding(building=building, graph=core_graph.build_graph(nodes), assets=assets)


def _name(building: dict) -> str:
    return building.get("name") or building.get("address") or "This building"


def source_sweeps(loaded: LoadedBuilding, gap: str) -> tuple[list[str], int]:
    """Sweeps holding a current asset of this gap type, and how many such assets are off the twin."""
    sweeps, off_twin = [], 0
    for asset in loaded.assets:
        if asset.get("type") not in SOURCE_ASSET_TYPES[gap]:
            continue
        sweep = asset.get("sweep_id")
        if sweep in loaded.graph:
            sweeps.append(sweep)
        else:
            off_twin += 1
    return sorted(set(sweeps)), off_twin


def time_maps(loaded: LoadedBuilding) -> CoverageByType:
    speed = ctx().walk_speed_mps
    return {g: core_graph.walking_time_map(loaded.graph, source_sweeps(loaded, g)[0], speed)
            for g in GAP_TYPES}


def coverage_rows(building_id: str, sweeps: list[str], gap: str, times: TimeMap, scenario: str) -> list[dict]:
    return [{"building_id": building_id, "sweep_id": s, "asset_type": gap, "scenario": scenario,
             "time_s": times.get(s)} for s in sweeps]


def write_coverage(building_id: str, graph: nx.Graph, gap: str, times: TimeMap, scenario: str) -> int:
    """One row per sweep; NULL where no asset is reachable (CONTRACTS section 1)."""
    rows = coverage_rows(building_id, sorted(graph.nodes), gap, times, scenario)
    db.upsert("coverage", rows, on_conflict="building_id,sweep_id,asset_type,scenario")
    return len(rows)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def build_graph(building_id: str) -> dict:
    """Build the walking graph from the building's scan positions and report its shape."""
    tool_call(AGENT, "build_graph", {"building_id": building_id}, building_id)
    loaded = load(building_id)
    summary = core_graph.graph_summary(loaded.graph)
    parts = summary["components"]
    floors = len(summary["floors"])
    result(AGENT, "build_graph",
           f"Built the walking graph: {summary['sweeps']} scan positions on {floors} "
           f"floor{'s' if floors != 1 else ''}, in {parts} connected part{'s' if parts != 1 else ''}.",
           building_id, summary)
    if parts > 1:
        warning(AGENT, "disconnected_scan",
                f"The scan is split into {parts} parts; positions that cannot reach equipment count as red.",
                building_id, {"components": parts})
    return summary


def _walking_time_map(loaded: LoadedBuilding, asset_type: str) -> dict:
    building_id = loaded.id
    sources, off_twin = source_sweeps(loaded, asset_type)
    times = core_graph.walking_time_map(loaded.graph, sources, ctx().walk_speed_mps)
    rows = write_coverage(building_id, loaded.graph, asset_type, times, "current")
    limit = ctx().limit_seconds(asset_type)
    stats = type_stats(times, loaded.graph.number_of_nodes(), limit)
    name = GAP_NAMES[asset_type]
    if not sources:
        message = (f"{NOT_VISIBLE[asset_type]} visible in the scan, so all {stats.red_sweeps} scanned "
                   f"positions count as red for {name} access.")
    else:
        message = (f"{name[0].upper() + name[1:]} worst case {time_phrase(asset_type, stats.worst_s)}; "
                   f"{pct(stats.red_frac)} of connected scanned positions are red.")
        if stats.unreachable:
            message += " " + not_connected_phrase(stats.unreachable)
        demo = sum(1 for a in loaded.assets
                   if is_simulated(a) and a.get("type") in SOURCE_ASSET_TYPES[asset_type])
        if demo:
            message += (f" This map uses {demo} demo {name}{'s' if demo != 1 else ''} placed by the team, "
                        "not found in the scan.")
    metrics = {"asset_type": asset_type, "sources": len(sources), "rows": rows,
               "limit_one_way_s": limit, **stats.as_dict()}
    result(AGENT, "walking_time_map", message, building_id, metrics)
    if off_twin:
        warning(AGENT, "asset_off_twin",
                f"{off_twin} {name} asset{'s are' if off_twin != 1 else ' is'} not pinned to a scan "
                f"position and {'were' if off_twin != 1 else 'was'} left out of the map.", building_id,
                {"asset_type": asset_type, "count": off_twin})
    return {"asset_type": asset_type, "sources": len(sources), "worst_s_one_way": stats.worst_s,
            "red_frac": stats.red_frac, "unreachable": stats.unreachable}


def walking_time_map(building_id: str, asset_type: str) -> dict:
    """Walking-time map for one equipment type (aed, extinguisher or exit); writes coverage."""
    if asset_type not in GAP_TYPES:
        raise ValueError(f"asset_type must be one of {GAP_TYPES}, got {asset_type!r}")
    tool_call(AGENT, "walking_time_map", {"building_id": building_id, "asset_type": asset_type}, building_id)
    return _walking_time_map(load(building_id), asset_type)


def compute_flags(loaded: LoadedBuilding) -> Flags:
    exits, _ = source_sweeps(loaded, "exit")
    blocked = sum(1 for a in loaded.assets if BLOCKED_EXIT_FLAG in (a.get("flags") or []))
    return Flags(
        stairs_only_sweeps=core_graph.stairs_only_sweeps(loaded.graph, exits),
        blocked_exits=blocked,
        no_aed_visible=not source_sweeps(loaded, "aed")[0],
        no_extinguisher_visible=not source_sweeps(loaded, "extinguisher")[0],
        no_exit_visible=not exits,
        graph_components=core_graph.component_count(loaded.graph),
        sweeps_total=loaded.graph.number_of_nodes(),
    )


def score(loaded: LoadedBuilding, flags: Flags | None = None) -> tuple[BuildingScore, Flags]:
    flags = flags or compute_flags(loaded)
    limits = {g: ctx().limit_seconds(g) for g in GAP_TYPES}
    s = score_building(time_maps(loaded), loaded.building.get("occupancy_est"), flags, limits_s=limits)
    return s, flags


def write_score(building_id: str, s: BuildingScore) -> None:
    row = {k: v for k, v in asdict(s).items() if k != "rank"}
    row.update(building_id=building_id, updated_at=db.now_iso())
    db.upsert("building_scores", [row], on_conflict="building_id")


def _flag_routes(loaded: LoadedBuilding) -> dict:
    building_id = loaded.id
    s, flags = score(loaded)
    write_score(building_id, s)
    db.set_building(building_id, census_status="mapped")

    if flags.stairs_only:
        n = len(flags.stairs_only_sweeps)
        warning(AGENT, "stairs_only",
                f"{n} upper-floor scan position{'s reach' if n != 1 else ' reaches'} an exit only by stairs.",
                building_id, {"sweeps": flags.stairs_only_sweeps[:50], "count": n})
    if flags.blocked_exits:
        warning(AGENT, "blocked_exit",
                f"{flags.blocked_exits} exit{'s look' if flags.blocked_exits != 1 else ' looks'} blocked in the scan.",
                building_id, {"count": flags.blocked_exits})
    if flags.no_aed_visible:
        warning(AGENT, "no_aed_visible", "No AED visible in the scan.", building_id)

    fracs = {"aed": s.aed_red_frac, "extinguisher": s.ext_red_frac, "exit": s.exit_red_frac}
    if s.worst_gap == "none":
        decision(AGENT, "No red zones: every scanned position is within the target for all three types.",
                 "all red fractions are 0", building_id, options=fracs)
    else:
        people = (f", about {s.people_at_risk} people at risk (estimate)" if s.people_at_risk is not None
                  else "; people at risk unknown (no occupancy estimate)")
        decision(AGENT,
                 f"Worst gap is {GAP_NAMES[s.worst_gap]} access: {pct(fracs[s.worst_gap])} of scanned "
                 f"positions are red{people}.",
                 "largest red fraction; ties go to the AED", building_id, options=fracs)
    summary = {
        "worst_gap": s.worst_gap, "gap_score": s.gap_score, "people_at_risk": s.people_at_risk,
        "red_frac": fracs, "stairs_only_sweeps": len(flags.stairs_only_sweeps),
        "blocked_exits": flags.blocked_exits, "components": flags.graph_components,
        "no_visible": {"aed": flags.no_aed_visible, "extinguisher": flags.no_extinguisher_visible,
                       "exit": flags.no_exit_visible},
    }
    result(AGENT, "flag_routes", f"Saved the life-safety score for {_name(loaded.building)}.",
           building_id, summary)
    return summary


def flag_routes(building_id: str) -> dict:
    """Stairs-only routes, blocked exits and missing equipment; writes the building score."""
    tool_call(AGENT, "flag_routes", {"building_id": building_id}, building_id)
    return _flag_routes(load(building_id))


def map_building(building_id: str) -> dict:
    """All three walking-time maps plus flags and score in one pass (used by the run loop)."""
    tool_call(AGENT, "map_building", {"building_id": building_id}, building_id)
    loaded = load(building_id)
    maps = {g: _walking_time_map(loaded, g) for g in GAP_TYPES}
    summary = _flag_routes(loaded)
    return {"maps": maps, **summary}
