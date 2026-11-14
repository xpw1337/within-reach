"""Hand-check of census detections (spec section 9.3 step 7). Writes only ``detections.human_label``."""

from __future__ import annotations

import random
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from agent.api.common import db_or_503, in_thread

router = APIRouter(prefix="/census")
LABELS = ("correct", "incorrect", "unsure")


class LabelRequest(BaseModel):
    human_label: Literal["correct", "incorrect", "unsure"]


def sample_rows(rows: list[dict], n: int, rng: random.Random | None = None) -> list[dict]:
    """Random sample of confirmed detections, unlabeled first."""
    rng = rng or random.Random()
    unlabeled = [r for r in rows if not r.get("human_label")]
    labeled = [r for r in rows if r.get("human_label")]
    rng.shuffle(unlabeled)
    rng.shuffle(labeled)
    picked = (unlabeled + labeled)[: max(0, n)]
    return [{"detection_id": r["id"], "asset_type": r.get("asset_type"), "crop_url": r.get("crop_uri"),
             "confidence": r.get("confidence"), "status": r.get("status")} for r in picked]


def summarize(rows: list[dict]) -> dict:
    counts = {label: sum(1 for r in rows if r.get("human_label") == label) for label in LABELS}
    return {"labeled": sum(counts.values()), **counts}


@router.get("/handcheck")
async def handcheck(n: int = Query(30, ge=1, le=500)) -> list[dict]:
    db = db_or_503()
    rows = await in_thread(db.fetch_all, "detections",
                           columns="id,asset_type,crop_uri,confidence,status,human_label", status="confirmed")
    return sample_rows(rows, n)


@router.post("/detections/{detection_id}/label")
async def label(detection_id: str, body: LabelRequest) -> dict:
    db = db_or_503()
    rows = await in_thread(db.update, "detections", {"human_label": body.human_label}, id=detection_id)
    if not rows:
        raise HTTPException(404, "unknown detection")
    return {"ok": True}


@router.get("/handcheck/summary")
async def summary() -> dict:
    db = db_or_503()
    rows = await in_thread(db.fetch_all, "detections", columns="human_label")
    return summarize(rows)
