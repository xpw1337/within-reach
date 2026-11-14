"""Twilio webhooks: form-encoded in, TwiML out. Calls only ever go to the allowlist (io/telephony.py).

When ``TWILIO_AUTH_TOKEN`` is set, every webhook must carry a valid ``X-Twilio-Signature`` computed
over ``PUBLIC_BASE_URL`` + path. Not verified against a real Twilio account yet.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from twilio.twiml.voice_response import VoiceResponse

from agent.api.dispatches import answer
from agent.deps import get_runtime
from agent.live.briefing import build_briefing
from agent.live.playbooks import camera_context

router = APIRouter(prefix="/twilio")


def twiml(vr: VoiceResponse) -> Response:
    return Response(content=str(vr), media_type="application/xml")


async def _form(request: Request) -> dict[str, Any]:
    form = dict(await request.form())
    try:
        from shared.config import get_settings

        s = get_settings()
    except ImportError:
        return form
    if s.twilio_auth_token:
        from twilio.request_validator import RequestValidator

        base = (s.public_base_url or str(request.base_url)).rstrip("/")
        url = base + request.url.path + (f"?{request.url.query}" if request.url.query else "")
        signature = request.headers.get("X-Twilio-Signature", "")
        if not RequestValidator(s.twilio_auth_token).validate(url, form, signature):
            raise HTTPException(403, "invalid Twilio signature")
    return form


def _aed_phrase(state: dict) -> str | None:
    ctx = camera_context(state.get("camera") or {}, state.get("routes") or {})
    if ctx.get("aed_distance") and ctx.get("aed_directions"):
        return f"{ctx['aed_distance']} meters, {ctx['aed_directions']}"
    return None


def role_message(role: str | None, status: str | None, state: dict) -> str:
    landmark = (state.get("camera") or {}).get("landmark") or "the camera"
    aed = _aed_phrase(state)
    if role == "patient":
        return (f"You are going to the person by {landmark}. "
                "Go to them, tap their shoulder and shout. If they don't respond and aren't breathing "
                "normally, call 911 on speaker and start CPR: push hard and fast in the center of the chest.")
    if role == "aed_runner":
        where = f": {aed}" if aed else ""
        return f"You are the AED runner. Get the AED{where}. Then bring it to {landmark}."
    if status == "released":
        return "Two responders are already on the way. Thank you, you can stand down."
    if status == "declined":
        return "Thank you. Goodbye."
    return "This alert is no longer active. Thank you."


async def _incident_for_dispatch(rt, dispatch_id: str) -> tuple[str, dict, dict]:
    incident_id, d = await rt.find_dispatch(dispatch_id)
    if incident_id is None:
        raise HTTPException(404, "unknown dispatch")
    return incident_id, d or {}, await rt.get_state(incident_id) or {}


@router.post("/voice/{dispatch_id}")
async def voice(dispatch_id: str, request: Request, rt=Depends(get_runtime)) -> Response:
    await _form(request)
    _, d, state = await _incident_for_dispatch(rt, dispatch_id)
    vr = VoiceResponse()
    if state.get("resolved") or d.get("status") not in ("sent", "timeout"):
        vr.say(role_message(d.get("role"), d.get("status"), state))
        vr.hangup()
        return twiml(vr)
    landmark = (state.get("camera") or {}).get("landmark") or "the camera"
    building = (state.get("building") or {}).get("name")
    where = f" at {building}" if building else ""
    aed = _aed_phrase(state)
    situation = f"Emergency alert from Within Reach. Someone has collapsed by {landmark}{where}."
    ask = ("If you can help, you will either go to the person or bring the AED"
           + (f", {aed}." if aed else ".") + " Press 1 to help. Press 2 if you can't.")
    gather = vr.gather(num_digits=1, action=f"/twilio/gather/{dispatch_id}", method="POST", timeout=10)
    gather.say(situation + " " + ask)
    vr.say("No answer received. Goodbye.")
    return twiml(vr)


@router.post("/gather/{dispatch_id}")
async def gather(dispatch_id: str, request: Request, rt=Depends(get_runtime)) -> Response:
    form = await _form(request)
    digits = str(form.get("Digits") or "").strip()
    vr = VoiceResponse()
    if digits == "1":
        d = await answer(rt, dispatch_id, "accept", "twilio")
    elif digits == "2":
        d = await answer(rt, dispatch_id, "decline", "twilio")
    else:
        vr.redirect(f"/twilio/voice/{dispatch_id}", method="POST")
        return twiml(vr)
    _, _, state = await _incident_for_dispatch(rt, dispatch_id)
    vr.say(role_message(d.get("role"), d.get("status"), state))
    vr.hangup()
    return twiml(vr)


@router.post("/briefing/{incident_id}")
async def briefing(incident_id: str, request: Request, rt=Depends(get_runtime)) -> Response:
    await _form(request)
    state = await rt.get_state(incident_id)
    if state is None:
        raise HTTPException(404, "unknown incident")
    vr = VoiceResponse()
    if request.query_params.get("spoken") == "1":
        # Twilio reached the end of the spoken briefing: now the same text goes out as an iMessage.
        rt.imessage.briefing_spoken(incident_id)
        vr.hangup()
        return twiml(vr)
    text = build_briefing(state, rt.clock.now())
    vr.say(text)
    vr.pause(length=1)
    vr.say(text)  # spec section 9.10: spoken twice
    if rt.imessage.enabled:
        rt.imessage.briefing_said(incident_id, text)
        vr.redirect(f"/twilio/briefing/{incident_id}?spoken=1", method="POST")
    else:
        vr.hangup()
    return twiml(vr)

