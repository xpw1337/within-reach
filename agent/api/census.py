"""Census commands. census/ is imported lazily: if it is missing, these answer 503."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.api.common import db_or_503, in_thread

router = APIRouter(prefix="/census")


def _census_run():
    try:
        from census import run
    except ImportError as exc:
        raise HTTPException(503, "census not available") from exc
    return run


class RunRequest(BaseModel):
    buildings_target: int
    city: Literal["Houston", "Los Angeles"] | None = None
    types: list[str] | None = None
    budget_usd: float


class FixRequest(BaseModel):
    asset_type: Literal["aed", "extinguisher"] = "aed"


@router.post("/runs")
async def start_run(body: RunRequest) -> dict:
    run = _census_run()
    run_id = await in_thread(run.start_run, body.buildings_target, body.city, body.types, body.budget_usd)
    return {"run_id": run_id}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    db = db_or_503()
    row = await in_thread(db.fetch_one, "runs", id=run_id)
    if row is None:
        raise HTTPException(404, "unknown run")
    return row


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict:
    run = _census_run()
    await in_thread(run.stop_run, run_id)
    return {"status": "stopping"}


@router.post("/buildings/{building_id}/rerun")
async def rerun_building(building_id: str) -> dict:
    run = _census_run()
    return {"run_id": await in_thread(run.rerun_building, building_id)}


@router.post("/buildings/{building_id}/fix")
async def fix_building(building_id: str, body: FixRequest | None = None) -> dict:
    try:
        from census.tools.fixer import propose_fix
    except ImportError as exc:
        raise HTTPException(503, "census not available") from exc
    asset_type = body.asset_type if body else "aed"
    return {"fix_id": await in_thread(propose_fix, building_id, asset_type)}


@router.get("/buildings/{building_id}/documents")
async def documents(building_id: str) -> list[dict]:
    db = db_or_503()
    rows = await in_thread(db.fetch_all, "documents", building_id=building_id)
    return [{k: r.get(k) for k in ("id", "kind", "content_md", "created_at")} for r in rows]
