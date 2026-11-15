"""Desk commands. Idempotent: repeating one returns the current state, never an error."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.deps import get_runtime
from agent.live.reducer import derive_status

router = APIRouter(prefix="/incidents")


class ConfirmRequest(BaseModel):
    decision: Literal["confirm", "false_alarm"]
    by: str


class ByRequest(BaseModel):
    by: str | None = None


class MilestoneRequest(BaseModel):
    kind: Literal["cpr_started", "aed_arrived", "responder_arrived", "aed_picked_up", "aed_help_started"]
    by: str | None = None


async def _deliver(rt, incident_id: str, signal: dict) -> dict:
    state = await rt.deliver(incident_id, signal)
    if state is None:
        raise HTTPException(404, "unknown incident")
    return state


@router.post("/{incident_id}/confirm")
async def confirm(incident_id: str, body: ConfirmRequest, rt=Depends(get_runtime)) -> dict:
    kind = "confirm" if body.decision == "confirm" else "false_alarm"
    state = await _deliver(rt, incident_id, {"kind": kind, "source": "desk", "by": body.by})
    return {"status": derive_status(state)}


@router.post("/{incident_id}/cancel_911")
async def cancel_911(incident_id: str, body: ByRequest | None = None, rt=Depends(get_runtime)) -> dict:
    await _deliver(rt, incident_id, {"kind": "cancel_911", "source": "desk", "by": body.by if body else None})
    return {"ok": True}


@router.post("/{incident_id}/milestone")
async def milestone(incident_id: str, body: MilestoneRequest, rt=Depends(get_runtime)) -> dict:
    await _deliver(rt, incident_id, {"kind": "milestone", "source": "desk", "milestone": body.kind,
                                     "by": body.by})
    return {"ok": True}


@router.post("/{incident_id}/resolve")
async def resolve(incident_id: str, body: ByRequest | None = None, rt=Depends(get_runtime)) -> dict:
    state = await _deliver(rt, incident_id, {"kind": "resolve", "source": "desk", "by": body.by if body else None})
    return {"status": derive_status(state)}
