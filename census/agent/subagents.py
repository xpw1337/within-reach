"""The five subagent definitions (spec section 9.2) and the tool wrapping they share.

Tool names follow the spec table. Every tool is wrapped so that it runs inside the run's tool
context (run id, DB, event sink) whatever thread LangGraph uses, returns JSON text, and turns an
exception into a console warning plus an error result the agent can react to.
"""

from __future__ import annotations

import functools
import importlib
import json
import logging
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from census.agent import prompts
from census.tools import fixer, mapper, outside, records
from census.tools.context import ToolContext, use_context
from census.tools.events import warning

log = logging.getLogger(__name__)

# Scanner tool names from the spec; the module is Agent 1's census/tools/scanner.py.
SCANNER_TOOL_NAMES = ("tile_pano", "detect_first_pass", "verify_crop", "find_second_view", "pin_asset")


def as_tool(fn: Callable[..., Any], context: ToolContext, *, name: str | None = None,
            agent: str = "planner") -> BaseTool:
    """A LangChain tool around a census tool function, bound to ``context``."""

    @functools.wraps(fn)
    def run(*args: Any, **kwargs: Any) -> str:
        with use_context(context):
            try:
                out = fn(*args, **kwargs)
            except Exception as exc:
                log.exception("tool %s failed", name or fn.__name__)
                warning(agent, "tool_error", f"{name or fn.__name__} failed: {type(exc).__name__}.",
                        kwargs.get("building_id"), {"error": str(exc)[:500]})
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        return json.dumps(out, default=str)

    return StructuredTool.from_function(func=run, name=name or fn.__name__,
                                        description=(fn.__doc__ or name or fn.__name__).strip())


def place_one(building_id: str, asset_type: str = "aed") -> dict:
    """Find where one new AED (asset_type="aed") or extinguisher ("extinguisher") covers the most
    scanned positions, and save it as the proposed fix. Returns the fix id."""
    return {"fix_id": fixer.propose_fix(building_id, asset_type)}


def draft_owner_letter(building_id: str) -> dict:
    """Draft the owner letter from measured facts only (a draft, never sent)."""
    return {"document_id": fixer.draft_owner_letter(building_id)}


def emergency_card(building_id: str) -> dict:
    """Write the one-page printable emergency card."""
    return {"document_id": fixer.emergency_card(building_id)}


def registry_list(building_id: str) -> dict:
    """Write the list of AEDs visible in the scan, for confirming registration."""
    return {"document_id": fixer.registry_list(building_id)}


def prioritize(building_ids: list[str]) -> dict:
    """Estimate occupancy for these buildings and return them in scan order (most people first)."""
    return {"order": records.prioritize(building_ids)}


def scanner_tools() -> list[Callable[..., Any]]:
    """Agent 1's scanner tools, when that module is present."""
    try:
        module = importlib.import_module("census.tools.scanner")
    except ImportError:
        return []
    return [getattr(module, n) for n in SCANNER_TOOL_NAMES if callable(getattr(module, n, None))]


def build_subagents(context: ToolContext) -> list[dict]:
    """deepagents SubAgent specs: name, description, system_prompt, tools."""
    def tools(agent: str, fns: list[Callable[..., Any]]) -> list[BaseTool]:
        return [as_tool(f, context, agent=agent) for f in fns]

    specs = [
        {"name": "records", "description": "Looks up CoStar facts and estimates occupancy; sets the scan order.",
         "system_prompt": prompts.RECORDS,
         "tools": tools("records", [records.get_costar_profile, records.estimate_occupancy, prioritize])},
        {"name": "mapper", "description": "Builds walking-time maps for AEDs, extinguishers and exits, "
                                          "finds red zones, stairs-only routes and the worst gap.",
         "system_prompt": prompts.MAPPER,
         "tools": tools("mapper", [mapper.map_building, mapper.build_graph, mapper.walking_time_map,
                                   mapper.flag_routes])},
        {"name": "outside", "description": "Reads entrances, ambulance parking and hydrants and picks the EMS door.",
         "system_prompt": prompts.OUTSIDE,
         "tools": tools("outside", [outside.get_vexcel, outside.pick_ems_door])},
        {"name": "fixer", "description": "Places one new AED or extinguisher and drafts the owner letter, "
                                         "emergency card and registry list.",
         "system_prompt": prompts.FIXER,
         "tools": tools("fixer", [place_one, draft_owner_letter, emergency_card, registry_list])},
    ]
    scan = []
    for fn in scanner_tools():
        try:
            scan.append(as_tool(fn, context, agent="scanner"))
        except Exception as exc:  # noqa: BLE001 - one odd signature must not break the planner
            log.warning("scanner tool %s not wrapped: %s", getattr(fn, "__name__", fn), exc)
    if scan:
        specs.insert(1, {"name": "scanner",
                         "description": "Confirms equipment in panoramas, double-checks borderline "
                                        "detections from a second panorama and pins assets.",
                         "system_prompt": prompts.SCANNER, "tools": scan})
    return specs
