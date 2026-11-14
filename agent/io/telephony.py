"""Phone calls (Twilio Programmable Voice) behind a hard destination allowlist.

Never call real 911 (spec rule 5). Every call goes through ``check_destination``:

- the number must be a full E.164 number (``+`` and 8 to 15 digits), never a short code;
- it must not be, or start with, an emergency code (911, 112, 999 and the others below);
- it must be ``DISPATCH_SIM_NUMBER`` (a teammate's phone) or the phone of a responder who is
  ``callable`` and gave ``consent_calls``.

``FakeTelephony`` applies the same checks, so tests prove the refusal.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

log = logging.getLogger(__name__)

# Emergency numbers that must never be dialed, in any form. North America, EU/UK, Australia,
# India, Japan, China and others; plus 933 (the US 911 address test line).
EMERGENCY_CODES = frozenset(
    {"911", "933", "112", "999", "000", "100", "101", "102", "108", "110", "113", "118", "119", "120",
     "122", "15", "17", "18", "061", "08", "106", "111", "190", "192", "193", "194"}
)
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class TelephonyError(RuntimeError):
    pass


class EmergencyNumberError(TelephonyError):
    """Raised for any destination that looks like an emergency number."""


class DestinationNotAllowedError(TelephonyError):
    pass


def _digits(number: str) -> str:
    return "".join(ch for ch in str(number) if ch.isdigit())


def is_emergency_number(number: str | None) -> bool:
    if not number:
        return False
    digits = _digits(number)
    if digits in EMERGENCY_CODES:
        return True
    # a country code (1 to 3 digits) followed by an emergency code: "+1 911", "+44 999"
    if any(digits[k:] in EMERGENCY_CODES for k in (1, 2, 3) if len(digits) > k):
        return True
    # NANP: N11 codes are never valid area codes, so (911) xxx-xxxx is an emergency dial attempt.
    if len(digits) == 11 and digits.startswith("1911"):
        return True
    return len(digits) == 10 and digits.startswith("911")


def normalize(number: str) -> str:
    s = str(number).strip()
    return "+" + _digits(s) if s.startswith("+") else _digits(s)


def check_destination(number: str | None, allowed: set[str]) -> str:
    """Return the normalized number if it may be called; raise otherwise."""
    if not number:
        raise DestinationNotAllowedError("no destination number")
    if is_emergency_number(number):
        raise EmergencyNumberError(f"refusing to call an emergency number: {number!r}")
    norm = normalize(number)
    if not E164.match(norm):
        raise DestinationNotAllowedError(f"not a full E.164 number: {number!r}")
    if norm not in {normalize(a) for a in allowed if a}:
        raise DestinationNotAllowedError("destination is not on the allowlist")
    return norm


def responder_allowed(responder: Mapping[str, Any]) -> bool:
    return bool(responder.get("callable") and responder.get("consent_calls") and responder.get("phone"))


class Telephony(Protocol):
    async def call_responder(self, dispatch: Mapping[str, Any], responder: Mapping[str, Any]) -> str: ...
    async def call_briefing(self, incident_id: str) -> str: ...
    async def hangup(self, call_sid: str) -> None: ...


class _Base:
    def __init__(self, dispatch_sim_number: str | None) -> None:
        if dispatch_sim_number and is_emergency_number(dispatch_sim_number):
            raise EmergencyNumberError("DISPATCH_SIM_NUMBER is an emergency number; refusing to start")
        self.dispatch_sim_number = dispatch_sim_number

    def _responder_number(self, responder: Mapping[str, Any]) -> str:
        if not responder_allowed(responder):
            raise DestinationNotAllowedError("responder is not callable or did not consent to calls")
        return check_destination(responder.get("phone"), {responder.get("phone")})

    def _briefing_number(self) -> str:
        return check_destination(self.dispatch_sim_number, {self.dispatch_sim_number or ""})


class FakeTelephony(_Base):
    """Records calls instead of placing them. ``fail=True`` makes every call raise (Twilio down)."""

    def __init__(self, dispatch_sim_number: str | None = "+15550001111", fail: bool = False) -> None:
        super().__init__(dispatch_sim_number)
        self.calls: list[dict[str, Any]] = []
        self.hangups: list[str] = []
        self.fail = fail
        self._ids = itertools.count(1)

    def _sid(self) -> str:
        return f"CAfake{next(self._ids):04d}"

    async def call_responder(self, dispatch: Mapping[str, Any], responder: Mapping[str, Any]) -> str:
        to = self._responder_number(responder)
        if self.fail:
            raise TelephonyError("fake telephony is down")
        sid = self._sid()
        self.calls.append({"kind": "responder", "to": to, "dispatch_id": dispatch.get("id"), "sid": sid})
        return sid

    async def call_briefing(self, incident_id: str) -> str:
        to = self._briefing_number()
        if self.fail:
            raise TelephonyError("fake telephony is down")
        sid = self._sid()
        self.calls.append({"kind": "briefing", "to": to, "incident_id": incident_id, "sid": sid})
        return sid

    async def hangup(self, call_sid: str) -> None:
        self.hangups.append(call_sid)


class TwilioTelephony(_Base):
    """Real calls. Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER, PUBLIC_BASE_URL.
    Not verified: there is no Twilio account yet."""

    def __init__(
        self,
        *,
        account_sid: str,
        auth_token: str,
        from_number: str,
        public_base_url: str,
        dispatch_sim_number: str | None,
        ring_timeout_s: int = 20,
    ) -> None:
        super().__init__(dispatch_sim_number)
        from twilio.rest import Client

        self.client = Client(account_sid, auth_token)
        self.from_number = from_number
        self.base = public_base_url.rstrip("/")
        self.ring_timeout_s = int(ring_timeout_s)

    async def _create(self, to: str, path: str) -> str:
        call = await asyncio.to_thread(
            self.client.calls.create,
            to=to,
            from_=self.from_number,
            url=f"{self.base}{path}",
            method="POST",
            timeout=self.ring_timeout_s,
        )
        return call.sid

    async def call_responder(self, dispatch: Mapping[str, Any], responder: Mapping[str, Any]) -> str:
        to = self._responder_number(responder)
        return await self._create(to, f"/twilio/voice/{dispatch['id']}")

    async def call_briefing(self, incident_id: str) -> str:
        to = self._briefing_number()
        return await self._create(to, f"/twilio/briefing/{incident_id}")

    async def hangup(self, call_sid: str) -> None:
        try:
            await asyncio.to_thread(self.client.calls(call_sid).update, status="completed")
        except Exception as exc:  # noqa: BLE001 - a call that already ended is fine
            log.info("hangup %s: %s", call_sid, exc)
