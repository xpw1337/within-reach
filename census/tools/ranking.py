"""Rank buildings across each city on their measured gaps (spec section 9.5).

Fallback fixtures and demo venues (data.adapter.FIXTURE_PREFIXES) are each ranked alone, so they
never displace a real rank or each other.
"""

from __future__ import annotations

from census.core.scoring import rank_buildings
from census.tools import db
from census.tools.events import result, tool_call
from census.tools.records import is_fixture
from shared.types import BuildingScore, from_row

AGENT = "planner"


def rerank() -> dict:
    """Recompute building_scores.rank within each city. Returns counts per group."""
    tool_call(AGENT, "rerank", {})
    scores = db.fetch_all("building_scores")
    if not scores:
        result(AGENT, "rerank", "No building scores to rank yet.", None, {"groups": {}})
        return {"groups": {}}
    buildings = {b["id"]: b for b in db.fetch_by_ids(
        "buildings", [s["building_id"] for s in scores], columns="id,city,costar_property_id")}
    groups: dict[str, dict[str, BuildingScore]] = {}
    counts: dict[str, int] = {}
    for row in scores:
        b = buildings.get(row["building_id"], {})
        if is_fixture(b):
            # Each fixture or demo venue is ranked alone (always 1), so adding one never changes
            # another's rank or any real rank.
            group, key = "fixture", f"fixture:{row['building_id']}"
        else:
            group = key = b.get("city") or "unknown city"
        groups.setdefault(key, {})[row["building_id"]] = from_row(BuildingScore, row)
        counts[group] = counts.get(group, 0) + 1
    stored = {row["building_id"]: row.get("rank") for row in scores}
    for group in groups.values():
        ranks = rank_buildings(group)
        changed = [{"building_id": bid, "rank": r} for bid, r in ranks.items() if stored.get(bid) != r]
        if changed:  # only rows whose rank moved are written
            db.upsert("building_scores", changed, on_conflict="building_id")
    real = sum(n for g, n in counts.items() if g != "fixture")
    result(AGENT, "rerank", f"Re-ranked {real} scanned buildings on their measured gaps.", None,
           {"groups": counts})
    return {"groups": counts}
