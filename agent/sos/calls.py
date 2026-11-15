"""Real phone calls to the responder being alerted, through Twilio's REST API.

The call rings even when the app is closed. It speaks the alert twice. When ``PUBLIC_BASE_URL``
(a public tunnel to this agent) is set, the responder can press 1 to accept or 2 to decline right in
the call; without it, the call tells them to open the app.

Two ways out, both run by Twilio:

* a Twilio number: ``TWILIO_FROM_NUMBER``;
* a Photon number over SIP: ``PHOTON_NUMBER`` (caller ID), ``PHOTON_SIP_SERVER`` (the Voice
  profile's SIP connection, ``host:port``), ``PHOTON_SIP_USERNAME`` and ``PHOTON_SIP_PASSWORD``
  (the profile's outbound credentials; the profile's digest must be MD5 for Twilio). Twilio dials
  ``sip:<number>@<server>;transport=tls;secure=true`` and Photon places the call from its number.

Not configured (no Twilio account, or no way out): no call is placed and the hub says so on the
timeline. Emergency numbers are never dialed.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape

import httpx

log = logging.getLogger(__name__)

# Emergency and service short codes in common countries. Calls to these are refused outright.
EMERGENCY = {"911", "112", "999", "000", "110", "119", "100", "101", "102", "108", "933", "988", "211", "311"}


def normalize_phone(raw: str | None, default_country: str = "1") -> str | None:
    """E.164 (+15551234567) from what a person typed, or None if it can't be a phone number."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        e164 = "+" + digits
    elif len(digits) == 10:
        e164 = f"+{default_country}{digits}"
    elif len(digits) == 11 and digits.startswith(default_country):
        e164 = "+" + digits
    else:
        return None
    if not 8 <= len(e164) - 1 <= 15 or is_emergency(e164):
        return None
    return e164


def is_emergency(number: str) -> bool:
    digits = re.sub(r"\D", "", number)
    return digits in EMERGENCY or digits.lstrip("1") in EMERGENCY or len(digits) < 7


@dataclass
class CallResult:
    placed: bool
    sid: str | None = None
    reason: str | None = None


class Caller:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.sid = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
        self.token = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
        self.from_number = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
        self.public_url = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
        self.enabled = os.environ.get("SOS_CALLS", "on").strip().lower() not in ("off", "0", "false", "no")
        self.photon_number = os.environ.get("PHOTON_NUMBER", "").strip()
        self.sip_server = os.environ.get("PHOTON_SIP_SERVER", "").strip()
        self.sip_user = os.environ.get("PHOTON_SIP_USERNAME", "").strip()
        self.sip_password = os.environ.get("PHOTON_SIP_PASSWORD", "").strip()
        self._client = client

    @property
    def via_photon(self) -> bool:
        return bool(self.photon_number and self.sip_server and self.sip_user and self.sip_password)

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.sid and self.token and (self.via_photon or self.from_number))

    def route(self, to: str, photon: bool | None = None) -> dict[str, str]:
        """Twilio's To/From (and SIP credentials) for a call to ``to``."""
        if self.via_photon if photon is None else photon:
            return {"To": f"sip:{to}@{self.sip_server};transport=tls;secure=true", "From": self.photon_number,
                    "SipAuthUsername": self.sip_user, "SipAuthPassword": self.sip_password}
        return {"To": to, "From": self.from_number}

    def twiml(self, text: str, offer_id: str) -> str:
        say = f'<Say voice="Polly.Joanna">{escape(text)}</Say>'
        if self.public_url:
            action = escape(f"{self.public_url}/sos/twilio/gather/{offer_id}")
            prompt = '<Say voice="Polly.Joanna">Press 1 to go. Press 2 if you cannot help.</Say>'
            return (f'<Response><Gather numDigits="1" timeout="8" action="{action}" method="POST">'
                    f"{say}{prompt}</Gather>{say}{prompt}"
                    f'<Redirect method="POST">{action}</Redirect></Response>')
        tail = '<Say voice="Polly.Joanna">Open the Within Reach app to accept.</Say>'
        return f'<Response>{say}{tail}<Pause length="1"/>{say}{tail}</Response>'

    async def call(self, to: str, text: str, offer_id: str) -> CallResult:
        if not self.configured:
            return CallResult(False, reason="Twilio not configured")
        if is_emergency(to):
            return CallResult(False, reason="refused: emergency number")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10)
        routes = [True, False] if self.via_photon and self.from_number else [self.via_photon]
        last = CallResult(False, reason="no route")
        for photon in routes:
            last = await self._place(to, text, offer_id, photon)
            if last.placed:
                return last
            if photon and len(routes) > 1:
                log.warning("call through Photon refused (%s); trying the Twilio number", last.reason)
        return last

    async def _place(self, to: str, text: str, offer_id: str, photon: bool) -> CallResult:
        assert self._client is not None
        try:
            r = await self._client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Calls.json",
                auth=(self.sid, self.token),
                data={**self.route(to, photon), "Twiml": self.twiml(text, offer_id), "Timeout": "25"},
            )
            data: dict[str, Any] = r.json() if r.content else {}
            if r.status_code >= 300:
                return CallResult(False, reason=str(data.get("message") or f"HTTP {r.status_code}")[:160])
            return CallResult(True, sid=data.get("sid"))
        except Exception as exc:  # noqa: BLE001 - the app alert still went out
            return CallResult(False, reason=f"{type(exc).__name__}: {exc}"[:160])

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
