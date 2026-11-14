"""iMessage through Photon 2.0 (REST API), behind the same destination allowlist as calls.

Only two kinds of destination exist, exactly as for ``io/telephony.py``:

- ``DISPATCH_SIM_NUMBER`` (a teammate's phone, never a real emergency number);
- the phone of a responder who is ``callable`` and gave ``consent_calls``.

Emergency numbers (911, 112, 999 and the others in ``telephony.EMERGENCY_CODES``) raise
``EmergencyNumberError`` before any network request. ``FakeMessenger`` applies the same checks.

How a send works on Photon (OpenAPI at https://api.photon.codes, Beta docs):

1. ``POST /v1/projects/{id}/messages`` needs a ``spaceId`` (a direct iMessage chat) and a
   ``senderId`` (our line's agent User), plus an ``Idempotency-Key`` header.
2. The project is on shared iMessage lines: each person gets an Assignment that maps their phone
   to an assigned line number, and a shared line can only reply in a chat the person started.
   So every responder and the sim-911 phone text the line once during setup (agent/README.md).
3. The space for a phone comes from an inbound ``message.received`` webhook (``space.id`` and
   ``receivedBy.id``, cached by ``remember``), or is looked up: the person's Assignment gives the
   line number, ``POST /users`` gives both User IDs, ``POST /spaces`` returns the existing chat.

Every request has a hard timeout; callers add an overall budget and never await a send on the
live path (``agent/live/imessage.py``).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import re
from collections.abc import Mapping
from typing import Any, Protocol

import httpx

from agent.io.telephony import (
    DestinationNotAllowedError,
    EmergencyNumberError,
    TelephonyError,
    check_destination,
    is_emergency_number,
    normalize,
    responder_allowed,
)

log = logging.getLogger(__name__)

API_BASE = "https://api.photon.codes"
PLATFORM = "imessage"
MAX_TEXT = 2000
PROJECT_ID = re.compile(r"^pho_prj_[0-7][0-9a-hjkmnp-tv-z]{25}$")
SPACE_ID = re.compile(r"^pho_spc_[0-7][0-9a-hjkmnp-tv-z]{25}$")
USER_ID = re.compile(r"^pho_usr_[0-7][0-9a-hjkmnp-tv-z]{25}$")
IDEMPOTENCY_KEY = re.compile(r"^[\x21-\x7e]{1,255}$")

__all__ = [
    "DestinationNotAllowedError",
    "EmergencyNumberError",
    "FakeMessenger",
    "MessagingError",
    "Messenger",
    "PhotonMessenger",
]


class MessagingError(TelephonyError):
    """A send failed (network, timeout, Photon error). Never raised for an allowlist refusal."""


class Messenger(Protocol):
    def responder_number(self, responder: Mapping[str, Any]) -> str: ...
    async def text_responder(self, responder: Mapping[str, Any], text: str, *, key: str) -> str: ...
    async def text_dispatch(self, text: str, *, key: str) -> str: ...
    def remember(self, handle: str, space_id: str, sender_id: str) -> None: ...
    async def aclose(self) -> None: ...


class _Base:
    def __init__(self, dispatch_sim_number: str | None) -> None:
        if dispatch_sim_number and is_emergency_number(dispatch_sim_number):
            raise EmergencyNumberError("DISPATCH_SIM_NUMBER is an emergency number; refusing to start")
        self.dispatch_sim_number = dispatch_sim_number

    def responder_number(self, responder: Mapping[str, Any]) -> str:
        """The allowlisted number for a responder; raises like ``telephony._Base``."""
        if not responder_allowed(responder):
            raise DestinationNotAllowedError("responder is not callable or did not consent to calls")
        return check_destination(responder.get("phone"), {responder.get("phone")})

    def dispatch_number(self) -> str:
        return check_destination(self.dispatch_sim_number, {self.dispatch_sim_number or ""})

    async def text_responder(self, responder: Mapping[str, Any], text: str, *, key: str) -> str:
        return await self._send(self.responder_number(responder), _clean(text), _key(key))

    async def text_dispatch(self, text: str, *, key: str) -> str:
        return await self._send(self.dispatch_number(), _clean(text), _key(key))

    async def _send(self, to: str, text: str, key: str) -> str:  # pragma: no cover - abstract
        raise NotImplementedError

    def remember(self, handle: str, space_id: str, sender_id: str) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _clean(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise MessagingError("empty message")
    return text[:MAX_TEXT]


def _key(key: str) -> str:
    if not IDEMPOTENCY_KEY.match(key or ""):
        raise MessagingError("idempotency key must be 1 to 255 visible ASCII characters")
    return key


class FakeMessenger(_Base):
    """Records texts instead of sending them. ``fail=True`` makes every send raise; ``hang=True``
    makes every send wait forever (a stuck network), to prove nothing waits for it."""

    def __init__(self, dispatch_sim_number: str | None = "+15550001111", *, fail: bool = False,
                 hang: bool = False) -> None:
        super().__init__(dispatch_sim_number)
        self.sent: list[dict[str, Any]] = []
        self.remembered: dict[str, tuple[str, str]] = {}
        self.fail = fail
        self.hang = hang
        self._ids = itertools.count(1)

    async def _send(self, to: str, text: str, key: str) -> str:
        if self.hang:
            await asyncio.Event().wait()
        if self.fail:
            raise MessagingError("fake messaging is down")
        for previous in self.sent:  # Photon replays a reused Idempotency-Key instead of sending again
            if previous["key"] == key:
                return previous["id"]
        message_id = f"pho_msg_fake{next(self._ids):04d}"
        self.sent.append({"to": to, "text": text, "key": key, "id": message_id})
        return message_id

    def remember(self, handle: str, space_id: str, sender_id: str) -> None:
        self.remembered[normalize(handle)] = (space_id, sender_id)

    def texts_to(self, number: str) -> list[str]:
        return [m["text"] for m in self.sent if m["to"] == normalize(number)]


class PhotonMessenger(_Base):
    """Photon 2.0 REST client for iMessage (shared lines). Not verified end to end: no message was
    sent while building it (read-only checks only, see agent/README.md)."""

    def __init__(self, *, api_key: str, project_id: str, dispatch_sim_number: str | None,
                 base_url: str = API_BASE, timeout_s: float = 5.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(dispatch_sim_number)
        if not PROJECT_ID.match(project_id or ""):
            raise MessagingError("PHOTON_PROJECT_ID is not a Photon project id (pho_prj_...)")
        if not api_key:
            raise MessagingError("PHOTON_API_KEY is empty")
        self.project_id = project_id
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=httpx.Timeout(timeout_s), transport=transport,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        self._spaces: dict[str, tuple[str, str]] = {}  # E.164 -> (space id, our sender user id)

    async def aclose(self) -> None:
        await self._http.aclose()

    def remember(self, handle: str, space_id: str, sender_id: str) -> None:
        """Cache the chat from an inbound message (``space.id``, ``receivedBy.id``)."""
        number = normalize(handle or "")
        if number and SPACE_ID.match(space_id or "") and USER_ID.match(sender_id or ""):
            self._spaces[number] = (space_id, sender_id)

    async def _request(self, method: str, path: str, *, json: Any = None, params: Any = None,
                       key: str | None = None) -> dict[str, Any]:
        headers = {"Idempotency-Key": key} if key else None
        try:
            r = await self._http.request(method, f"/v1/projects/{self.project_id}{path}", json=json,
                                         params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise MessagingError(f"Photon {method} {path.split('?')[0]}: {type(exc).__name__}") from None
        if r.status_code >= 400:
            code = None
            try:
                code = (r.json() or {}).get("code")
            except ValueError:
                pass
            # status and problem code only: problem details can echo phone numbers
            raise MessagingError(f"Photon {method} {path}: HTTP {r.status_code} {code or ''}".strip())
        try:
            body = r.json()
        except ValueError:
            raise MessagingError(f"Photon {method} {path}: response is not JSON") from None
        if not isinstance(body, dict):
            raise MessagingError(f"Photon {method} {path}: unexpected response")
        return body

    async def _assigned_line(self, number: str) -> str:
        """The shared line number assigned to this phone (``GET .../imessage/assignments``)."""
        token = None
        for _ in range(20):  # 200 per page; the plan caps seats far below this
            params = {"pageSize": 200, **({"pageToken": token} if token else {})}
            page = await self._request("GET", "/platforms/imessage/assignments", params=params)
            for a in page.get("assignments") or []:
                if a.get("releasedAt") or not a.get("assignedPhoneNumber"):
                    continue
                if normalize(str(a.get("handle") or "")) == number:
                    return str(a["assignedPhoneNumber"])
            token = page.get("nextPageToken")
            if not token:
                break
        raise MessagingError("no active shared iMessage line assignment for this destination")

    async def _user(self, handle: str) -> str:
        user = await self._request("POST", "/users", json={"handle": handle, "platform": PLATFORM})
        if not USER_ID.match(str(user.get("id") or "")):
            raise MessagingError("Photon returned no user id")
        return user["id"]

    async def _space(self, number: str) -> tuple[str, str]:
        if number in self._spaces:
            return self._spaces[number]
        line = await self._assigned_line(number)
        agent = await self._user(line)
        human = await self._user(number)
        # iMessage: the first participant is our line (creator); an existing chat is reused.
        space = await self._request("POST", "/spaces", json={"participantIds": [agent, human], "platform": PLATFORM},
                                    key=f"within-reach-space-{agent}-{human}")
        if not SPACE_ID.match(str(space.get("id") or "")):
            raise MessagingError("Photon returned no space id")
        self._spaces[number] = (space["id"], agent)
        return self._spaces[number]

    async def _send(self, to: str, text: str, key: str) -> str:
        space_id, sender_id = await self._space(to)
        body = {"spaceId": space_id, "senderId": sender_id,
                "content": {"type": "text", "format": "plain", "text": text}}
        try:
            sent = await self._request("POST", "/messages", json=body, key=key)
        except MessagingError:
            self._spaces.pop(to, None)  # a stale chat is looked up again next time
            raise
        return str(sent.get("id") or "")
