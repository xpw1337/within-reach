"""The iMessage side channel of the live response (docs/CONTRACTS.md, Photon 2.0).

Rules:

- A text never blocks or delays the graph, the speaker, a call or the 911 briefing. Every send is
  a background task (``rt.spawn``) with an overall budget; a failure is an ``imessage_failed``
  timeline event and nothing else.
- Texts are external actions: they go out only where the graph already decided to act (a wave
  dispatch, the staff alert, a role assignment, the 911 briefing). Nothing here decides anything.
- Destinations are the call allowlist (``io/messaging.py``): ``DISPATCH_SIM_NUMBER`` or a
  ``callable`` responder with ``consent_calls``. Emergency numbers raise before any request.
- Text uses the same facts as the call scripts (``api/twilio.py``) and the speaker templates:
  landmark, building, AED distance from ``distance_m`` plus the route directions. Nothing is
  estimated here.

Timeline events (actor ``photon``): ``imessage_sent`` {purpose, dispatch_id?, responder_id?, role?,
message_id}, ``imessage_failed`` {purpose, error, ...}, ``imessage_received`` {reply, dispatch_id,
responder_id}. ``purpose`` is ``alert``, ``staff_alert``, ``role``, ``stand_down`` or ``briefing``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from agent.io.telephony import EmergencyNumberError, TelephonyError
from agent.live.briefing import TYPE_PHRASES
from agent.live.playbooks import camera_context
from agent.live.responders import ROLE_ORDER, roles_filled
from agent.live.state import merge_state

log = logging.getLogger(__name__)

ACTOR = "photon"
BUDGET_S = 15.0  # whole send, including a first-time chat lookup (each HTTP request: 5 s)
# If the briefing call never reaches its end (unanswered, hung up early), the text still goes out.
# Approximation: ring timeout (20 s) plus the briefing spoken twice.
BRIEFING_TEXT_FALLBACK_S = 90.0
SEEN_EVENTS = 1000


# ---------------------------------------------------------------------------
# Message text (pure)
# ---------------------------------------------------------------------------


def _where(state: Mapping[str, Any]) -> str:
    landmark = (state.get("camera") or {}).get("landmark") or "the camera"
    building = (state.get("building") or {}).get("name")
    return f"{landmark} at {building}" if building else landmark


def aed_phrase(state: Mapping[str, Any]) -> str | None:
    """``{aed_distance} meters, {aed_directions}``, as in the speaker script and the call."""
    ctx = camera_context(state.get("camera") or {}, state.get("routes") or {})
    if ctx.get("aed_distance") and ctx.get("aed_directions"):
        return f"{ctx['aed_distance']} meters, {ctx['aed_directions']}"
    return None


def alert_text(state: Mapping[str, Any]) -> str:
    aed = aed_phrase(state)
    return (f"Emergency alert from Within Reach. Someone has collapsed by {_where(state)}. "
            "If you can help, you will either go to the person or bring the AED"
            + (f" ({aed})." if aed else ".") + " Reply 1 to help. Reply 2 if you can't.")


def staff_text(state: Mapping[str, Any]) -> str:
    phrase = TYPE_PHRASES.get(state.get("type") or "unknown", TYPE_PHRASES["unknown"])
    return (f"Within Reach staff alert. {phrase}, by {_where(state)}. Please go to them. "
            "Reply 1 if you are going, then HERE when you arrive.")


def role_text(role: str, state: Mapping[str, Any]) -> str:
    landmark = (state.get("camera") or {}).get("landmark") or "the camera"
    building = state.get("building") or {}
    place = ", ".join(str(x) for x in (building.get("name"), building.get("address")) if x)
    floor = (state.get("camera") or {}).get("floor")
    at = "".join([f", floor {floor}" if floor is not None else "", f", {place}" if place else ""])
    if role == "patient":
        return (f"You are going to the person. Go to {landmark}{at}. Tap their shoulder and shout. "
                "If they don't respond and aren't breathing normally, call 911 on speaker and start CPR: "
                "push hard and fast in the center of the chest. Reply HERE when you arrive.")
    aed = aed_phrase(state)
    get = f"Get the AED: {aed}." if aed else "Get the AED."
    return (f"You are the AED runner. {get} Then bring it to {landmark}{at}. "
            "Reply HERE when you arrive with the AED.")


def stand_down_text(state_after: Mapping[str, Any]) -> str:
    if roles_filled(state_after.get("roles") or {}) and not state_after.get("resolved"):
        return "Two responders are already on the way. Thank you, you can stand down."
    return "This alert is no longer active. Thank you, you can stand down."


def briefing_text(spoken: str) -> str:
    return f"Within Reach 911 briefing (simulated dispatcher line). {spoken}"


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


class IMessage:
    """Per-runtime iMessage state: what was alerted, briefing texts, webhook ids already handled."""

    def __init__(self, rt: Any, messenger: Any = None) -> None:
        self.rt = rt
        self.messenger = messenger
        self.alerted: set[str] = set()  # dispatch ids that got an iMessage alert
        self.spoken: dict[str, str] = {}  # incident id -> briefing text as spoken on the call
        self.briefed: set[str] = set()  # incident ids whose briefing text went out
        self._seen: OrderedDict[str, None] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.messenger is not None

    def reset(self) -> None:
        self.alerted.clear()
        self.spoken.clear()
        self.briefed.clear()

    # -- plumbing ------------------------------------------------------------

    async def event(self, incident_id: str, kind: str, payload: dict[str, Any]) -> None:
        try:
            await self.rt.store.add_event(incident_id, ACTOR, kind, payload)
        except Exception as exc:  # noqa: BLE001 - the timeline is best effort here
            log.warning("imessage event %s failed: %s", kind, exc)

    def _spawn(self, incident_id: str, purpose: str, send: Callable[[], Awaitable[str]],
               dispatch: Mapping[str, Any] | None = None) -> None:
        base: dict[str, Any] = {"purpose": purpose}
        if dispatch is not None:
            base.update(dispatch_id=dispatch.get("id"), responder_id=dispatch.get("responder_id"))
            if dispatch.get("role"):
                base["role"] = dispatch["role"]

        async def run() -> None:
            try:
                message_id = await asyncio.wait_for(send(), BUDGET_S)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - recorded on the timeline, never retried here
                error = "timed out" if isinstance(exc, TimeoutError) else f"{type(exc).__name__}: {exc}"
                log.warning("iMessage %s failed: %s", purpose, error)
                await self.event(incident_id, "imessage_failed", {**base, "error": error})
                return
            await self.event(incident_id, "imessage_sent", {**base, "message_id": message_id})

        self.rt.spawn(run(), incident_id)

    def _allowed(self, responder: Mapping[str, Any]) -> bool:
        try:
            self.messenger.responder_number(responder)
        except EmergencyNumberError:
            log.warning("refusing to text responder %s: emergency number", responder.get("id"))
            return False
        except TelephonyError:
            return False
        return True

    def _text_responder(self, incident_id: str, purpose: str, dispatch: Mapping[str, Any],
                        responder: Mapping[str, Any], text: str) -> bool:
        if not self.enabled or not self._allowed(responder):
            return False
        key = f"within-reach-{purpose}-{dispatch['id']}"
        self._spawn(incident_id, purpose, lambda: self.messenger.text_responder(responder, text, key=key), dispatch)
        return True

    # -- hooks called by graph nodes and webhooks ----------------------------

    def alert(self, state: Mapping[str, Any], dispatch: Mapping[str, Any], responder: Mapping[str, Any],
              *, staff: bool = False) -> bool:
        """The iMessage alert next to the app alert (and the call). True when a text is on its way."""
        purpose = "staff_alert" if staff else "alert"
        text = staff_text(state) if staff else alert_text(state)
        sent = self._text_responder(state["incident_id"], purpose, dispatch, responder, text)
        if sent:
            self.alerted.add(dispatch["id"])
        return sent

    def after_signal(self, state: Mapping[str, Any], updates: Mapping[str, Any]) -> None:
        """After the reducer applied a signal: a role was assigned -> the role and route follow-up;
        a texted dispatch was released -> a stand-down text."""
        if not self.enabled:
            return
        rows = updates.get("dispatches") or []
        if not rows:
            return
        after = merge_state(dict(state), dict(updates))
        by_id = {d["id"]: d for d in after.get("dispatches") or []}
        for row in rows:
            d = by_id.get(row["id"]) or row
            if row.get("status") == "accepted" and row.get("role") in ROLE_ORDER:
                self.rt.spawn(self._to_responder(after, d, "role", role_text(row["role"], after)),
                              state["incident_id"])
            elif row.get("status") == "released" and row["id"] in self.alerted:
                self.rt.spawn(self._to_responder(after, d, "stand_down", stand_down_text(after)),
                              state["incident_id"])

    async def _to_responder(self, state: Mapping[str, Any], dispatch: Mapping[str, Any], purpose: str,
                            text: str) -> None:
        try:
            everyone = await self.rt.store.list_responders()
        except Exception as exc:  # noqa: BLE001
            log.warning("iMessage %s: responder lookup failed: %s", purpose, exc)
            return
        responder = next((r for r in everyone if r.get("id") == dispatch.get("responder_id")), None)
        if responder is not None:
            self._text_responder(state["incident_id"], purpose, dispatch, responder, text)

    def briefing_placed(self, state: Mapping[str, Any], text: str, *, call_placed: bool) -> None:
        """After ``brief_911`` placed (or failed to place) the call. With a ringing call the text
        follows the spoken briefing (``briefing_spoken``, from the TwiML), with a fallback timer;
        with no call it goes out now."""
        if not self.enabled:
            return
        incident_id = state["incident_id"]
        self.spoken.setdefault(incident_id, text)
        if not call_placed or not getattr(self.rt.telephony, "rings", True):
            self.briefing_spoken(incident_id)
            return

        async def fallback() -> None:
            await self.rt.clock.sleep(BRIEFING_TEXT_FALLBACK_S)
            self.briefing_spoken(incident_id)

        self.rt.spawn(fallback(), incident_id)

    def briefing_said(self, incident_id: str, text: str) -> None:
        """The TwiML for the briefing call was built: keep the exact words being spoken."""
        if self.enabled:
            self.spoken[incident_id] = text

    def briefing_spoken(self, incident_id: str) -> None:
        """Send the briefing text to ``DISPATCH_SIM_NUMBER``, once per incident."""
        if not self.enabled or incident_id in self.briefed or incident_id not in self.spoken:
            return
        self.briefed.add(incident_id)
        text = briefing_text(self.spoken[incident_id])
        key = f"within-reach-briefing-{incident_id}"
        self._spawn(incident_id, "briefing", lambda: self.messenger.text_dispatch(text, key=key))

    # -- inbound -------------------------------------------------------------

    def remember(self, handle: str | None, space_id: str | None, sender_id: str | None) -> None:
        if self.enabled and handle and space_id and sender_id:
            self.messenger.remember(handle, space_id, sender_id)

    def seen(self, event_id: str) -> bool:
        return event_id in self._seen

    def mark_seen(self, event_id: str) -> None:
        self._seen[event_id] = None
        while len(self._seen) > SEEN_EVENTS:
            self._seen.popitem(last=False)
