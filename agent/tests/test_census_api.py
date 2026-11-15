"""The census routes kept on the agent app (unchanged by the live SOS rewrite)."""

import httpx
import pytest

from agent.api.handcheck import sample_rows, summarize
from agent.main import create_app
from agent.sos.hub import Hub
from agent.sos.settings import SosSettings


@pytest.fixture
async def client(tmp_path):
    s = SosSettings()
    s.offline = True
    s.state_file = tmp_path / "state.json"
    app = create_app(Hub(s, use_llm=False))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_and_thresholds(client):
    assert (await client.get("/health")).json()["ok"] is True
    assert (await client.get("/config/thresholds")).status_code == 200


async def test_census_routes_503_when_db_missing(client, monkeypatch):
    import shared.config

    monkeypatch.setattr(shared.config.get_settings(), "supabase_url", None, raising=False)
    r = await client.get("/census/runs/x")
    assert r.status_code == 503 and r.json() == {"detail": "database not available"}
    assert (await client.get("/census/handcheck/summary")).status_code == 503


def test_handcheck_helpers():
    rows = [{"id": "a", "human_label": "correct"}, {"id": "b", "human_label": None},
            {"id": "c", "human_label": "unsure"}]
    assert sample_rows(rows, 2)[0]["detection_id"] == "b"  # unlabeled first
    assert summarize(rows) == {"labeled": 2, "correct": 1, "incorrect": 0, "unsure": 1}


async def test_census_routes_call_census_run(client, monkeypatch):
    import census.run
    import census.tools.fixer

    calls = []
    monkeypatch.setattr(census.run, "start_run", lambda *a, **k: calls.append(("start", a)) or "run-1")
    monkeypatch.setattr(census.run, "stop_run", lambda *a, **k: calls.append(("stop", a)))
    monkeypatch.setattr(census.run, "rerun_building", lambda *a, **k: calls.append(("rerun", a)) or "run-2")
    monkeypatch.setattr(census.tools.fixer, "propose_fix", lambda *a, **k: calls.append(("fix", a)) or "fix-1")
    r = await client.post("/census/runs", json={"buildings_target": 20, "city": "Houston", "budget_usd": 5})
    assert r.json() == {"run_id": "run-1"}
    assert (await client.post("/census/runs/run-1/stop")).json() == {"status": "stopping"}
    assert (await client.post("/census/buildings/b1/rerun")).json() == {"run_id": "run-2"}
    r = await client.post("/census/buildings/b1/fix", json={"asset_type": "extinguisher"})
    assert r.json() == {"fix_id": "fix-1"}
    assert calls == [("start", (20, "Houston", None, 5.0)), ("stop", ("run-1",)), ("rerun", ("b1",)),
                     ("fix", ("b1", "extinguisher"))]
