"""Run lifecycle for the census (spec sections 9.2, 10; census/DESIGN.md "run.py").

Shape of a run: Records ranks the candidate pool (cheap, no vision), then buildings go in ranked
batches. In ``agent`` mode the Deep Agent planner works each batch (a fresh planner per batch keeps
its context small); in ``pipeline`` mode the same tools run in a fixed order with no planner LLM
(tests, and a fallback when the model is unavailable). After every building: progress goes to
``runs``; after every batch: re-rank. A building that fails gets ``census_status='error'`` and a
warning, and the run continues. A crashed run resumes from ``buildings.census_status``: finished
buildings ('fixed') are skipped.

The budget for a run is kept in ``runs.notes`` as JSON (the schema has no budget column), so a
resumed run keeps the same budget. The real guard is ``budget_remaining``: checked before each
building and inside the planner's ``scan_building_bulk``.
"""

from __future__ import annotations

import importlib
import json
import logging
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from census.tools import budget, db, fixer, mapper, outside, ranking, records, routes
from census.tools.budget import budget_remaining
from census.tools.context import ToolContext, ctx, use_context, with_changes
from census.tools.events import decision, result, warning

log = logging.getLogger(__name__)

AGENT = "planner"
DONE = "fixed"
DEFAULT_BATCH_SIZE = 5

_stops: dict[str, threading.Event] = {}
_threads: dict[str, threading.Thread] = {}

__all__ = ["budget_remaining", "process_building", "rerun_building", "resume_run", "start_run", "stop_run"]


@dataclass
class RunConfig:
    budget_usd: float | None = None
    city: str | None = None
    types: list[str] | None = None
    mode: str = "agent"  # agent | pipeline
    batch_size: int = DEFAULT_BATCH_SIZE
    building_ids: list[str] | None = None  # explicit list (rerun) instead of the candidate pool
    extra: dict[str, Any] = field(default_factory=dict)

    def notes(self) -> str:
        return json.dumps({"budget_usd": self.budget_usd, "city": self.city, "types": self.types,
                           "mode": self.mode, "batch_size": self.batch_size,
                           "building_ids": self.building_ids})

    @classmethod
    def from_notes(cls, notes: str | None) -> RunConfig:
        try:
            data = json.loads(notes or "{}")
        except json.JSONDecodeError:
            data = {}
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# One building, deterministic order (pipeline mode, and the finishing steps in agent mode)
# ---------------------------------------------------------------------------


def _load_bulk() -> Any:
    """Agent 1's census/tools/bulk.py, or None while it is not installed (tests pin this)."""
    try:
        return importlib.import_module("census.tools.bulk")
    except ImportError:
        return None


def _bulk_scan(building_id: str) -> None:
    bulk = _load_bulk()
    if bulk is None:
        return
    db.set_building(building_id, census_status="scanning")
    bulk.scan_building_bulk(building_id)


def _cameras_in(building_id: str) -> list[str]:
    return [c["id"] for c in db.fetch_all("cameras", columns="id", filters=[("eq", "building_id", building_id)])]


def finish_building(building_id: str) -> None:
    """Camera routes for any camera in the building, then mark it done."""
    for camera_id in _cameras_in(building_id):
        routes.precompute_camera_routes(camera_id)
    db.set_building(building_id, census_status=DONE)


def process_building(building_id: str) -> dict:
    """Every census step for one building, in the spec order, without a planner."""
    _bulk_scan(building_id)
    records.estimate_occupancy(building_id)
    summary = mapper.map_building(building_id)
    if outside.get_vexcel(building_id).get("entrances"):
        outside.pick_ems_door(building_id)
    fixer.propose_fix(building_id, "aed")
    if summary.get("worst_gap") == "extinguisher":
        fixer.propose_fix(building_id, "extinguisher")
    fixer.write_documents(building_id)
    finish_building(building_id)
    return summary


def _is_complete(building_id: str) -> bool:
    has_score = db.fetch_one("building_scores", columns="building_id",
                             filters=[("eq", "building_id", building_id)]) is not None
    has_fix = db.fetch_one("fixes", columns="id", filters=[("eq", "building_id", building_id)]) is not None
    kinds = {d["kind"] for d in db.fetch_all("documents", columns="kind",
                                             filters=[("eq", "building_id", building_id)])}
    return has_score and has_fix and kinds >= set(fixer.DOC_KINDS)


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


def _set_run(run_id: str, **values: Any) -> None:
    db.update("runs", values, filters=[("eq", "id", run_id)])


def _stop_requested(run_id: str) -> bool:
    if _stops.get(run_id) and _stops[run_id].is_set():
        return True
    row = db.fetch_one("runs", columns="status", filters=[("eq", "id", run_id)])
    return bool(row and row.get("status") in ("stopping", "stopped"))


def _candidates(cfg: RunConfig) -> list[str]:
    if cfg.building_ids:
        return list(cfg.building_ids)
    filters = [("eq", "city", cfg.city)] if cfg.city else []
    rows = db.fetch_all("buildings", columns="id,property_type,census_status", filters=filters)
    if cfg.types:
        wanted = [t.lower() for t in cfg.types]
        rows = [r for r in rows if any(w in (r.get("property_type") or "").lower() for w in wanted)]
    return [r["id"] for r in rows if r.get("census_status") != DONE]


def _process_batch(batch: list[str], cfg: RunConfig, context: ToolContext, model: Any) -> Iterator[tuple[str, bool]]:
    """Yields (building_id, ok) as each building finishes, so progress is saved per building."""
    if cfg.mode == "agent":
        from census.agent.planner import run_buildings

        try:
            run_buildings(batch, context, model=model)
        except Exception as exc:  # a planner failure must not end the run
            log.exception("planner failed on batch")
            warning(AGENT, "planner_error", f"The planner stopped on this batch ({type(exc).__name__}); "
                    "checking each building.", None, {"error": str(exc)[:500], "buildings": batch})
        for bid in batch:
            try:
                ok = _is_complete(bid)
                if ok:
                    finish_building(bid)
            except Exception as exc:
                log.exception("finishing %s failed", bid)
                warning(AGENT, "building_error", f"Could not finish a building ({type(exc).__name__}).", bid,
                        {"error": str(exc)[:500]})
                ok = False
            yield bid, ok
        return
    for bid in batch:
        if _stop_requested(context.run_id) or budget.budget_exhausted():
            break
        try:
            process_building(bid)
        except Exception as exc:  # failure policy: mark, warn, continue
            log.exception("building %s failed", bid)
            warning(AGENT, "building_error",
                    f"A building failed ({type(exc).__name__}); marking it as an error and moving on.", bid,
                    {"error": str(exc)[:500]})
            yield bid, False
        else:
            yield bid, True


def _run_loop(run_id: str, cfg: RunConfig, context: ToolContext, model: Any = None) -> str:
    with use_context(context):
        row = db.fetch_one("runs", filters=[("eq", "id", run_id)]) or {}
        target = int(row.get("buildings_target") or 0)
        done = int(row.get("buildings_done") or 0)
        panos = int(row.get("panos_done") or 0)
        order = records.prioritize(_candidates(cfg))
        order = order[: max(0, target - done)] if target else order
        if not order:
            result(AGENT, "run", "Nothing left to scan in this run.", None, {"buildings": 0})
        status = "done"
        for i in range(0, len(order), max(1, cfg.batch_size)):
            if _stop_requested(run_id):
                status = "stopped"
                warning(AGENT, "stopped", "Run stopped on request; no new buildings will start.")
                break
            if budget.budget_exhausted(run_id):
                status = "budget_stopped"
                warning(AGENT, "budget_exhausted", "Budget used up, so no new buildings will start.", None,
                        {"budget_usd": context.budget_usd, "spent_usd": budget.spent_usd(run_id)})
                break
            batch = order[i:i + cfg.batch_size]
            for bid, ok in _process_batch(batch, cfg, context, model):
                if ok:
                    done += 1
                    panos += _panos_tiled(bid)
                else:
                    db.set_building(bid, census_status="error")
                _set_run(run_id, buildings_done=done, panos_done=panos)
            ranking.rerank()
        else:
            if budget.budget_exhausted(run_id) and done < len(order):
                status = "budget_stopped"
        if status == "done" and _stop_requested(run_id):
            status = "stopped"
        _set_run(run_id, status=status, finished_at=db.now_iso(), buildings_done=done)
        left = budget.budget_remaining(run_id)
        result(AGENT, "run", f"Run finished: {done} building{'s' if done != 1 else ''} done ({status}).", None,
               {"status": status, "buildings_done": done,
                "budget_remaining_usd": None if left is None else round(left, 4)})
        return status


def _panos_tiled(building_id: str) -> int:
    """Panoramas tiled for one finished building (a real count from the panos table)."""
    return len(db.fetch_all("panos", columns="sweep_id",
                            filters=[("eq", "building_id", building_id), ("eq", "tiles_done", True)]))


def _launch(run_id: str, cfg: RunConfig, context: ToolContext, background: bool, model: Any) -> None:
    _stops[run_id] = threading.Event()

    def target() -> None:
        with use_context(context):
            try:
                _run_loop(run_id, cfg, context, model)
            except Exception as exc:  # record the crash on the run row
                log.exception("run %s crashed", run_id)
                warning(AGENT, "run_error", f"The run stopped unexpectedly ({type(exc).__name__}).", None,
                        {"error": str(exc)[:500]})
                _set_run(run_id, status="error", finished_at=db.now_iso())
            finally:
                _stops.pop(run_id, None)
                _threads.pop(run_id, None)

    if background:
        thread = threading.Thread(target=target, name=f"census-run-{run_id[:8]}", daemon=True)
        _threads[run_id] = thread
        thread.start()
    else:
        target()


def _create_run(target: int, cfg: RunConfig) -> str:
    (row,) = db.insert("runs", [{"buildings_target": target, "status": "running", "notes": cfg.notes()}])
    return row["id"]


def start_run(buildings_target: int, city: str | None, types: list[str] | None, budget_usd: float, *,
              mode: str = "agent", batch_size: int = DEFAULT_BATCH_SIZE, background: bool = True,
              model: Any = None) -> str:
    """Create the runs row, start the census in the background, return the run id."""
    cfg = RunConfig(budget_usd=budget_usd, city=city, types=types, mode=mode, batch_size=batch_size)
    run_id = _create_run(buildings_target, cfg)
    context = with_changes(run_id=run_id, budget_usd=budget_usd)
    with use_context(context):
        decision(AGENT, f"Starting a census run for up to {buildings_target} buildings with a "
                        f"${budget_usd:.2f} budget.", "requested run", None,
                 options={"city": city, "types": types, "mode": mode})
    _launch(run_id, cfg, context, background, model)
    return run_id


def rerun_building(building_id: str, *, mode: str = "agent", background: bool = True, model: Any = None,
                   budget_usd: float | None = None) -> str:
    """One-building run for the stage demo; events are paced by DEMO_EVENT_DELAY_MS."""
    budget_usd = budget_usd if budget_usd is not None else ctx().budget_usd
    cfg = RunConfig(budget_usd=budget_usd, mode=mode, batch_size=1, building_ids=[building_id])
    run_id = _create_run(1, cfg)
    db.set_building(building_id, census_status="pending")
    _launch(run_id, cfg, with_changes(run_id=run_id, budget_usd=budget_usd), background, model)
    return run_id


def resume_run(run_id: str, *, background: bool = True, model: Any = None) -> str:
    """Continue a run that crashed or was stopped, with its stored budget and filters."""
    row = db.fetch_one("runs", filters=[("eq", "id", run_id)])
    if row is None:
        raise ValueError(f"run {run_id} not found")
    cfg = RunConfig.from_notes(row.get("notes"))
    _set_run(run_id, status="running", finished_at=None)
    context = with_changes(run_id=run_id, budget_usd=cfg.budget_usd)
    with use_context(context):
        decision(AGENT, f"Resuming the run with {row.get('buildings_done') or 0} buildings already done.",
                 "resume after a crash or stop", None)
    _launch(run_id, cfg, context, background, model)
    return run_id


def stop_run(run_id: str) -> None:
    """Ask a run to stop after the building in progress."""
    if run_id in _stops:
        _stops[run_id].set()
    _set_run(run_id, status="stopping")


def wait(run_id: str, timeout: float | None = None) -> None:
    """Block until a background run finishes (tests and the CLI)."""
    thread = _threads.get(run_id)
    if thread is not None:
        thread.join(timeout)
