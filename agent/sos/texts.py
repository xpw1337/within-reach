"""Text messages (iMessage) to the alerted responder, through Photon's REST API.

Sent alongside the in-app alert so it reaches a phone whose app is closed. Configured with
``PHOTON_API_KEY`` and ``PHOTON_PROJECT_ID``; turn off with ``SOS_TEXTS=off``.

Photon's free plan uses shared iMessage lines: each phone is assigned a line, and a shared line can
only reply in a chat the person started. So each phone that should get texts must text its
assigned line once (from the Photon dashboard's iMessage page); until then a send fails with
``SHARED_LINE_INBOUND_REQUIRED`` and the hub says so on the timeline.

How a send works: the phone's Assignment gives its line number, ``POST /users`` turns both numbers
into Photon users, ``POST /spaces`` returns their existing chat, ``POST /messages`` sends.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from agent.sos.calls import is_emergency, normalize_phone

log = logging.getLogger(__name__)

API_BASE = "https://api.photon.codes"
PLATFORM = "imessage"


@dataclass
class TextResult:
    sent: bool
    id: str | None = None
    reason: str | None = None


class TextError(RuntimeError):
    pass


class Texter:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.api_key = os.environ.get("PHOTON_API_KEY", "").strip()
        self.project = os.environ.get("PHOTON_PROJECT_ID", "").strip()
        self.enabled = os.environ.get("SOS_TEXTS", "on").strip().lower() not in ("off", "0", "false", "no")
        self._client = client
        self._spaces: dict[str, tuple[str, str]] = {}  # E.164 -> (space id, our line's user id)

    @property
    def configured(self) -> bool:
        return self.enabled and bool(self.api_key and self.project.startswith("pho_prj_"))

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=API_BASE, timeout=8, headers={
                "Authorization": f"Bearer {self.api_key}", "Accept": "application/json"})
        return self._client

    async def _req(self, method: str, path: str, *, json: Any = None, params: Any = None,
                   key: str | None = None) -> dict[str, Any]:
        http = await self._http()
        r = await http.request(method, f"/v1/projects/{self.project}{path}", json=json, params=params,
                               headers={"Idempotency-Key": key} if key else None)
        if r.status_code >= 400:
            try:
                code = (r.json() or {}).get("code")
            except ValueError:
                code = None
            # Status and problem code only: Photon's problem details can echo phone numbers.
            raise TextError(f"Photon HTTP {r.status_code} {code or ''}".strip())
        body = r.json()
        if not isinstance(body, dict):
            raise TextError("Photon: unexpected response")
        return body

    async def _line_for(self, number: str) -> str:
        token = None
        for _ in range(20):
            page = await self._req("GET", "/platforms/imessage/assignments",
                                   params={"pageSize": 200, **({"pageToken": token} if token else {})})
            for a in page.get("assignments") or []:
                if a.get("releasedAt") or not a.get("assignedPhoneNumber"):
                    continue
                if normalize_phone(str(a.get("handle") or "")) == number:
                    return str(a["assignedPhoneNumber"])
            token = page.get("nextPageToken")
            if not token:
                break
        raise TextError("this phone has no Photon iMessage line assigned")

    async def _user(self, handle: str) -> str:
        user = await self._req("POST", "/users", json={"handle": handle, "platform": PLATFORM})
        if not str(user.get("id") or "").startswith("pho_usr_"):
            raise TextError("Photon returned no user id")
        return str(user["id"])

    async def _space(self, number: str) -> tuple[str, str]:
        if number in self._spaces:
            return self._spaces[number]
        line = await self._line_for(number)
        agent, human = await self._user(line), await self._user(number)
        space = await self._req("POST", "/spaces", json={"participantIds": [agent, human], "platform": PLATFORM},
                                key=f"within-reach-space-{agent}-{human}")
        if not str(space.get("id") or "").startswith("pho_spc_"):
            raise TextError("Photon returned no chat id")
        self._spaces[number] = (str(space["id"]), agent)
        return self._spaces[number]

    async def enable(self, to: str, first_name: str | None = None) -> dict[str, Any]:
        """Give this phone a shared iMessage line (uses one of the project's seats), or return the
        one it already has. The person must then text that line once before texts can reach them."""
        if not self.configured:
            raise TextError("texts not configured")
        number = normalize_phone(to)
        if not number or is_emergency(number):
            raise TextError("not a valid personal number")
        try:
            return {"line": await self._line_for(number), "new": False}
        except TextError:
            pass
        body: dict[str, Any] = {"handle": number}
        if first_name:
            body["firstName"] = first_name[:100]
        a = await self._req("POST", "/platforms/imessage/assignments", json=body,
                            key=f"within-reach-assign-{number.lstrip('+')}")
        line = str(a.get("assignedPhoneNumber") or "")
        if not line:
            raise TextError("Photon assigned no line")
        return {"line": line, "new": True}

    async def send(self, to: str, text: str, key: str) -> TextResult:
        if not self.configured:
            return TextResult(False, reason="texts not configured")
        number = normalize_phone(to)
        if not number or is_emergency(number):
            return TextResult(False, reason="refused: not a valid personal number")
        safe_key = re.sub(r"[^\x21-\x7e]", "", key)[:200] or "within-reach"
        try:
            space_id, sender = await self._space(number)
            sent = await self._req("POST", "/messages", key=safe_key, json={
                "spaceId": space_id, "senderId": sender,
                "content": {"type": "text", "format": "plain", "text": text.strip()[:1000]}})
            return TextResult(True, id=str(sent.get("id") or ""))
        except Exception as exc:  # noqa: BLE001 - the app alert still went out
            self._spaces.pop(number, None)
            return TextResult(False, reason=str(exc)[:160] if isinstance(exc, TextError) else type(exc).__name__)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
