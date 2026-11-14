"""The signal inbox and the decision.

``await_signal`` is the only node that calls ``interrupt()``. It has no side effect before the
interrupt, so re-running it on resume is safe. The resumed signal is applied through the pure
reducer; its effects (cancel timers, hang up calls, stop the speaker) run here, once, and so
do the iMessage follow-ups (background tasks, never awaited).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from agent.live import reducer
from agent.live.persist import sync


def make(rt) -> dict[str, Any]:
    async def await_signal(state: dict) -> dict:
        signal = interrupt({"incident_id": state["incident_id"], "waiting": True})
        tr = reducer.apply_signal(state, signal)
        rt.last_transition[state["incident_id"]] = tr
        if not tr.applied:
            return {}
        await rt.run_effects(state, tr.effects)
        await sync(rt.store, state, tr.updates, tr.events)
        rt.imessage.after_signal(state, tr.updates)  # role follow-up / stand-down texts (background)
        return tr.updates

    async def classify(state: dict) -> dict:
        tr = reducer.classify(state)
        await sync(rt.store, state, tr.updates, tr.events)
        return tr.updates

    return {"await_signal": await_signal, "classify": classify}
