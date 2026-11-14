"""python -m census.cli run|rerun|rank|report

``report`` prints the numbers for the pitch, and the headline number comes from here and nowhere
else (census/DESIGN.md). It counts real buildings only: fallback/demo fixtures (costar_property_id
starting with FALLBACK-) are filtered out, and anything without data prints as ``--``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from census import run as census_run
from census.tools import db, ranking
from census.tools.records import is_fixture

DASH = "--"


def _real_buildings(ids: set[str] | None = None) -> dict[str, dict]:
    columns = "id,costar_property_id,census_status"
    rows = db.fetch_by_ids("buildings", sorted(ids), columns=columns) if ids is not None \
        else db.fetch_all("buildings", columns=columns)
    return {b["id"]: b for b in rows if not is_fixture(b)}


def report(run_id: str | None = None) -> dict[str, Any]:
    """Real counts. With ``run_id``: buildings that run mapped (from its console events) and its cost."""
    run = None
    if run_id:
        run = db.fetch_one("runs", filters=[("eq", "id", run_id)])
        if run is None:
            raise ValueError(f"run {run_id} not found")
        touched = {e["building_id"] for e in db.fetch_all(
            "agent_events", columns="building_id,agent,payload",
            filters=[("eq", "run_id", run_id), ("eq", "kind", "result"), ("eq", "agent", "mapper")])
            if e.get("building_id") and (e.get("payload") or {}).get("tool") == "flag_routes"}
        buildings = _real_buildings(touched)
        cost = run.get("est_cost_usd")
    else:
        buildings = _real_buildings()
        runs = db.fetch_all("runs", columns="est_cost_usd")
        cost = sum(float(r.get("est_cost_usd") or 0) for r in runs) if runs else None

    ids = sorted(buildings)
    scores = db.fetch_by_ids("building_scores", ids, column="building_id") if ids else []
    panos = db.fetch_by_ids("panos", ids, column="building_id", columns="building_id",
                            filters=[("eq", "tiles_done", True)]) if ids else []
    detections = db.fetch_by_ids("detections", ids, column="building_id",
                                 columns="building_id,human_label") if ids else []
    scored = len(scores)
    aed_red = sum(1 for s in scores if (s.get("aed_red_frac") or 0) > 0)
    no_aed = sum(1 for s in scores if s.get("aed_worst_s") is None)
    correct = sum(1 for d in detections if d.get("human_label") == "correct")
    incorrect = sum(1 for d in detections if d.get("human_label") == "incorrect")
    return {
        "run_id": run_id,
        "run_status": run.get("status") if run else None,
        "buildings_scanned": scored,
        "panoramas": len(panos),
        "cost_usd": cost,
        "aed_red_zone_buildings": aed_red,
        "aed_red_zone_fraction": (aed_red / scored) if scored else None,
        "no_aed_visible_buildings": no_aed,
        "handcheck_correct": correct,
        "handcheck_labeled": correct + incorrect,
        "handcheck_precision": (correct / (correct + incorrect)) if (correct + incorrect) else None,
    }


def format_report(r: dict[str, Any]) -> str:
    def num(v: Any) -> str:
        return DASH if v is None else str(v)

    frac = r["aed_red_zone_fraction"]
    cost = DASH if r["cost_usd"] is None else "${:.2f}".format(r["cost_usd"])
    hand = DASH if not r["handcheck_labeled"] else "{}/{} correct".format(r["handcheck_correct"],
                                                                          r["handcheck_labeled"])
    red = DASH if frac is None else "{} ({}%)".format(r["aed_red_zone_buildings"], round(frac * 100))
    scope = " for run " + r["run_id"] if r["run_id"] else " (all runs)"
    status = " [" + r["run_status"] + "]" if r["run_status"] else ""
    no_aed = r["no_aed_visible_buildings"] if r["buildings_scanned"] else None
    lines = [
        "Census report" + scope + status + ". Real buildings only; demo fixtures excluded.",
        "  Buildings scanned:            " + num(r["buildings_scanned"] or None),
        "  Panoramas processed:          " + num(r["panoramas"] or None),
        "  Cost:                         " + cost,
        "  With an AED red zone:         " + red,
        "  No AED visible in the scan:   " + num(no_aed),
        "  Hand-check precision:         " + hand,
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m census.cli", description="Within Reach census")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="start (or resume) a census run in the foreground")
    p_run.add_argument("--target", type=int, default=20)
    p_run.add_argument("--city", choices=["Houston", "Los Angeles"])
    p_run.add_argument("--types", help="comma-separated property types, for example gym,office")
    p_run.add_argument("--budget", type=float, help="dollars; defaults to CENSUS_BUDGET_USD")
    p_run.add_argument("--mode", choices=["agent", "pipeline"], default="agent")
    p_run.add_argument("--batch-size", type=int, default=census_run.DEFAULT_BATCH_SIZE)
    p_run.add_argument("--resume", metavar="RUN_ID")

    p_rerun = sub.add_parser("rerun", help="rerun one building (the stage demo)")
    p_rerun.add_argument("--building", required=True)
    p_rerun.add_argument("--mode", choices=["agent", "pipeline"], default="agent")

    sub.add_parser("rank", help="re-rank buildings on their measured gaps")

    p_report = sub.add_parser("report", help="real numbers for the pitch")
    p_report.add_argument("--run", metavar="RUN_ID")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        if args.resume:
            run_id = census_run.resume_run(args.resume, background=False)
        else:
            from census.tools.context import ctx

            budget = args.budget if args.budget is not None else ctx().budget_usd
            if budget is None:
                parser.error("set --budget or CENSUS_BUDGET_USD")
            types = [t.strip() for t in args.types.split(",")] if args.types else None
            run_id = census_run.start_run(args.target, args.city, types, budget, mode=args.mode,
                                          batch_size=args.batch_size, background=False)
        print(format_report(report(run_id)))
    elif args.cmd == "rerun":
        run_id = census_run.rerun_building(args.building, mode=args.mode, background=False)
        print(f"Rerun finished: run {run_id}")
    elif args.cmd == "rank":
        print(ranking.rerank())
    elif args.cmd == "report":
        print(format_report(report(args.run)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
