"""Fixer subagent tools: place_one (propose_fix), draft_owner_letter, registry_list, emergency_card.

Writes ``fixes``, ``assets(source='proposed')``, ``coverage(scenario='proposed')`` and
``documents``; emits the placement and letter decisions to the console (spec sections 9.2, 9.6).
``propose_fix`` is the entry point the live API calls (docs/CONTRACTS.md section 4).
"""

from __future__ import annotations

import logging

from census.core import docs as core_docs
from census.core.graph import walking_time_map as core_time_map
from census.core.placement import candidate_sweeps
from census.core.placement import place_one as core_place_one
from census.tools import db
from census.tools.context import ctx
from census.tools.events import GAP_NAMES, decision, pct, result, time_phrase, tool_call, warning
from census.tools.mapper import (
    SOURCE_ASSET_TYPES,
    LoadedBuilding,
    load,
    not_connected_phrase,
    source_sweeps,
    time_maps,
    write_coverage,
)
from census.tools.records import occupancy_estimate
from shared.types import GAP_TYPES

log = logging.getLogger(__name__)

AGENT = "fixer"
FIXABLE = ("aed", "extinguisher")
DOC_KINDS = ("owner_letter", "emergency_card", "registry_list")


def _where(loaded: LoadedBuilding, sweep: str) -> str:
    data = loaded.graph.nodes[sweep]
    return data.get("label") or data.get("room_type") or f"scan position {sweep}"


def write_proposed_coverage(loaded: LoadedBuilding) -> None:
    """coverage(scenario='proposed') for every gap type: current assets plus proposed ones."""
    proposed = db.load_assets(loaded.id, sources=("proposed",))
    speed = ctx().walk_speed_mps
    for gap in GAP_TYPES:
        sweeps = set(source_sweeps(loaded, gap)[0])
        sweeps |= {a["sweep_id"] for a in proposed
                   if a.get("type") in SOURCE_ASSET_TYPES[gap] and a.get("sweep_id") in loaded.graph}
        write_coverage(loaded.id, loaded.graph, gap, core_time_map(loaded.graph, sorted(sweeps), speed),
                       "proposed")


def propose_fix(building_id: str, asset_type: str = "aed") -> str:
    """Greedy placement of one new AED or extinguisher. Returns the new ``fixes.id``.

    Replaces any earlier proposal of the same type for this building. When no placement improves
    the worst case or the red area, the fixes row has ``sweep_id = NULL`` and says why.
    """
    if asset_type not in FIXABLE:
        raise ValueError(f"asset_type must be one of {FIXABLE}, got {asset_type!r}")
    tool_call(AGENT, "place_one", {"building_id": building_id, "asset_type": asset_type}, building_id)
    loaded = load(building_id)
    existing, _ = source_sweeps(loaded, asset_type)
    limit = ctx().limit_seconds(asset_type)
    placement = core_place_one(loaded.graph, existing, candidate_sweeps(loaded.graph), limit,
                               ctx().walk_speed_mps)
    name = GAP_NAMES[asset_type]
    before = f"worst case {time_phrase(asset_type, placement.before_worst_s)}"
    after = time_phrase(asset_type, placement.after_worst_s)
    change = (f"{before} to {after}; red area {pct(placement.before_red_frac)} to "
              f"{pct(placement.after_red_frac)}")

    if placement.sweep_id:
        where = _where(loaded, placement.sweep_id)
        rationale = (f"One new {name} at {where} gives the lowest worst-case walk among "
                     f"{placement.candidates_considered} candidate positions: {change}.")
        if placement.subsampled:
            rationale += " Candidates were subsampled for speed."
        left_out = loaded.graph.number_of_nodes() - len(placement.proposed_times)
        if left_out:
            rationale += " " + not_connected_phrase(left_out)
    else:
        where = None
        rationale = (f"No single new {name} position improves the worst case or the red area "
                     f"({placement.candidates_considered} candidates checked).")

    db.delete("fixes", filters=[("eq", "building_id", building_id), ("eq", "asset_type", asset_type)])
    db.delete("assets", filters=[("eq", "building_id", building_id), ("eq", "type", asset_type),
                                 ("eq", "source", "proposed")])
    (fix,) = db.insert("fixes", [{
        "building_id": building_id, "asset_type": asset_type, "sweep_id": placement.sweep_id,
        "before_worst_s": placement.before_worst_s, "after_worst_s": placement.after_worst_s,
        "before_red_frac": placement.before_red_frac, "after_red_frac": placement.after_red_frac,
        "rationale": rationale,
    }])
    if placement.sweep_id:
        node = loaded.graph.nodes[placement.sweep_id]
        db.insert("assets", [{
            "building_id": building_id, "type": asset_type, "sweep_id": placement.sweep_id,
            "floor": node.get("floor"), "label": where, "x": node.get("x"), "y": node.get("y"),
            "z": node.get("z"), "source": "proposed", "detection_ids": [], "verified": False, "flags": [],
        }])
        decision(AGENT, f"Placing one new {name} at {where}: {change}.", rationale, building_id,
                 sweep_id=placement.sweep_id, fix_id=fix["id"])
    else:
        decision(AGENT, f"No new {name} placement helps here; keeping the current layout.", rationale,
                 building_id, fix_id=fix["id"])
    write_proposed_coverage(loaded)
    metrics = {"fix_id": fix["id"], "sweep_id": placement.sweep_id,
               "before_worst_s": placement.before_worst_s, "after_worst_s": placement.after_worst_s,
               "before_red_frac": placement.before_red_frac, "after_red_frac": placement.after_red_frac,
               "candidates": placement.candidates_considered, "subsampled": placement.subsampled}
    result(AGENT, "place_one", f"Saved the proposed {name} fix: {change}.", building_id, metrics)
    return fix["id"]


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def collect_facts(building_id: str) -> dict:
    loaded = load(building_id)
    score = db.fetch_one("building_scores", filters=[("eq", "building_id", building_id)])
    assets = {gap: [a for a in loaded.assets if a.get("type") in SOURCE_ASSET_TYPES[gap]]
              for gap in GAP_TYPES}
    fix = db.fetch_one("fixes", filters=[("eq", "building_id", building_id), ("eq", "asset_type", "aed")]) \
        or db.fetch_one("fixes", filters=[("eq", "building_id", building_id)])
    fix_where = None
    if fix and fix.get("sweep_id") in loaded.graph:
        fix_where = dict(loaded.graph.nodes[fix["sweep_id"]])
    total = loaded.graph.number_of_nodes()
    not_connected = {g: (total - len(t)) if t else 0 for g, t in time_maps(loaded).items()}
    return core_docs.build_facts(
        not_connected=not_connected,
        building=loaded.building, score=score, sweeps_scanned=total,
        assets=assets, fix=fix, fix_where=fix_where, ems_door=loaded.building.get("ems_door"),
        occupancy_basis=occupancy_estimate(loaded.building)["basis"], show_s=ctx().display_seconds,
    )


def _save_document(building_id: str, kind: str, content_md: str) -> str:
    db.delete("documents", filters=[("eq", "building_id", building_id), ("eq", "kind", kind)])
    (row,) = db.insert("documents", [{"building_id": building_id, "kind": kind, "content_md": content_md}])
    return row["id"]


def _llm_letter_body(facts: dict, building_id: str) -> tuple[str | None, list[str]]:
    """Up to two LLM drafts; returns the first that passes the checker, plus the problems seen."""
    complete = ctx().complete_json
    if complete is None:
        return None, ["no LLM configured"]
    from shared.llm import text_part

    problems: list[str] = []
    for _attempt in (1, 2):
        try:
            out = complete(tier="reasoning", system=core_docs.LETTER_SYSTEM,
                           user=[text_part(core_docs.letter_user_text(facts, problems or None))],
                           schema=core_docs.LETTER_SCHEMA, run_id=ctx().run_id, max_tokens=2048)
        except Exception as exc:  # noqa: BLE001 - any LLM failure falls back to the template
            log.warning("owner letter LLM call failed: %s", exc)
            return None, [f"LLM error: {type(exc).__name__}"]
        body = str(out.get("body_md") or "")
        problems = core_docs.check_letter_body(body, facts) or ([] if body.strip() else ["empty body"])
        if not problems:
            return body, []
    return None, problems


def draft_owner_letter(building_id: str) -> str:
    """Owner letter from measured facts only (LLM draft, number-checked, template fallback)."""
    tool_call(AGENT, "draft_owner_letter", {"building_id": building_id}, building_id)
    facts = collect_facts(building_id)
    body, problems = _llm_letter_body(facts, building_id)
    if body is None:
        body = core_docs.owner_letter_template(facts)
        method = "template"
        warning(AGENT, "letter_template",
                f"The owner letter uses the plain template ({problems[0] if problems else 'no draft'}).",
                building_id, {"problems": problems[:10]})
    else:
        method = "llm"
    doc_id = _save_document(building_id, "owner_letter", core_docs.wrap_letter(facts, body))
    decision(AGENT, "Drafted the owner letter from measured facts only; it is a draft and is not sent.",
             f"written by {'the model and number-checked' if method == 'llm' else 'the fixed template'}",
             building_id, document_id=doc_id, method=method)
    return doc_id


def emergency_card(building_id: str) -> str:
    tool_call(AGENT, "emergency_card", {"building_id": building_id}, building_id)
    doc_id = _save_document(building_id, "emergency_card", core_docs.emergency_card(collect_facts(building_id)))
    result(AGENT, "emergency_card", "Saved the one-page emergency card.", building_id, {"document_id": doc_id})
    return doc_id


def registry_list(building_id: str) -> str:
    tool_call(AGENT, "registry_list", {"building_id": building_id}, building_id)
    facts = collect_facts(building_id)
    doc_id = _save_document(building_id, "registry_list", core_docs.registry_list(facts))
    n = len(facts["aeds"])
    result(AGENT, "registry_list",
           f"Saved the AED registry list with {n} AED{'s' if n != 1 else ''} visible in the scan.",
           building_id, {"document_id": doc_id, "aeds": n})
    return doc_id


def write_documents(building_id: str) -> dict:
    """All three documents. Returns {kind: document_id}."""
    return {"owner_letter": draft_owner_letter(building_id), "emergency_card": emergency_card(building_id),
            "registry_list": registry_list(building_id)}
