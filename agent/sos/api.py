"""HTTP and websocket API of the live SOS path.

Vision:     POST /events                      person_down, responsive, possible_seizure,
                                              responder_arrived, fire_detected, fire_cleared
Dashboard:  WS   /sos/ws/console              full state on every change
            GET  /sos/state
            PUT  /sos/cameras/{camera_id}     {lat, lng, accuracy_m?, label?}  where the camera is
            POST /sos/fire                    {lat?, lng?, radius_m?}  report a fire (default: at the person)
            DELETE /sos/fire
            POST /sos/places                  {kind: aed|extinguisher, lat, lng, label?}  pin equipment
            DELETE /sos/places/{place_id}
            POST /sos/simulate/fall           {camera_id?}  test without a camera
            POST /sos/resolve, POST /sos/reset
            GET  /sos/incidents/{id}/snapshot.jpg
Phone:      WS   /sos/ws/phone                {type: hello|location|duty|accept|decline|collected|arrived}
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from agent.sos.hub import Hub

log = logging.getLogger(__name__)
router = APIRouter()


def hub_of(obj: Request | WebSocket) -> Hub:
    return obj.app.state.sos


class VisionEventIn(BaseModel):
    camera_id: str
    kind: Literal["person_down", "responsive", "possible_seizure", "responder_arrived",
                  "fire_detected", "fire_cleared"]
    ts: str | None = None
    victim_track_id: int | None = None
    witnessed: bool | None = None
    frame_jpeg_b64: str | None = None
    fire: dict[str, Any] | None = None


@router.post("/events")
async def vision_event(body: VisionEventIn, request: Request) -> dict:
    hub = hub_of(request)
    try:
        if body.kind == "person_down":
            snap = None
            if body.frame_jpeg_b64:
                try:
                    snap = base64.b64decode(body.frame_jpeg_b64, validate=True)
                except ValueError:
                    snap = None
            inc = await hub.open_incident("fall", body.camera_id, witnessed=body.witnessed, snapshot=snap)
            return {"incident_id": inc["id"], "status": inc["status"]}
        if body.kind == "fire_detected":
            f = body.fire or {}
            fire = {"source": "camera", "label": f.get("label"), "conf": f.get("conf")}
            inc = await hub.open_incident("fire", body.camera_id, fire=fire)
            return {"incident_id": inc["id"], "status": inc["status"]}
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    if body.kind == "fire_cleared":
        hub.clear_fire("camera")
    else:
        hub.vision_signal(body.kind)
    inc = hub.incident
    return {"incident_id": inc["id"] if inc else None, "status": inc["status"] if inc else "none"}


@router.get("/sos/state")
async def state(request: Request) -> dict:
    return hub_of(request).console_state()


class CameraIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = None
    label: str | None = Field(default=None, max_length=80)


@router.put("/sos/cameras/{camera_id}")
async def put_camera(camera_id: str, body: CameraIn, request: Request) -> dict:
    return hub_of(request).set_camera(camera_id, body.lat, body.lng, body.accuracy_m, body.label)


class FireIn(BaseModel):
    lat: float | None = None
    lng: float | None = None
    radius_m: float | None = Field(default=None, gt=0, le=500)
    camera_id: str | None = None


@router.post("/sos/fire")
async def report_fire(body: FireIn, request: Request) -> dict:
    hub = hub_of(request)
    fire = {"source": "manual", "label": "fire", "radius_m": body.radius_m}
    if body.lat is not None and body.lng is not None:
        fire.update(lat=body.lat, lng=body.lng)
    if hub.incident and hub.incident["status"] in ("alerting", "en_route", "on_scene", "no_responders"):
        hub.set_fire(fire)
        return {"incident_id": hub.incident["id"]}
    cam_id = body.camera_id or next((c["id"] for c in hub.cameras.values()), "default")
    loc = None
    if body.lat is not None and body.lng is not None:
        loc = {"lat": body.lat, "lng": body.lng, "accuracy_m": None, "label": "reported fire"}
    try:
        inc = await hub.open_incident("fire", cam_id, fire=fire, location=loc)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"incident_id": inc["id"]}


@router.delete("/sos/fire")
async def clear_fire(request: Request) -> dict:
    hub_of(request).clear_fire("manual")
    return {"ok": True}


class PlaceIn(BaseModel):
    kind: Literal["aed", "extinguisher"]
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=80)


@router.post("/sos/places")
async def add_place(body: PlaceIn, request: Request) -> dict:
    return hub_of(request).add_place(body.kind, body.lat, body.lng, body.label)


@router.delete("/sos/places/{place_id}")
async def remove_place(place_id: str, request: Request) -> dict:
    if not hub_of(request).remove_place(place_id):
        raise HTTPException(404, "no such pin")
    return {"ok": True}


class SimIn(BaseModel):
    camera_id: str | None = None


@router.post("/sos/simulate/fall")
async def simulate_fall(request: Request, body: SimIn | None = None) -> dict:
    hub = hub_of(request)
    cam_id = (body.camera_id if body else None) or next((c["id"] for c in hub.cameras.values()), "default")
    try:
        inc = await hub.open_incident("fall", cam_id, witnessed=True)
    except LookupError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"incident_id": inc["id"]}


@router.post("/sos/responders/{responder_id}/texts")
async def enable_texts(responder_id: str, request: Request) -> dict:
    """Set up iMessage alerts for a responder's phone (Photon shared line). Returns the line the
    person must text once. The phone number itself never leaves the agent in this reply."""
    hub = hub_of(request)
    r = hub.responders.get(responder_id)
    if r is None or not r.get("phone"):
        raise HTTPException(404, "no responder with a phone number under that id")
    from agent.sos.texts import TextError

    try:
        out = await hub.texter.enable(r["phone"], r.get("name"))
    except TextError as exc:
        raise HTTPException(502, str(exc)) from exc
    r["text_line"] = out["line"]
    hub.changed()
    return {"responder": r.get("name"), **out}


@router.post("/sos/resolve")
async def resolve(request: Request) -> dict:
    return {"ok": hub_of(request).resolve("closed from the dashboard")}


@router.post("/sos/reset")
async def reset(request: Request) -> dict:
    hub_of(request).reset()
    return {"ok": True}


@router.get("/sos/incidents/{incident_id}/snapshot.jpg")
async def snapshot(incident_id: str, request: Request) -> Response:
    data = hub_of(request).snapshots.get(incident_id)
    if not data:
        raise HTTPException(404, "no snapshot")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.websocket("/sos/ws/console")
async def console_ws(ws: WebSocket) -> None:
    hub = hub_of(ws)
    await ws.accept()

    async def send(msg: dict[str, Any]) -> None:
        await ws.send_json(msg)

    hub.consoles.add(send)
    try:
        await send({"type": "state", "state": hub.console_state()})
        while True:
            await ws.receive_text()  # keepalive pings; commands go over HTTP
    except WebSocketDisconnect:
        pass
    finally:
        hub.consoles.discard(send)


@router.websocket("/sos/ws/phone")
async def phone_ws(ws: WebSocket) -> None:
    hub = hub_of(ws)
    await ws.accept()
    rid: str | None = None

    async def send(msg: dict[str, Any]) -> None:
        await ws.send_json(msg)

    try:
        while True:
            msg = await ws.receive_json()
            t = msg.get("type")
            if t == "hello":
                rid = str(msg.get("id") or "")[:64]
                if not rid:
                    await send({"type": "error", "message": "hello needs an id"})
                    continue
                hub.responder_hello(rid, (msg.get("name") or "").strip()[:60] or None, send)
                hub.responder_update(rid, msg)
                await send({"type": "state", **hub.phone_state(rid)})
            elif rid is None:
                await send({"type": "error", "message": "say hello first"})
            elif t in ("location", "duty", "ping"):
                hub.responder_update(rid, msg)
                if t == "ping":
                    await send({"type": "pong"})
            elif t in ("accept", "decline"):
                res = hub.respond(str(msg.get("offer_id")), rid, "accepted" if t == "accept" else "declined")
                await send({"type": "result", "action": t, **res})
            elif t == "collected":
                await send({"type": "result", "action": t, **hub.collected(rid, str(msg.get("what")))})
            elif t == "arrived":
                await send({"type": "result", "action": t, **hub.arrived(rid)})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 - bad JSON etc.: drop this socket only
        log.info("phone socket closed: %s", exc)
    finally:
        if rid:
            hub.responder_gone(rid, send)


GATHER_REPLY = {
    "1": "Thank you. Open the Within Reach app for directions. Help is on the way.",
    "2": "Okay. We will ask someone else.",
}


@router.post("/sos/twilio/gather/{offer_id}")
async def twilio_gather(offer_id: str, request: Request) -> Response:
    """Keypad answer from the alert call: 1 accepts, 2 declines (only with PUBLIC_BASE_URL set)."""
    hub = hub_of(request)
    form = dict(await request.form())
    caller = hub.caller
    signature = request.headers.get("X-Twilio-Signature", "")
    if caller.token:
        from twilio.request_validator import RequestValidator

        url = f"{caller.public_url}{request.url.path}"
        if not RequestValidator(caller.token).validate(url, {k: str(v) for k, v in form.items()}, signature):
            raise HTTPException(403, "bad signature")
    digit = str(form.get("Digits") or "")
    text = "We did not get an answer. Open the Within Reach app to respond."
    if digit in GATHER_REPLY:
        res = hub.respond(offer_id, None, "accepted" if digit == "1" else "declined")
        text = GATHER_REPLY[digit] if res.get("ok") else str(res.get("reason") or "This alert is closed.")
    body = f'<Response><Say voice="Polly.Joanna">{text}</Say></Response>'
    return Response(body, media_type="application/xml")
