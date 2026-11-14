import copy
import time

import pytest
from langchain_core.messages import AIMessage

from census import cli
from census import run as census_run
from census.tests.fakes import EventSink, FakeLLM, FakeSupabase, make_context
from census.tests.fixture_building import fixture_building, seed
from census.tests.test_agent_wiring import ScriptedModel, call
from census.tools import mapper
from census.tools.context import use_context


def seed_city(db, n=20):
    """One fixture plus n real-looking buildings, larger than the fixture so they rank first."""
    fixture_id = seed(db)
    ids = []
    for i in range(n):
        data = copy.deepcopy(fixture_building())
        data["building"].update(costar_property_id=f"REAL-{i}", name=f"Gym {i}", size_sqft=30000 + 1000 * i)
        data.pop("camera")
        ids.append(seed(db, data))
    return fixture_id, ids


@pytest.fixture
def env():
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events)) as c:
        yield db, events, c


def test_pipeline_run_of_20_survives_a_forced_error(env, monkeypatch):
    db, events, _ = env
    fixture_id, ids = seed_city(db)
    bad = ids[7]
    real_map = mapper.map_building

    def flaky(building_id):
        if building_id == bad:
            raise RuntimeError("forced failure")
        return real_map(building_id)

    monkeypatch.setattr(mapper, "map_building", flaky)
    run_id = census_run.start_run(20, "Houston", ["gym"], 5.0, mode="pipeline", background=False)

    (run,) = db.rows("runs", id=run_id)
    assert run["status"] == "done" and run["buildings_done"] == 19 and run["finished_at"]
    assert db.rows("buildings", id=bad)[0]["census_status"] == "error"
    assert db.rows("buildings", id=fixture_id)[0]["census_status"] == "pending"  # ranked 21st, not run
    assert all(db.rows("buildings", id=b)[0]["census_status"] == "fixed" for b in ids if b != bad)
    assert any(e["payload"].get("code") == "building_error" and e["building_id"] == bad for e in events.events)
    assert {e["run_id"] for e in events.events if e["run_id"]} == {run_id}
    ranks = sorted(s["rank"] for s in db.rows("building_scores") if s["building_id"] in ids)
    assert ranks == list(range(1, 20))

    r = cli.report(run_id)
    assert r["buildings_scanned"] == 19 and r["handcheck_labeled"] == 0
    text = cli.format_report(r)
    assert "Buildings scanned:            19" in text and "Hand-check precision:         --" in text


def test_budget_guard_stops_new_buildings(env):
    db, events, _ = env
    seed_city(db, n=6)

    class MeteredLLM(FakeLLM):
        def __call__(self, **kwargs):  # stands in for shared.llm cost metering into runs.est_cost_usd
            row = db.rows("runs", id=kwargs["run_id"])[0]
            row["est_cost_usd"] = (row.get("est_cost_usd") or 0) + 1.0
            return {"body_md": "Please review the measured gaps."}

    with use_context(make_context(db, events, llm=MeteredLLM())):
        run_id = census_run.start_run(6, None, None, 3.0, mode="pipeline", batch_size=2, background=False)
    (run,) = db.rows("runs", id=run_id)
    assert run["status"] == "budget_stopped" and run["buildings_done"] == 3
    assert any(e["payload"].get("code") == "budget_exhausted" for e in events.events)


def test_crash_then_resume_skips_finished_buildings(env, monkeypatch):
    db, _, _ = env
    _, ids = seed_city(db, n=5)
    seen = []
    real = census_run.process_building

    def crashing(building_id):
        seen.append(building_id)
        if len(seen) == 3:
            raise SystemExit("simulated crash")
        return real(building_id)

    monkeypatch.setattr(census_run, "process_building", crashing)
    with pytest.raises(SystemExit):
        census_run.start_run(5, None, ["gym"], 5.0, mode="pipeline", background=False)
    (run,) = db.rows("runs")
    assert run["status"] == "running" and run["buildings_done"] == 2

    monkeypatch.setattr(census_run, "process_building", lambda b: (seen.append(b), real(b))[1])
    census_run.resume_run(run["id"], background=False)
    (run,) = db.rows("runs")
    assert run["status"] == "done" and run["buildings_done"] == 5
    assert len(seen) == 3 + 3  # 2 done + crash on the 3rd, then the 3rd again plus 2 more
    assert len(set(seen[3:]) & set(seen[:2])) == 0
    assert all(len(db.rows("fixes", building_id=b, asset_type="aed")) == 1 for b in ids)


def test_stop_run(env, monkeypatch):
    db, _, _ = env
    seed_city(db, n=6)
    real = census_run.process_building
    monkeypatch.setattr(census_run, "process_building", lambda b: (time.sleep(0.05), real(b))[1])
    run_id = census_run.start_run(6, None, None, 5.0, mode="pipeline", batch_size=1, background=True)
    time.sleep(0.02)
    census_run.stop_run(run_id)
    census_run.wait(run_id, timeout=10)
    (run,) = db.rows("runs", id=run_id)
    assert run["status"] == "stopped" and run["buildings_done"] < 6


def test_rerun_building_in_agent_mode_streams_and_finishes(env):
    db, events, _ = env
    bid = seed(db)
    script = [
        call("write_todos", 1, todos=[{"content": "Map, fix and document the gym", "status": "in_progress"}]),
        call("task", 2, description=f"Map building {bid}", subagent_type="mapper"),
        call("map_building", 3, building_id=bid),
        AIMessage(content="Mapped."),
        call("task", 4, description=f"Find the EMS door for {bid}", subagent_type="outside"),
        call("get_vexcel", 5, building_id=bid),
        call("pick_ems_door", 6, building_id=bid),
        AIMessage(content="Door chosen."),
        call("task", 7, description=f"Fix building {bid}", subagent_type="fixer"),
        call("place_one", 8, building_id=bid),
        call("draft_owner_letter", 9, building_id=bid),
        call("emergency_card", 10, building_id=bid),
        call("registry_list", 11, building_id=bid),
        AIMessage(content="Fixed."),
        call("write_todos", 12, todos=[{"content": "Map, fix and document the gym", "status": "completed"}]),
        AIMessage(content="Done."),
    ]
    run_id = census_run.rerun_building(bid, mode="agent", background=False,
                                       model=ScriptedModel(messages=iter(script)))
    (run,) = db.rows("runs", id=run_id)
    assert run["status"] == "done" and run["buildings_done"] == 1
    assert db.rows("buildings", id=bid)[0]["census_status"] == "fixed"
    assert db.rows("camera_routes", camera_id="cam-lobby-1")  # precomputed after the building finished
    kinds = {(e["agent"], e["kind"]) for e in events.events if e["run_id"] == run_id}
    assert {("planner", "todo"), ("planner", "decision"), ("mapper", "result"), ("outside", "decision"),
            ("fixer", "decision")} <= kinds
    # The fixture is excluded from the pitch numbers.
    assert cli.report(run_id)["buildings_scanned"] == 0


def test_report_with_no_data_prints_dashes(env):
    text = cli.format_report(cli.report())
    assert "Buildings scanned:            --" in text and "Cost:                         --" in text


def test_report_counts_handchecks_for_real_buildings_only(env):
    db, _, _ = env
    fixture_id, ids = seed_city(db, n=1)
    db.table("detections").insert([
        {"building_id": ids[0], "human_label": "correct"},
        {"building_id": ids[0], "human_label": "incorrect"},
        {"building_id": ids[0], "human_label": "unsure"},
        {"building_id": fixture_id, "human_label": "correct"},
    ]).execute()
    r = cli.report()
    assert (r["handcheck_correct"], r["handcheck_labeled"]) == (1, 2)
    assert "1/2 correct" in cli.format_report(r)
