"""POST /events: vision in. ``person_down`` starts an incident; the others resume it."""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from agent.deps import get_runtime
from agent.live.reducer import derive_status

router = APIRouter()


class VisionEvent(BaseModel):
    camera_id: str
    kind: Literal["person_down", "responsive", "possible_seizure", "responder_arrived"]
    victim_track_id: int
    witnessed: bool | None = None
    ts: str | float | None = None
    frame_jpeg_b64: str | None = None


def parse_ts(value: str | float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


async def handle_event(rt, ev: VisionEvent) -> dict:
    if ev.kind == "person_down":
        frame = None
        if ev.frame_jpeg_b64:
            try:
                frame = base64.b64decode(ev.frame_jpeg_b64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise HTTPException(422, "frame_jpeg_b64 is not valid base64") from exc
        incident_id, state = await rt.start_incident(
            camera_id=ev.camera_id, victim_track_id=ev.victim_track_id, witnessed=bool(ev.witnessed),
            event_ts=parse_ts(ev.ts), frame=frame)
        return {"incident_id": incident_id, "status": derive_status(state)}
    incident_id = rt.open_by_camera.get(ev.camera_id)
    if not incident_id:
        return {"incident_id": None, "status": "ignored"}
    state = await rt.deliver(incident_id, {"kind": ev.kind, "source": "vision",
                                           "victim_track_id": ev.victim_track_id})
    return {"incident_id": incident_id, "status": derive_status(state or {})}


@router.post("/events")
async def post_event(ev: VisionEvent, rt=Depends(get_runtime)) -> dict:
    return await handle_event(rt, ev)
