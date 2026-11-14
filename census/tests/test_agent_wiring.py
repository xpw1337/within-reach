"""Deep Agent wiring with a scripted fake chat model (no LLM keys). A real run is not verified."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from census.agent.planner import run_buildings
from census.tests.fakes import EventSink, FakeSupabase, make_context
from census.tests.fixture_building import seed


class ScriptedModel(GenericFakeChatModel):
    """Replays AI messages (including tool calls) in order; tool binding is a no-op."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, n, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{n}", "type": "tool_call"}])


def test_planner_streams_plan_delegations_and_results_to_the_console():
    db, events = FakeSupabase(), EventSink()
    bid = seed(db)
    ctx = make_context(db, events, run_id="run-agent")
    script = [
        call("write_todos", 1, todos=[{"content": "Map the fixture gym", "status": "in_progress"},
                                      {"content": "Propose a fix", "status": "pending"}]),
        call("scan_building_bulk", 2, building_id=bid),
        call("task", 3, description=f"Map building {bid}", subagent_type="mapper"),
        call("map_building", 4, building_id=bid),
        AIMessage(content="Mapped."),
        call("task", 5, description=f"Fix building {bid}", subagent_type="fixer"),
        call("place_one", 6, building_id=bid, asset_type="aed"),
        AIMessage(content="Fixed."),
        call("write_todos", 7, todos=[{"content": "Map the fixture gym", "status": "completed"},
                                      {"content": "Propose a fix", "status": "completed"}]),
        AIMessage(content="Done: mapped and fixed one building."),
    ]
    final = run_buildings([bid], ctx, model=ScriptedModel(messages=iter(script)))
    assert final.startswith("Done")

    todos = [e for e in events.events if e["kind"] == "todo"]
    assert len(todos) == 2 and todos[0]["agent"] == "planner"
    assert todos[0]["payload"]["todos"][0] == {"text": "Map the fixture gym", "status": "in_progress"}
    assert [t["status"] for t in todos[1]["payload"]["todos"]] == ["done", "done"]
    handoffs = [e["message"] for e in events.events if e["kind"] == "decision" and e["agent"] == "planner"]
    assert any(m.startswith("Handing work to mapper") for m in handoffs)
    assert any(m.startswith("Handing work to fixer") for m in handoffs)
    assert any(e["payload"].get("code") == "scanner_unavailable" for e in events.events)
    # The subagents' tools really ran against the database.
    assert db.rows("building_scores", building_id=bid)
    assert len(db.rows("fixes", building_id=bid)) == 1
    assert {e["run_id"] for e in events.events} == {"run-agent"}
    assert {"planner", "mapper", "fixer"} <= {e["agent"] for e in events.events}


def test_tool_errors_become_warnings_not_crashes():
    db, events = FakeSupabase(), EventSink()
    ctx = make_context(db, events, run_id="run-err")
    script = [
        call("task", 1, description="Map building missing", subagent_type="mapper"),
        call("map_building", 2, building_id="missing"),
        AIMessage(content="The building does not exist."),
        AIMessage(content="Stopped: building not found."),
    ]
    final = run_buildings(["missing"], ctx, model=ScriptedModel(messages=iter(script)))
    assert "Stopped" in final
    assert any(e["payload"].get("code") == "tool_error" for e in events.events)
