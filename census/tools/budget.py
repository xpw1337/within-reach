"""Budget guard for a census run (spec section 9.2). The code check is the real guard; the
planner is told the budget too, but it cannot spend past this.

``runs.est_cost_usd`` is filled by shared.llm cost metering. The run's budget lives on the tool
context (``budget_usd``), set by census.run from ``start_run(..., budget_usd)``.
"""

from __future__ import annotations

from census.tools import db
from census.tools.context import ctx

WARN_FRACTION = 0.9  # console warning when this share of the budget is used (display choice)


def spent_usd(run_id: str | None) -> float:
    if not run_id:
        return 0.0
    row = db.fetch_one("runs", columns="id,est_cost_usd", filters=[("eq", "id", run_id)])
    return float((row or {}).get("est_cost_usd") or 0.0)


def budget_remaining(run_id: str | None = None) -> float | None:
    """Dollars left for the run, or None when the run has no budget."""
    c = ctx()
    run_id = run_id or c.run_id
    if c.budget_usd is None:
        return None
    return c.budget_usd - spent_usd(run_id)


def budget_exhausted(run_id: str | None = None) -> bool:
    left = budget_remaining(run_id)
    return left is not None and left <= 0
