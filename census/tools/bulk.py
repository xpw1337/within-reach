"""Bulk scanning for one building: tiling, first pass, verify and pin in a bounded worker pool
(spec section 9.2 "overnight execution", docs/ARCHITECTURE.md decision D9).

The planner dispatches a whole building with one call instead of thousands of tool calls. Work is
resumable (sweeps with ``panos.tiles_done`` are skipped) and checks the budget between batches.
Borderline confirmations are left unpinned and returned to the planner, which decides whether to
call ``find_second_view`` (that decision is what the console should show).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from census.tools import scanner
from shared import db
from shared.config import get_settings

log = logging.getLogger(__name__)


def _budget_ok(run_id: str | None) -> bool:
    """Default budget guard: the run's metered cost is below CENSUS_BUDGET_USD."""
    if not run_id:
        return True
    row = db.fetch_one("runs", columns="id,est_cost_usd", id=run_id)
    spent = (row or {}).get("est_cost_usd") or 0.0
    return spent < get_settings().census_budget_usd


def _pool_map(
    fn: Callable[[Any], Any], items: list[Any], workers: int
) -> list[tuple[Any, Any, Exception | None]]:
    out: list[tuple[Any, Any, Exception | None]] = []

    def run(item: Any) -> tuple[Any, Any, Exception | None]:
        try:
            return item, fn(item), None
        except Exception as exc:  # noqa: BLE001 - one bad panorama must not stop the building
            return item, None, exc

    if workers <= 1:
        return [run(i) for i in items]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="scan") as pool:
        out.extend(pool.map(run, items))
    return out


def scan_building_bulk(
    building_id: str,
    run_id: str | None = None,
    *,
    concurrency: int | None = None,
    batch_size: int | None = None,
    verify: bool = True,
    pin: bool = True,
    budget_ok: Callable[[str | None], bool] | None = None,
) -> dict:
    """Scan every untiled panorama of a building and return a short summary."""
    rid = scanner._run_id(run_id)
    workers = concurrency or get_settings().scan_concurrency
    batch = batch_size or max(workers * 2, 1)
    check = budget_ok or _budget_ok
    scanner._tool_call(rid, "scan_building_bulk", {"building_id": building_id}, building_id)

    pending = sorted(
        p["sweep_id"] for p in db.fetch_all("panos", building_id=building_id, tiles_done=False)
    )
    stopped_for_budget = False
    scanned, failed = 0, []
    for i in range(0, len(pending), batch):
        if not check(rid):
            stopped_for_budget = True
            break
        chunk = pending[i : i + batch]
        for sweep_id, _res, exc in _pool_map(
            lambda s: scanner.detect_first_pass(building_id, s, rid, quiet=True), chunk, workers
        ):
            if exc is None:
                scanned += 1
            else:
                failed.append(sweep_id)
                log.warning("first pass failed for %s/%s: %s", building_id, sweep_id, exc)

    confirmed = rejected = 0
    borderline: list[str] = []
    pinned = merged = 0
    if verify and not stopped_for_budget:
        # First-pass threads insert detections in completion order; sort so pinning and duplicate
        # merging (which depend on order) give the same assets on every run.
        rows = db.fetch_all("detections", building_id=building_id, status="candidate")
        rows.sort(
            key=lambda d: (
                str(d.get("sweep_id") or ""),
                float(d.get("tile_heading") or 0.0),
                float(d.get("tile_pitch") or 0.0),
                str(d.get("created_at") or ""),
                str(d.get("id")),
            )
        )
        candidates = [d["id"] for d in rows]
        for i in range(0, len(candidates), batch):
            if not check(rid):
                stopped_for_budget = True
                break
            for _did, res, exc in _pool_map(
                lambda d: scanner.verify_crop(d, rid, quiet=True), candidates[i : i + batch], workers
            ):
                if exc is not None or res is None:
                    continue
                if not res["confirmed"]:
                    rejected += 1
                    continue
                confirmed += 1
                if res["borderline"]:
                    borderline.append(res["detection_id"])
                elif pin:
                    p = scanner.pin_asset(
                        res["detection_id"], rid, quiet=True
                    )  # serial: merging reads assets
                    pinned += int(p.get("pinned", False) and not p.get("merged", False))
                    merged += int(p.get("merged", False))

    if stopped_for_budget:
        scanner._emit(
            rid,
            "warning",
            "Budget reached, so the scan of this building stopped early.",
            building_id,
            {"code": "budget", "detail": {"building_id": building_id}},
        )
    summary = {
        "building_id": building_id,
        "panos_scanned": scanned,
        "panos_pending": len(pending) - scanned - len(failed),
        "panos_failed": len(failed),
        "confirmed": confirmed,
        "rejected": rejected,
        "assets_new": pinned,
        "assets_merged": merged,
        "borderline": len(borderline),
        "borderline_detection_ids": borderline[:10],
        "stopped_for_budget": stopped_for_budget,
    }
    msg = (
        f"Scanned {scanned} panoramas: {confirmed} items confirmed, {rejected} rejected, "
        f"{pinned} new assets pinned, {len(borderline)} borderline left for a second view."
    )
    if failed:
        msg = msg[:-1] + f"; {len(failed)} panoramas failed."
    scanner._result(rid, "scan_building_bulk", msg, building_id, summary)
    return summary
