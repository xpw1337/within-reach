"""POST /simulate/{cardiac|fall|outdoor} and POST /reset.

Simulate injects exactly the event vision would send. cardiac: witnessed ``person_down`` with the
stock frame from ``demo/frames/``, never followed by ``responsive``. fall: ``person_down`` then
``responsive`` 2 s later. outdoor: stretch goal, 501 until built.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from agent.api.events import VisionEvent, handle_event
from agent.deps import get_runtime

log = logging.getLogger(__name__)
router = APIRouter()
FRAMES = Path(__file__).resolve().parents[2] / "demo" / "frames"
SIM_TRACK_ID = 1
FALL_RAISE_HAND_AFTER_S = 2  # agent/DESIGN.md: "person_down then responsive after 2 s"


class SimulateRequest(BaseModel):
    camera_id: str | None = None


def stock_frame_b64() -> str | None:
    for name in ("simulated_cardiac.jpg",):
        p = FRAMES / name
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode()
    return None


@router.post("/simulate/{scenario}")
async def simulate(scenario: str, request: Request, body: SimulateRequest | None = None,
                   rt=Depends(get_runtime)) -> dict:
    if scenario == "outdoor":
        raise HTTPException(501, "outdoor scene is a stretch goal, not built")
    if scenario not in ("cardiac", "fall"):
        raise HTTPException(404, "unknown scenario")
    camera_id = (body.camera_id if body else None) or request.app.state.camera_id
    ev = VisionEvent(camera_id=camera_id, kind="person_down", victim_track_id=SIM_TRACK_ID, witnessed=True,
                     ts=rt.clock.now(), frame_jpeg_b64=stock_frame_b64())
    out = await handle_event(rt, ev)
    if scenario == "fall":
        async def raise_hand() -> None:
            await rt.clock.sleep(FALL_RAISE_HAND_AFTER_S)
            await handle_event(rt, VisionEvent(camera_id=camera_id, kind="responsive",
                                               victim_track_id=SIM_TRACK_ID))

        rt.spawn(raise_hand(), out["incident_id"])
    return {"incident_id": out["incident_id"]}


@router.post("/reset")
async def reset(request: Request, rt=Depends(get_runtime)) -> dict:
    await rt.reset()
    # re-warm: reload the camera context (and render audio if it is missing)
    from agent.main import warm_up

    try:
        await warm_up(request.app)
    except Exception as exc:  # noqa: BLE001
        log.warning("re-warm after reset failed: %s", exc)
    return {"ok": True}
