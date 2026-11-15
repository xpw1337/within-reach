"""The 911 agent: an AI caller that reports the emergency to a SIMULATED dispatcher.

Nothing here dials a phone. The dispatcher side is a scripted simulator that asks the standard
911 call-taker questions; the caller side answers each one from the live incident facts, with
Claude when a model is configured (``shared.llm``) and from a fact template otherwise. Every line
is pushed to the dashboard as it happens, and the call sends short updates when the situation
changes (responder accepted, arrived, fire).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

SYSTEM = (
    "You are an automated emergency-reporting agent for a building safety system. You are on a "
    "SIMULATED call with a 911 dispatcher (a training simulator, not a real call). Answer the "
    "dispatcher's question in one or two short spoken sentences, using ONLY the facts given. "
    "Never invent details. A camera cannot tell whether someone is breathing: say so when asked. "
    "Give the address first when asked where. Plain speech, no lists, no markdown."
)
SCHEMA = {"type": "object", "properties": {"say": {"type": "string"}}, "required": ["say"],
          "additionalProperties": False}

FALL_QUESTIONS = [
    ("address", "911, what is the address of your emergency?"),
    ("what", "Okay. Tell me exactly what happened."),
    ("breathing", "Is the person awake? Are they breathing?"),
    ("help", "Is anyone with them right now?"),
    ("aed", "Is there an AED nearby?"),
]
FIRE_QUESTIONS = [
    ("address", "911, what is the address of your emergency?"),
    ("what", "Tell me what you're seeing."),
    ("trapped", "Is anyone hurt or trapped?"),
    ("help", "Is anyone on scene?"),
]
CLOSING = "Okay. I'm sending units to that location now. Stay on the line and tell me if anything changes."

Facts = Callable[[], dict[str, Any]]
Emit = Callable[[str, str], Awaitable[None]]


def template_answer(topic: str, f: dict[str, Any]) -> str:
    where = f.get("address") or f.get("coords") or "the location on file"
    spot = f" at {f['place']}" if f.get("place") else ""
    if topic == "address":
        return f"The emergency is at {where}{spot}."
    if topic == "what":
        if f.get("kind") == "fire":
            return f"Our camera detected {f.get('fire_label') or 'fire'}{spot} at {f.get('time')}."
        how = "a person suddenly fall" if f.get("witnessed") else "a person down on the floor"
        extra = " There is also a fire reported nearby." if f.get("fire") else ""
        return f"Our camera saw {how}{spot} at {f.get('time')}. They have not gotten up.{extra}"
    if topic == "breathing":
        if f.get("responsive"):
            return "The camera saw them raise a hand, so they may be responsive. A camera can't confirm breathing."
        return "They are not moving on camera. A camera can't tell if they're breathing, so treat it as possible cardiac arrest."
    if topic == "trapped":
        return "The camera can't confirm that. " + ("A person is down near the fire." if f.get("kind") == "fall"
                                                    else "No one is seen down on camera.")
    if topic == "help":
        return _responder_sentence(f)
    if topic == "aed":
        a = f.get("aed")
        if a:
            return f"Yes, the nearest mapped AED is about {a['distance_m']} meters away, {a['label']}."
        return "No AED is mapped near this location."
    return "I don't have that information."


def _responder_sentence(f: dict[str, Any]) -> str:
    r = f.get("responder")
    if not r:
        if f.get("alerting"):
            return f"We're alerting the nearest trained volunteer now: {f['alerting']}."
        return "No volunteer has been reached yet."
    if r.get("status") == "on_scene":
        return f"Yes, a trained volunteer, {r['name']}, is with them now."
    dist = f", about {r['distance_m']} meters away" if r.get("distance_m") is not None else ""
    return f"A trained volunteer, {r['name']}, accepted and is on the way{dist}."


class Call911:
    def __init__(self, facts: Facts, emit: Emit, *, use_llm: bool = True, pace_s: float = 1.6,
                 llm_timeout_s: float = 6.0):
        self.facts = facts
        self.emit = emit
        self.use_llm = use_llm
        self.pace_s = pace_s
        self.llm_timeout_s = llm_timeout_s
        self._updates: asyncio.Queue[str] = asyncio.Queue()
        self.ended = False

    async def answer(self, topic: str, question: str) -> str:
        f = self.facts()
        fallback = template_answer(topic, f)
        if not self.use_llm:
            return fallback
        try:
            from shared import llm

            facts_text = "\n".join(f"- {k}: {v}" for k, v in f.items() if v not in (None, "", [], {}))
            out = await asyncio.wait_for(llm.acomplete_json(
                tier="fast", system=SYSTEM, max_tokens=400,
                user=[llm.text_part(f"Facts:\n{facts_text}\n\nDispatcher: {question}")], schema=SCHEMA,
            ), timeout=self.llm_timeout_s)
            say = str(out.get("say") or "").strip()
            return say or fallback
        except Exception as exc:  # noqa: BLE001 - the template always works
            log.info("911 agent answering from template (%s)", type(exc).__name__)
            self.use_llm = False  # don't wait on a dead model for every line
            return fallback

    def update(self, text: str) -> None:
        """Queue a situation update for the dispatcher."""
        if not self.ended:
            self._updates.put_nowait(text)

    async def run(self) -> None:
        await self.emit("system", "SIMULATED 911 call: no real emergency number is dialed.")
        await asyncio.sleep(self.pace_s)
        await self.emit("system", "Connected to simulated dispatcher.")
        questions = FIRE_QUESTIONS if self.facts().get("kind") == "fire" else FALL_QUESTIONS
        for topic, q in questions:
            await asyncio.sleep(self.pace_s * 0.6)
            await self.emit("dispatcher", q)
            await self.emit("ai", await self.answer(topic, q))
        await asyncio.sleep(self.pace_s * 0.6)
        await self.emit("dispatcher", CLOSING)
        while not self.ended:
            text = await self._updates.get()
            if self.ended:
                break
            await asyncio.sleep(self.pace_s * 0.4)
            await self.emit("ai", text)
            await asyncio.sleep(self.pace_s * 0.6)
            await self.emit("dispatcher", "Copy that. Units are still on the way.")

    async def end(self, reason: str) -> None:
        if self.ended:
            return
        self.ended = True
        self._updates.put_nowait("")
        await self.emit("system", f"Call ended: {reason}.")
