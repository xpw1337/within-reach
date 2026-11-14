"""Records subagent tools: get_costar_profile, estimate_occupancy, and the scan order (spec 9.2, 9.5).

Writes ``buildings.occupancy_est`` and ``buildings.priority_score``. The occupancy factors are
unverified (census/core/occupancy.py), so every people count is labeled an estimate.
"""

from __future__ import annotations

from census.core.occupancy import TABLE_STATUS
from census.core.occupancy import estimate_occupancy as core_estimate
from census.core.scoring import scan_priority
from census.tools import db
from census.tools.events import decision, result, tool_call, warning

AGENT = "records"

PROFILE_FIELDS = ("id", "costar_property_id", "name", "address", "city", "property_type", "floors",
                  "size_sqft", "tenants_count", "occupancy_est", "census_status", "priority_score")
FALLBACK_PREFIX = "FALLBACK-"


def is_fixture(building: dict) -> bool:
    """Fallback/demo buildings never count toward a headline number (demo/DESIGN.md)."""
    return str(building.get("costar_property_id") or "").startswith(FALLBACK_PREFIX)


def get_costar_profile(building_id: str) -> dict:
    """CoStar facts for one building: type, size, floors, tenants, city."""
    tool_call(AGENT, "get_costar_profile", {"building_id": building_id}, building_id)
    row = db.load_building(building_id)
    if row is None:
        warning(AGENT, "building_missing", f"Building {building_id} does not exist.", None,
                {"building_id": building_id})
        return {"error": "building not found", "building_id": building_id}
    profile = {k: row.get(k) for k in PROFILE_FIELDS}
    size = f"{row['size_sqft']} sq ft" if row.get("size_sqft") else "unknown size"
    result(AGENT, "get_costar_profile",
           f"{row.get('name') or 'Building'}: {row.get('property_type') or 'unknown type'}, {size}, "
           f"{row.get('floors') if row.get('floors') is not None else '--'} floors.",
           building_id, profile)
    return profile


def _estimate(row: dict) -> dict:
    est = core_estimate(row.get("property_type"), row.get("size_sqft"))
    people = est.people if est else None
    return {"occupancy_est": people, "priority_score": scan_priority(people),
            "basis": est.basis if est else None}


def estimate_occupancy(building_id: str) -> dict:
    """Estimated occupant load from gross area and type (IBC 2021 Table 1004.5, unverified)."""
    tool_call(AGENT, "estimate_occupancy", {"building_id": building_id}, building_id)
    row = db.load_building(building_id)
    if row is None:
        warning(AGENT, "building_missing", f"Building {building_id} does not exist.", None,
                {"building_id": building_id})
        return {"error": "building not found", "building_id": building_id}
    est = _estimate(row)
    db.set_building(building_id, occupancy_est=est["occupancy_est"], priority_score=est["priority_score"])
    if est["occupancy_est"] is None:
        result(AGENT, "estimate_occupancy",
               f"No occupancy estimate for a {row.get('property_type') or 'building of unknown type'} "
               f"without a citable factor; people at risk will show as unknown.", building_id,
               {"occupancy_est": None, "status": TABLE_STATUS})
    else:
        result(AGENT, "estimate_occupancy",
               f"Estimated occupant load about {est['occupancy_est']} people (code-table estimate, "
               f"{TABLE_STATUS}).", building_id,
               {"occupancy_est": est["occupancy_est"], "basis": est["basis"], "status": TABLE_STATUS})
    return {"building_id": building_id, "occupancy_est": est["occupancy_est"], "basis": est["basis"]}


def prioritize(building_ids: list[str]) -> list[str]:
    """Estimate occupancy for every candidate, store the priority, and return the scan order
    (most people first; unknown last; then by id). Emits the scan-order decision."""
    tool_call(AGENT, "prioritize", {"buildings": len(building_ids)})
    rows = db.fetch_by_ids("buildings", building_ids)
    scored = [(row, _estimate(row)) for row in rows]
    db.upsert("buildings", [{"id": row["id"], "occupancy_est": est["occupancy_est"],
                             "priority_score": est["priority_score"]} for row, est in scored],
              on_conflict="id")
    scored.sort(key=lambda item: (item[1]["priority_score"] is None, -(item[1]["priority_score"] or 0),
                                  item[0]["id"]))
    order = [row["id"] for row, _ in scored]
    known = sum(1 for _, est in scored if est["occupancy_est"] is not None)
    head = [
        {"building_id": row["id"], "name": row.get("name"), "property_type": row.get("property_type"),
         "occupancy_est": est["occupancy_est"]}
        for row, est in scored[:5]
    ]
    if scored:
        first = scored[0][0]
        decision(AGENT,
                 f"Scan order set for {len(order)} buildings: {first.get('name') or first['id']} first, "
                 f"largest estimated occupant load first ({known} of {len(order)} have an estimate).",
                 "more people inside means more people exposed to a gap", None, options=head)
    return order
