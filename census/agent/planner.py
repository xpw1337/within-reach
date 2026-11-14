"""The census Deep Agent: a planner with a visible todo list and five subagents (spec section 9.2).

Built with ``deepagents.create_deep_agent`` (0.7.x). That version no longer adds the todo tool by
default, so ``TodoListMiddleware`` (LangChain's ``write_todos``) is passed explicitly. A small
middleware mirrors every ``write_todos`` call into ``agent_events(kind='todo')`` with the full list,
and every ``task`` delegation into a planner ``decision`` (docs/CONTRACTS.md section 3).
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware
from langchain_core.messages import HumanMessage

from census.agent import prompts
from census.agent.subagents import as_tool, build_subagents
from census.tools import budget, db
from census.tools.context import ToolContext, use_context
from census.tools.events import decision, todo, warning
from census.tools.records import is_fixture

log = logging.getLogger(__name__)

AGENT = "planner"
DONE_STATUSES = ("fixed",)
TODO_STATUS = {"pending": "pending", "in_progress": "in_progress", "completed": "done"}


# ---------------------------------------------------------------------------
# Planner tools (coarse; fine-grained tools belong to the subagents)
# ---------------------------------------------------------------------------


def list_candidate_buildings(city: str | None = None, types: list[str] | None = None, limit: int = 20) -> list[dict]:
    """Buildings not yet finished, highest priority (estimated occupant load) first."""
    filters: list[tuple[str, str, Any]] = []
    if city:
        filters.append(("eq", "city", city))
    rows = db.fetch_all("buildings", columns="id,name,property_type,city,census_status,occupancy_est,"
                        "priority_score,costar_property_id", filters=filters)
    if types:
        wanted = [t.lower() for t in types]
        rows = [r for r in rows if any(w in (r.get("property_type") or "").lower() for w in wanted)]
    rows = [r for r in rows if r.get("census_status") not in DONE_STATUSES]
    rows.sort(key=lambda r: (r.get("priority_score") is None, -(r.get("priority_score") or 0), r["id"]))
    return [{k: r.get(k) for k in ("id", "name", "property_type", "city", "census_status", "occupancy_est")}
            for r in rows[:limit]]


def _load_bulk() -> Any:
    """Agent 1's census/tools/bulk.py, or None while it is not installed (tests pin this)."""
    try:
        return importlib.import_module("census.tools.bulk")
    except ImportError:
        return None


def scan_building_bulk(building_id: str) -> dict:
    """Tile every panorama and run the first-pass detector for one building (bulk worker pool).
    Refuses when the run's budget is spent."""
    if budget.budget_exhausted():
        warning(AGENT, "budget_exhausted", "Budget used up, so no new buildings will be scanned.",
                building_id)
        return {"refused": "budget exhausted"}
    bulk = _load_bulk()
    if bulk is None:
        warning(AGENT, "scanner_unavailable",
                "The bulk scanner is not installed here, so this building uses the equipment already pinned.",
                building_id)
        return {"skipped": "bulk scanner not available; using assets already pinned"}
    db.set_building(building_id, census_status="scanning")
    return bulk.scan_building_bulk(building_id)


def get_building_summary(building_id: str) -> dict:
    """Status, score, fix and document kinds for one building."""
    b = db.load_building(building_id)
    if b is None:
        return {"error": "building not found"}
    score = db.fetch_one("building_scores", filters=[("eq", "building_id", building_id)])
    fixes = db.fetch_all("fixes", columns="asset_type,sweep_id,before_worst_s,after_worst_s,before_red_frac,"
                         "after_red_frac", filters=[("eq", "building_id", building_id)])
    docs = db.fetch_all("documents", columns="kind", filters=[("eq", "building_id", building_id)])
    return {
        "name": b.get("name"), "census_status": b.get("census_status"),
        "occupancy_est": b.get("occupancy_est"), "ems_door": (b.get("ems_door") or {}).get("desc"),
        "score": score and {k: score.get(k) for k in ("worst_gap", "aed_red_frac", "ext_red_frac",
                                                      "exit_red_frac", "people_at_risk", "stairs_only",
                                                      "blocked_exits")},
        "fixes": fixes, "documents": sorted(d["kind"] for d in docs),
    }


def get_run_status() -> dict:
    """Progress and spend for the current run."""
    from census.tools.context import ctx

    run_id = ctx().run_id
    row = db.fetch_one("runs", filters=[("eq", "id", run_id)]) if run_id else None
    return {"run": row and {k: row.get(k) for k in ("status", "buildings_target", "buildings_done",
                                                     "est_cost_usd")},
            "budget_remaining_usd": budget.budget_remaining(run_id)}


PLANNER_TOOLS = (list_candidate_buildings, scan_building_bulk, get_building_summary, get_run_status)


# ---------------------------------------------------------------------------
# Console mirroring
# ---------------------------------------------------------------------------


class ConsoleMirror(AgentMiddleware):
    """Writes the planner's todo list and delegations to agent_events as they happen."""

    def __init__(self, context: ToolContext) -> None:
        super().__init__()
        self.context = context

    def _mirror(self, call: dict) -> None:
        name, args = call.get("name"), call.get("args") or {}
        with use_context(self.context):
            if name == "write_todos":
                items = [{"text": t.get("content", ""), "status": TODO_STATUS.get(t.get("status"), "pending")}
                         for t in args.get("todos") or []]
                done = sum(1 for t in items if t["status"] == "done")
                now = next((t["text"] for t in items if t["status"] == "in_progress"), None)
                message = f"Plan updated: {done} of {len(items)} steps done" + (f"; now: {now}." if now else ".")
                todo(AGENT, message, items)
            elif name == "task":
                who = args.get("subagent_type", "a subagent")
                text = " ".join(str(args.get("description", "")).split())
                decision(AGENT, f"Handing work to {who}: {text[:200]}", text[:1000], None,
                         options=[who])

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        try:
            self._mirror(request.tool_call)
        except Exception as exc:  # noqa: BLE001 - console mirroring must never break the agent
            log.warning("console mirror failed: %s", exc)
        return handler(request)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        try:
            self._mirror(request.tool_call)
        except Exception as exc:  # noqa: BLE001
            log.warning("console mirror failed: %s", exc)
        return await handler(request)


# ---------------------------------------------------------------------------
# Construction and invocation
# ---------------------------------------------------------------------------


def build_planner(context: ToolContext, model: Any = None) -> Any:
    """The compiled Deep Agent for one run. ``model`` defaults to the reasoning tier, metered to
    the run through shared.llm.get_chat_model."""
    from deepagents import create_deep_agent

    if model is None:
        from shared.llm import get_chat_model

        model = get_chat_model("reasoning", run_id=context.run_id)
    budget_text = f"${context.budget_usd:.2f}" if context.budget_usd is not None else "not set"
    return create_deep_agent(
        model=model,
        tools=[as_tool(f, context) for f in PLANNER_TOOLS],
        system_prompt=prompts.PLANNER.format(budget=budget_text, run_id=context.run_id or "--"),
        subagents=build_subagents(context),
        middleware=[TodoListMiddleware(), ConsoleMirror(context)],
        name="census-planner",
    )


def run_buildings(building_ids: list[str], context: ToolContext, model: Any = None,
                  recursion_limit: int | None = None) -> str:
    """Let the planner work through ``building_ids`` (already in scan order). Returns its final text."""
    with use_context(context):
        rows = {b["id"]: b for b in db.fetch_by_ids("buildings", building_ids)}
        listing = "\n".join(
            f"- {bid}: {rows.get(bid, {}).get('name') or 'unnamed'} "
            f"({rows.get(bid, {}).get('property_type') or 'unknown type'})"
            + (" [demo fixture]" if is_fixture(rows.get(bid, {})) else "")
            for bid in building_ids)
        decision(AGENT, f"Starting {len(building_ids)} building{'s' if len(building_ids) != 1 else ''} "
                        "in ranked order.", "highest estimated occupant load first", None,
                 options=building_ids[:20])
    agent = build_planner(context, model)
    limit = recursion_limit or 60 + 60 * len(building_ids)
    out = agent.invoke({"messages": [HumanMessage(f"Run the census on these buildings, in order:\n{listing}")]},
                       config={"recursion_limit": limit})
    messages = out.get("messages") or []
    final = messages[-1].content if messages else ""
    return final if isinstance(final, str) else str(final)
