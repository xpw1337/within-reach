"""``POST /photon/webhook``: iMessage replies from responders (docs/CONTRACTS.md, Photon 2.0).

Verification follows Photon's Beta docs (Standard Webhooks): headers ``webhook-id``,
``webhook-timestamp`` and ``webhook-signature`` (space-separated ``v1,<base64>``); the signature is
HMAC-SHA256 over ``{webhook-id}.{webhook-timestamp}.{raw body}`` keyed with the base64-decoded
part of ``PHOTON_WEBHOOK_SECRET`` after ``whsec_``; timestamps more than 5 minutes off are
rejected. A bad signature returns 400 and nothing is processed.

The event coded against (``message.received``, apiVersion 2026-07-01, iMessage variant)::

    {"id": "...", "type": "message.received", "apiVersion": "2026-07-01", "source": "imessage.photon",
     "timestamp": "...", "data": {"projectId": "pho_prj_...", "object": {
        "id": "pho_msg_...", "platform": "imessage", "status": "received",
        "space": {"id": "pho_spc_...", "kind": "direct", ...},
        "sentBy": {"id": "pho_usr_...", "handle": "+1...", "kind": "human", ...},
        "receivedBy": {"id": "pho_usr_...", "handle": "<our line>", "kind": "agent", ...},
        "content": {"type": "text", "format": "plain", "text": "1"}, ...}}}

A reply from a responder's phone maps to their open dispatch: ``1`` accept, ``2`` decline,
``here`` arrived (``with_aed`` for the AED runner), delivered through ``signals.deliver`` like the
app and phone digits, so repeats are no-ops. Duplicate deliveries (same ``webhook-id``) are
skipped. Anything else, and unknown senders, get ``{ok: true}`` and are ignored.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from agent.api.dispatches import answer
from agent.deps import get_runtime
from agent.io.telephony import E164, normalize
from agent.live.state import DISPATCH_ENGAGED, DISPATCH_OPEN

log = logging.getLogger(__name__)
router = APIRouter(prefix="/photon")

TOLERANCE_S = 300  # Standard Webhooks: reject timestamps more than five minutes off
COMMANDS = {"1": "accept", "2": "decline", "here": "arrived"}


class SignatureError(ValueError):
    pass


def verify_signature(secret: str, headers: Mapping[str, str], body: bytes, now: float) -> None:
    """Standard Webhooks verification. Raises ``SignatureError``; returns None when valid."""
    msg_id = headers.get("webhook-id") or ""
    timestamp = headers.get("webhook-timestamp") or ""
    signatures = headers.get("webhook-signature") or ""
    if not (msg_id and timestamp and signatures):
        raise SignatureError("missing webhook headers")
    try:
        ts = int(timestamp)
    except ValueError:
        raise SignatureError("bad timestamp") from None
    if abs(now - ts) > TOLERANCE_S:
        raise SignatureError("timestamp outside the tolerance")
    raw = secret.removeprefix("whsec_")
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise SignatureError("PHOTON_WEBHOOK_SECRET is not a whsec_ base64 secret") from None
    expected = base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + body, hashlib.sha256).digest())
    for part in signatures.split():
        version, _, sig = part.partition(",")
        if version == "v1" and hmac.compare_digest(sig.encode(), expected):
            return
    raise SignatureError("no matching signature")


def parse_reply(text: Any) -> str | None:
    """``1`` -> accept, ``2`` -> decline, ``here`` -> arrived (case, spaces and punctuation ignored)."""
    if not isinstance(text, str):
        return None
    return COMMANDS.get(re.sub(r"[^a-z0-9]", "", text.lower()))


async def find_open_dispatch(rt, number: str, reply: str) -> tuple[str, dict[str, Any]] | None:
    """The latest dispatch of the responder with this phone in an open incident that the reply can
    still act on (the reducer ignores anything that no longer applies)."""
    responders = await rt.store.list_responders()
    ids = {r["id"] for r in responders if r.get("phone") and normalize(r["phone"]) == number}
    if not ids:
        return None
    statuses = DISPATCH_ENGAGED if reply == "arrived" else DISPATCH_OPEN + DISPATCH_ENGAGED
    best: tuple[str, dict[str, Any]] | None = None
    for incident_id in list(rt.known_incidents):
        state = await rt.get_state(incident_id) or {}
        if state.get("resolved"):
            continue
        for d in state.get("dispatches") or []:
            if d.get("responder_id") not in ids or d.get("status") not in statuses:
                continue
            if best is None or (d.get("sent_at") or 0) >= (best[1].get("sent_at") or 0):
                best = (incident_id, d)
    return best


async def handle_event(rt, event: Mapping[str, Any]) -> str:
    """Apply one verified event. Returns what happened (for logs and tests)."""
    if event.get("type") != "message.received":
        return "ignored: not message.received"
    obj = (event.get("data") or {}).get("object") or {}
    if obj.get("platform") != "imessage" or obj.get("status") != "received":
        return "ignored: not a received iMessage"
    sender = obj.get("sentBy") or {}
    if sender.get("kind") == "agent":
        return "ignored: sent by an agent"
    handle = str(sender.get("handle") or "")
    rt.imessage.remember(handle, (obj.get("space") or {}).get("id"), (obj.get("receivedBy") or {}).get("id"))
    content = obj.get("content") or {}
    reply = parse_reply(content.get("text")) if content.get("type") == "text" else None
    number = normalize(handle) if handle.startswith("+") else ""
    if reply is None or not E164.match(number):
        return "ignored: not a reply"
    match = await find_open_dispatch(rt, number, reply)
    if match is None:
        return "ignored: no open dispatch for this sender"
    incident_id, d = match
    extra = {"with_aed": d.get("role") == "aed_runner"} if reply == "arrived" else {}
    await rt.imessage.event(incident_id, "imessage_received",
                            {"reply": reply, "dispatch_id": d["id"], "responder_id": d.get("responder_id")})
    await answer(rt, d["id"], reply, "photon", **extra)
    return reply


def _secret(request: Request) -> str | None:
    override = getattr(request.app.state, "photon_webhook_secret", None)
    if override:
        return override
    from agent.deps import settings

    return settings().photon_webhook_secret


@router.post("/webhook")
async def webhook(request: Request, rt=Depends(get_runtime)) -> dict:
    secret = _secret(request)
    if not secret:
        raise HTTPException(503, "PHOTON_WEBHOOK_SECRET is not set")
    body = await request.body()  # the raw body: verification must not see re-serialized JSON
    try:
        verify_signature(secret, request.headers, body, time.time())
    except SignatureError as exc:
        log.warning("Photon webhook rejected: %s", exc)
        raise HTTPException(400, "invalid Photon webhook signature") from None
    try:
        event = json.loads(body)
    except ValueError:
        raise HTTPException(400, "invalid JSON") from None
    event_id = request.headers["webhook-id"]
    if not isinstance(event, dict) or rt.imessage.seen(event_id):
        return {"ok": True}
    outcome = await handle_event(rt, event)
    rt.imessage.mark_seen(event_id)
    log.info("Photon webhook %s: %s", event.get("type"), outcome)
    return {"ok": True}
