"""The deterministic live response graph (spec section 9.8), signal-inbox shape (agent/DESIGN.md).

    START -> ingest -> first_response -> route
    route --plan()--> Send(verify | request_confirm | voice_check)    first pass, in parallel
                    | classify                                        when the voice check ends
                    | Send(announce | guide | dispatch | brief_911 | police | staff | fall_timer)
                    | handoff -> END                                  after resolve or false alarm
                    | await_signal                                    nothing to do: wait
    every node -> route

Why not one interrupt per waiting branch: in LangGraph 1.2 a successor runs only after every task
of the superstep finished, so classify would wait for a pending confirm interrupt (measured, see
agent/README.md). All waiting is therefore one ``interrupt()`` in ``await_signal``; the pure
reducer applies each signal and ``plan`` decides what runs next.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent.live.nodes import actions, decide, handoff, speak, start
from agent.live.reducer import plan
from agent.live.state import IncidentState

FAN_OUT = ("verify", "request_confirm", "voice_check", "announce", "guide", "dispatch", "brief_911",
           "police", "staff", "fall_timer")


def route_after(state: dict):
    if state.get("resolved") and (state.get("done") or {}).get("handoff"):
        return END
    todo = plan(state)
    if not todo:
        return "await_signal"
    if todo in (["classify"], ["handoff"]):
        return todo[0]
    return [Send(name, state) for name in todo]


def build_graph(rt) -> StateGraph:
    nodes = {}
    for module in (start, decide, speak, actions, handoff):
        nodes.update(module.make(rt))
    g = StateGraph(IncidentState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    async def route(state: dict) -> dict:
        return {}

    g.add_node("route", route)
    g.add_edge(START, "ingest")
    g.add_edge("ingest", "first_response")
    g.add_edge("first_response", "route")
    g.add_conditional_edges("route", route_after, [*FAN_OUT, "classify", "handoff", "await_signal", END])
    for name in (*FAN_OUT, "classify", "await_signal"):
        g.add_edge(name, "route")
    g.add_edge("handoff", END)
    return g
