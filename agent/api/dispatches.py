"""Responder answers from the app (and, through twilio.py, from phone digits)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.deps import get_runtime

router = APIRouter(prefix="/dispatches")


class ArrivedRequest(BaseModel):
    with_aed: bool = False


def accept_response(d: dict[str, Any]) -> dict[str, Any]:
    """``{role, status}`` when a role is held (``aed_runner``, ``patient`` or ``staff``),
    ``{status:"released"}`` when the helper roles were already taken."""
    if d.get("status") in ("accepted", "arrived") and d.get("role"):
        return {"role": d["role"], "status": d["status"]}
    return {"status": d.get("status")}


async def answer(rt, dispatch_id: str, kind: str, source: str, **extra: Any) -> dict[str, Any]:
    incident_id, d = await rt.find_dispatch(dispatch_id)
    if incident_id is None:
        raise HTTPException(404, "unknown dispatch")
    state = await rt.deliver(incident_id, {"kind": kind, "source": source, "dispatch_id": dispatch_id, **extra})
    for row in (state or {}).get("dispatches") or []:
        if row.get("id") == dispatch_id:
            return row
    return d or {}


@router.post("/{dispatch_id}/accept")
async def accept(dispatch_id: str, rt=Depends(get_runtime)) -> dict:
    return accept_response(await answer(rt, dispatch_id, "accept", "app"))


@router.post("/{dispatch_id}/decline")
async def decline(dispatch_id: str, rt=Depends(get_runtime)) -> dict:
    d = await answer(rt, dispatch_id, "decline", "app")
    return {"status": d.get("status")}


@router.post("/{dispatch_id}/arrived")
async def arrived(dispatch_id: str, body: ArrivedRequest | None = None, rt=Depends(get_runtime)) -> dict:
    d = await answer(rt, dispatch_id, "arrived", "app", with_aed=bool(body and body.with_aed))
    return {"status": d.get("status")}
