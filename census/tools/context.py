"""Everything a census tool needs from the outside world, in one injectable object.

Tools never import ``shared.db`` / ``shared.events`` / ``shared.llm`` directly. They call
``ctx()`` and use the handles on it. In production ``default_context()`` builds the handles from
``shared`` (docs/CONTRACTS.md section 4). Tests and the run loop install their own with
``use_context(...)``. The run id travels on the context too, so concurrent runs (the overnight
run and an on-stage rerun) never mix their console events.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ToolContext:
    db: Any  # supabase.Client, or a fake with the same table() builder API
    emit: Callable[..., None]  # shared.events.emit_agent_event(run_id, agent, kind, message, building_id, payload)
    limit_seconds: Callable[[str], float]  # shared.thresholds.limit_seconds: red limit, one-way seconds
    # shared.thresholds.display_seconds(asset_type, one_way_s): what a person reads (AED round trip)
    display_seconds: Callable[[str, float | None], float | None]
    walk_speed_mps: float
    complete_json: Callable[..., dict] | None = None  # shared.llm.complete_json
    get_adapter: Callable[[], Any] | None = None  # data.adapter.get_adapter
    run_id: str | None = None
    event_delay_s: float = 0.0  # demo pacing between console events (DEMO_EVENT_DELAY_MS)
    budget_usd: float | None = None


_override: contextvars.ContextVar[ToolContext | None] = contextvars.ContextVar("census_tool_ctx", default=None)
_default: ToolContext | None = None
_default_lock = threading.Lock()


def ctx() -> ToolContext:
    """The active context: the innermost ``use_context``, else the production default."""
    current = _override.get()
    if current is not None:
        return current
    return default_context()


@contextlib.contextmanager
def use_context(context: ToolContext) -> Iterator[ToolContext]:
    token = _override.set(context)
    try:
        yield context
    finally:
        _override.reset(token)


def with_changes(**changes: Any) -> ToolContext:
    """A copy of the active context with some fields replaced (for example ``run_id``)."""
    return replace(ctx(), **changes)


def default_context() -> ToolContext:
    """Production handles from ``shared`` and ``data``. Built once, lazily, so importing a tool
    never needs credentials."""
    global _default
    if _default is None:
        with _default_lock:
            if _default is None:
                _default = _build_default()
    return _default


class _SharedDB:
    """Resolves ``shared.db.get_db()`` on every use, so ``shared.db.set_db(fake)`` applies too."""

    def table(self, name: str) -> Any:
        from shared.db import get_db

        return get_db().table(name)


def _build_default() -> ToolContext:
    from shared import thresholds
    from shared.config import get_settings
    from shared.events import emit_agent_event

    settings = get_settings()

    def complete_json(**kwargs: Any) -> dict:
        from shared.llm import complete_json as _complete_json

        return _complete_json(**kwargs)

    def get_adapter() -> Any:
        from data.adapter import get_adapter as _get_adapter

        return _get_adapter()

    return ToolContext(
        db=_SharedDB(),
        emit=emit_agent_event,
        limit_seconds=thresholds.limit_seconds,
        display_seconds=thresholds.display_seconds,
        walk_speed_mps=float(settings.walk_speed_mps),
        complete_json=complete_json,
        get_adapter=get_adapter,
        event_delay_s=float(settings.demo_event_delay_ms) / 1000.0,
        budget_usd=float(settings.census_budget_usd),
    )
