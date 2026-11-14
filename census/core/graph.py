"""Sweep graph, walking-time maps, shortest routes and stairs-only detection (spec section 9.4).

Pure functions. Thresholds and walk speed come in as arguments; nothing here reads settings.

Graph model:
- One node per sweep (scan position). Node attributes copy the ``TwinNode`` fields.
- One undirected edge per neighbor pair. ``weight`` is the 3D Euclidean distance in meters.
  Elevator and stair edges therefore cost their 3D length too: a coarse stand-in for real
  vertical travel time, which the scan does not measure.
- Neighbor ids that are not sweeps of this building are skipped and counted in
  ``graph.graph["dangling_neighbors"]``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable

import networkx as nx

from shared.types import Route, TimeMap, TwinNode

WEIGHT = "weight"


def build_graph(nodes: list[TwinNode]) -> nx.Graph:
    """Build the walking graph from a building's sweeps."""
    graph = nx.Graph()
    by_id: dict[str, TwinNode] = {}
    for node in nodes:
        by_id[node.sweep_id] = node
        graph.add_node(
            node.sweep_id,
            floor=node.floor,
            x=node.x,
            y=node.y,
            z=node.z,
            room_type=node.room_type,
            label=node.label,
            is_elevator=bool(node.is_elevator),
            is_stairs=bool(node.is_stairs),
        )
    dangling = 0
    for node in nodes:
        for other_id in node.neighbors:
            if other_id == node.sweep_id:
                continue
            other = by_id.get(other_id)
            if other is None:
                dangling += 1
                continue
            if graph.has_edge(node.sweep_id, other_id):
                continue
            graph.add_edge(node.sweep_id, other_id, **{WEIGHT: _distance(node, other)})
    graph.graph["dangling_neighbors"] = dangling
    return graph


def _distance(a: TwinNode, b: TwinNode) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))


def component_count(graph: nx.Graph) -> int:
    """Number of connected components. Disconnected scans are common; this is reported, not fatal."""
    if graph.number_of_nodes() == 0:
        return 0
    return nx.number_connected_components(graph)


def walking_time_map(graph: nx.Graph, sources: list[str], walk_speed_mps: float) -> TimeMap:
    """One-way walking seconds from every reachable sweep to the nearest source sweep.

    Multi-source Dijkstra over the 3D edge lengths, divided by ``walk_speed_mps``. Sweeps that
    cannot reach any source are omitted (stored as NULL). Sources that are not in the graph are
    ignored; with no usable source the map is empty.
    """
    if walk_speed_mps <= 0:
        raise ValueError(f"walk_speed_mps must be positive, got {walk_speed_mps}")
    valid = {s for s in sources if s in graph}
    if not valid:
        return {}
    lengths = nx.multi_source_dijkstra_path_length(graph, valid, weight=WEIGHT)
    return {sweep: float(meters) / walk_speed_mps for sweep, meters in lengths.items()}


def shortest_route(graph: nx.Graph, src: str, dst_sweeps: list[str]) -> Route | None:
    """Shortest walking route from ``src`` to the nearest of ``dst_sweeps``.

    Returns None when ``src`` is not in the graph or no destination is reachable from it.
    """
    targets = {d for d in dst_sweeps if d in graph}
    if src not in graph or not targets:
        return None
    if src in targets:
        return Route(path=[src], distance_m=0.0)
    # Undirected graph: search outward from all destinations and stop at the source, then
    # reverse the path so it starts at the source.
    try:
        distance, path = nx.multi_source_dijkstra(graph, targets, target=src, weight=WEIGHT)
    except nx.NetworkXNoPath:
        return None
    return Route(path=list(reversed(path)), distance_m=float(distance))


def ground_floor(graph: nx.Graph, exit_sweeps: Iterable[str]) -> int | None:
    """The floor treated as ground level: the lowest floor holding an exit, else the lowest floor."""
    exit_floors = [graph.nodes[s]["floor"] for s in exit_sweeps if s in graph]
    if exit_floors:
        return min(exit_floors)
    floors = [data["floor"] for _, data in graph.nodes(data=True) if data.get("floor") is not None]
    return min(floors) if floors else None


def stairs_only_sweeps(
    graph: nx.Graph, exit_sweeps: list[str], ground: int | None = None
) -> list[str]:
    """Sweeps off the ground floor whose every route to an exit needs stairs (spec section 9.4).

    A sweep is flagged when it can reach an exit on the full graph but cannot once stair nodes are
    removed (so no elevator route exists). Stair sweeps themselves are not flagged. Exit sweeps are
    kept even if tagged as stairs, so an exit door at the foot of a stairwell still counts once
    reached by elevator. ``ground`` defaults to ``ground_floor(graph, exit_sweeps)``.
    Returns sweep ids sorted for a stable result.
    """
    exits = {s for s in exit_sweeps if s in graph}
    if not exits:
        return []
    if ground is None:
        ground = ground_floor(graph, exits)

    reach_all = _reachable_from(graph, exits)
    no_stairs = graph.subgraph(
        n for n, data in graph.nodes(data=True) if not data.get("is_stairs") or n in exits
    )
    reach_no_stairs = _reachable_from(no_stairs, exits)

    flagged = []
    for sweep in reach_all - reach_no_stairs:
        data = graph.nodes[sweep]
        if data.get("is_stairs"):
            continue
        if data.get("floor") == ground:
            continue
        flagged.append(sweep)
    return sorted(flagged)


def _reachable_from(graph: nx.Graph, sources: set[str]) -> set[str]:
    reached: set[str] = set()
    for source in sources:
        if source in graph and source not in reached:
            reached |= nx.node_connected_component(graph, source)
    return reached


def graph_summary(graph: nx.Graph) -> dict:
    """Small JSON-friendly description for tool results and console events."""
    floors = sorted({d.get("floor") for _, d in graph.nodes(data=True) if d.get("floor") is not None})
    return {
        "sweeps": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "components": component_count(graph),
        "floors": floors,
        "stairs_sweeps": sum(1 for _, d in graph.nodes(data=True) if d.get("is_stairs")),
        "elevator_sweeps": sum(1 for _, d in graph.nodes(data=True) if d.get("is_elevator")),
        "dangling_neighbors": graph.graph.get("dangling_neighbors", 0),
    }
