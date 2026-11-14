"""Console events (``agent_events``) with the payload shapes from docs/CONTRACTS.md section 3,
and the display helpers for numbers a person reads in those messages.

Every ``message`` is a complete sentence: the console renders it directly. Numbers in messages are
measured values only. AED times shown to a person are round trip, converted by the thresholds
helper on the context, never inline (CONTRACTS section 1).
"""

from __future__ import annotations

import time
from typing import Any

from census.tools.context import ctx

GAP_NAMES = {"aed": "AED", "extinguisher": "extinguisher", "exit": "exit"}


def emit(agent: str, kind: str, message: str, building_id: str | None = None,
         payload: dict | None = None) -> None:
    c = ctx()
    c.emit(c.run_id, agent, kind, message, building_id=building_id, payload=payload or {})
    if c.event_delay_s > 0:
        time.sleep(c.event_delay_s)


def tool_call(agent: str, tool: str, args: dict[str, Any], building_id: str | None = None) -> None:
    shown = ", ".join(f"{k}={v}" for k, v in args.items() if k != "building_id")
    emit(agent, "tool_call", f"{tool}({shown})", building_id, {"tool": tool, "args": args})


def result(agent: str, tool: str, message: str, building_id: str | None = None,
           metrics: dict | None = None) -> None:
    payload: dict[str, Any] = {"tool": tool, "summary": message}
    if metrics is not None:
        payload["metrics"] = metrics
    emit(agent, "result", message, building_id, payload)


def decision(agent: str, message: str, reason: str, building_id: str | None = None, **extra: Any) -> None:
    emit(agent, "decision", message, building_id, {"reason": reason, **extra})


def warning(agent: str, code: str, message: str, building_id: str | None = None,
            detail: Any = None) -> None:
    emit(agent, "warning", message, building_id, {"code": code, "detail": detail if detail is not None else message})


def todo(agent: str, message: str, todos: list[dict], building_id: str | None = None) -> None:
    emit(agent, "todo", message, building_id, {"todos": todos})


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def display_seconds(asset_type: str, one_way_s: float | None) -> float | None:
    """The number of seconds a person should see: AED round trip, others one-way."""
    return ctx().display_seconds(asset_type, one_way_s)


def time_phrase(asset_type: str, one_way_s: float | None) -> str:
    shown = display_seconds(asset_type, one_way_s)
    if shown is None:
        return "--"
    unit = "s round trip" if asset_type == "aed" else "s one-way walk"
    return f"{round(shown)} {unit}"


def pct(frac: float | None) -> str:
    return "--" if frac is None else f"{round(frac * 100)}%"
