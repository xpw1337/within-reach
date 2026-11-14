"""Event emitters for the census console (``agent_events``) and the live timeline (``incident_events``).

An event write must never break a census step or the live path: every failure is logged and
swallowed. ``emit_incident_event`` does not block the live hot path: called from a thread that runs
an asyncio event loop it hands the insert to a background worker and returns at once.

Allowed values (docs/CONTRACTS.md section 3) are checked and logged when unknown, but the row is
still written so nothing is lost.
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any

from shared import db

log = logging.getLogger(__name__)

AGENT_NAMES = frozenset({"planner", "records", "scanner", "mapper", "outside", "fixer"})
AGENT_EVENT_KINDS = frozenset({"todo", "decision", "tool_call", "result", "warning"})
INCIDENT_EVENT_KINDS = frozenset(
    {
        "detected",
        "speak",
        "verify_result",
        "confirm_requested",
        "confirmed",
        "false_alarm",
        "voice_check_result",
        "classified",
        "gate_opened",
        "dispatch_sent",
        "dispatch_accepted",
        "dispatch_declined",
        "dispatch_timeout",
        "dispatch_released",
        "responder_arrived",
        "ems_briefed",
        "police_notified",
        "staff_alerted",
        "milestone",
        "fall_911_cancelled",
        "timer_started",
        "timer_fired",
        "resolved",
    }
)
INCIDENT_ACTORS = frozenset({"vision", "system", "desk", "twilio", "llm"})  # plus "responder:<id>"

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="events")
_pending: set[Future] = set()


def _insert(table: str, row: dict[str, Any]) -> None:
    try:
        db.insert(table, row)
    except Exception as exc:  # noqa: BLE001 - events must never raise
        log.warning("event write to %s failed (%s): %s", table, type(exc).__name__, exc)


def emit_agent_event(
    run_id: str | None,
    agent: str,
    kind: str,
    message: str,
    building_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Write one ``agent_events`` row. ``message`` is a complete sentence; the console shows it as is."""
    if agent not in AGENT_NAMES:
        log.warning("unknown agent_events.agent %r", agent)
    if kind not in AGENT_EVENT_KINDS:
        log.warning("unknown agent_events.kind %r", kind)
    _insert(
        "agent_events",
        {
            "run_id": run_id,
            "agent": agent,
            "kind": kind,
            "building_id": building_id,
            "message": message,
            "payload": payload or {},
        },
    )


def _in_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def emit_incident_event(
    incident_id: str, actor: str, kind: str, payload: dict[str, Any] | None = None
) -> None:
    """Write one ``incident_events`` row; fire-and-forget when called from async code."""
    if kind not in INCIDENT_EVENT_KINDS:
        log.warning("unknown incident_events.kind %r", kind)
    if actor not in INCIDENT_ACTORS and not actor.startswith("responder:"):
        log.warning("unknown incident_events.actor %r", actor)
    row = {"incident_id": incident_id, "actor": actor, "kind": kind, "payload": payload or {}}
    if _in_event_loop():
        try:
            fut = _executor.submit(_insert, "incident_events", row)
        except RuntimeError as exc:  # executor shut down at interpreter exit
            log.warning("incident event dropped: %s", exc)
            return
        _pending.add(fut)
        fut.add_done_callback(_pending.discard)
    else:
        _insert("incident_events", row)


def flush_events(timeout: float | None = 5.0) -> None:
    """Wait for background event writes (tests and shutdown)."""
    if _pending:
        wait(list(_pending), timeout=timeout)
