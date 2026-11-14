"""Rank buildings across each city on their measured gaps (spec section 9.5).

Fallback/demo buildings are ranked in their own group so they never displace a real rank.
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
    for row in scores:
        b = buildings.get(row["building_id"], {})
        group = "fixture" if is_fixture(b) else (b.get("city") or "unknown city")
        groups.setdefault(group, {})[row["building_id"]] = from_row(BuildingScore, row)
    for group in groups.values():
        ranks = rank_buildings(group)
        db.upsert("building_scores", [{"building_id": bid, "rank": r} for bid, r in ranks.items()],
                  on_conflict="building_id")
    counts = {g: len(v) for g, v in groups.items()}
    real = sum(n for g, n in counts.items() if g != "fixture")
    result(AGENT, "rerank", f"Re-ranked {real} scanned buildings on their measured gaps.", None,
           {"groups": counts})
    return {"groups": counts}
