"""Census test defaults.

Agent 1's bulk scanner (census/tools/bulk.py) talks to the shared DB and LLM clients directly. The
census tool, agent and run tests here are about mapping, fixing and run lifecycle, so they pin the
bulk step off whether or not that module is installed. A test that wants the bulk step patches
``census.agent.planner._load_bulk`` / ``census.run._load_bulk`` itself, and a test that runs the
real scanner tools must call ``shared.db.set_db(fake)`` and ``shared.llm.set_client(...)``.
"""

import pytest


@pytest.fixture(autouse=True)
def _no_bulk_scan(monkeypatch):
    from census import run
    from census.agent import planner

    monkeypatch.setattr(planner, "_load_bulk", lambda: None)
    monkeypatch.setattr(run, "_load_bulk", lambda: None)
