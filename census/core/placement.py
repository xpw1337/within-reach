"""Greedy placement of one new AED or extinguisher (spec section 9.6).

For each candidate sweep, add it as a source and recompute the walking-time map; keep the
candidate that minimizes the worst case, ties broken by the smallest red fraction, then by sweep
id so the answer is deterministic. A sweep that cannot reach any source makes the worst case
infinite, so in a disconnected scan the search first covers the uncovered part, then shrinks the
red area. Red fractions use the same rule as ``census.core.scoring`` (over the limit, or
unreachable). Pure: thresholds and walk speed are arguments.

Cost: one single-source Dijkstra per candidate, merged with the existing map. Fine for hundreds
of sweeps. Above ``max_candidates`` the candidates are subsampled evenly and the result says so.
"""

from __future__ import annotations

import math

import networkx as nx

from census.core.graph import WEIGHT, walking_time_map
from census.core.scoring import type_stats
from shared.types import Placement, TimeMap

DEFAULT_MAX_CANDIDATES = 400  # performance bound, not a safety parameter

# Room types where a new AED or extinguisher should not be proposed (private, locked or outside).
# Matched as lowercase substrings of twin_nodes.room_type when the dataset provides it.
UNSUITABLE_ROOM_WORDS: tuple[str, ...] = (
    "bathroom", "restroom", "toilet", "shower", "locker", "closet", "utility", "mechanical",
    "electrical", "server", "storage", "bedroom", "laundry", "outdoor", "exterior", "balcony",
    "patio", "terrace", "roof",
)


def candidate_sweeps(graph: nx.Graph) -> list[str]:
    """Sweeps where a device could be mounted: not stairs, not elevators, not an unsuitable room."""
    out = []
    for sweep, data in graph.nodes(data=True):
        if data.get("is_stairs") or data.get("is_elevator"):
            continue
        room = (data.get("room_type") or "").lower()
        if room and any(word in room for word in UNSUITABLE_ROOM_WORDS):
            continue
        out.append(sweep)
    return sorted(out)


def _key(times: TimeMap, total: int, limit_s: float) -> tuple[float, float]:
    stats = type_stats(times, total, limit_s)
    worst = math.inf if stats.unreachable or stats.worst_s is None else stats.worst_s
    return (worst, stats.red_frac if stats.red_frac is not None else 0.0)


def _subsample(items: list[str], limit: int) -> list[str]:
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def place_one(
    graph: nx.Graph,
    existing: list[str],
    candidates: list[str],
    limit_s: float,
    walk_speed_mps: float,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> Placement:
    """Best single new device location among ``candidates`` (sweep ids).

    ``existing`` are the sweeps of the assets of this type already visible in the scan.
    ``limit_s`` is the red limit in one-way seconds. Returns before/after stats; ``sweep_id`` is
    None when no candidate improves the worst case or the red fraction, and then
    ``proposed_times`` equals the current map.
    """
    total = graph.number_of_nodes()
    before = walking_time_map(graph, existing, walk_speed_mps)
    before_stats = type_stats(before, total, limit_s)
    before_key = _key(before, total, limit_s)

    existing_set = set(existing)
    pool = sorted({c for c in candidates if c in graph and c not in existing_set})
    subsampled = len(pool) > max_candidates
    if subsampled:
        pool = _subsample(pool, max_candidates)

    best_sweep: str | None = None
    best_key = before_key
    best_times: TimeMap = before
    for cand in pool:
        lengths = nx.single_source_dijkstra_path_length(graph, cand, weight=WEIGHT)
        merged = dict(before)
        for sweep, meters in lengths.items():
            t = float(meters) / walk_speed_mps
            if t < merged.get(sweep, math.inf):
                merged[sweep] = t
        key = _key(merged, total, limit_s)
        if key < best_key:
            best_sweep, best_key, best_times = cand, key, merged

    after_stats = type_stats(best_times, total, limit_s)
    return Placement(
        sweep_id=best_sweep,
        before_worst_s=before_stats.worst_s,
        after_worst_s=after_stats.worst_s,
        before_red_frac=before_stats.red_frac if before_stats.red_frac is not None else 0.0,
        after_red_frac=after_stats.red_frac if after_stats.red_frac is not None else 0.0,
        proposed_times=dict(best_times),
        candidates_considered=len(pool),
        subsampled=subsampled,
    )
