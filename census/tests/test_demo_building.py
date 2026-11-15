"""The live demo venue (demo/rabinowitz/building.json): a DEMO- building with a team-placed AED.

It must work end to end for the live path (walking-time map, camera route) and never show up as a
census finding: excluded from the report, ranking and run candidates, and its simulated AED never
described as found in the scan.
"""

import pytest

from census import cli
from census import run as census_run
from census.core import docs as core_docs
from census.tests.fakes import EventSink, FakeSupabase, make_context
from census.tests.fixture_building import seed
from census.tools import fixer, ranking, records
from census.tools.context import use_context
from data import load as data_load
from data.fallback import FallbackAdapter
from shared import db as shared_db
from shared.config import REPO_ROOT

DEMO_FILE = REPO_ROOT / "demo" / "rabinowitz" / "building.json"
CAMERA = "cam-atrium-1"
AED_SWEEP = "0f2a2fyf5iibscursb5gkyu9a"


@pytest.fixture
def demo():
    fake = FakeSupabase()
    shared_db.set_db(fake)
    try:
        (summary,) = data_load.load(FallbackAdapter(DEMO_FILE), with_fixture_rows=True)
        events = EventSink()
        # The default adapter (the FALLBACK-1 file) is what production get_adapter() returns.
        with use_context(make_context(fake, events, run_id="run-demo", adapter=FallbackAdapter())):
            yield fake, summary.building_id, events
    finally:
        shared_db.set_db(None)


def test_demo_prefix_is_a_fixture():
    assert records.is_fixture({"costar_property_id": "DEMO-RABINOWITZ"})
    assert records.is_fixture({"costar_property_id": "FALLBACK-1"})
    assert not records.is_fixture({"costar_property_id": "REAL-1"})


def test_demo_pipeline_routes_to_the_team_placed_aed(demo):
    fake, bid, events = demo
    census_run.process_building(bid)

    (b,) = fake.rows("buildings", id=bid)
    assert not b.get("vexcel") and not b.get("ems_door")  # the fallback's outside data is not borrowed
    cam = fake.rows("cameras", id=CAMERA)[0]
    current = {r["sweep_id"]: r["time_s"] for r in fake.rows("coverage", building_id=bid, scenario="current",
                                                              asset_type="aed")}
    assert current[AED_SWEEP] == 0 and current[cam["sweep_id"]] > 0  # the demo AED feeds this building's map

    (route,) = fake.rows("camera_routes", camera_id=CAMERA, target="aed")
    assert route["path"][0] == cam["sweep_id"] and route["path"][-1] == AED_SWEEP
    assert 8 <= route["distance_m"] <= 15
    assert "Gothic arcade gate" in route["directions"]
    assert "Demo AED" not in route["directions"] and "meter" not in route["directions"]

    docs = {d["kind"]: d["content_md"] for d in fake.rows("documents", building_id=bid)}
    assert "Demo AED" not in docs["registry_list"].split("not listed")[0]
    assert "No AED visible in the scan" in docs["registry_list"] and "not listed" in docs["registry_list"]
    letter = docs["owner_letter"]
    assert "no AED visible in the scan" in letter and core_docs.TEAM_PLACED_NOTE in letter
    card = docs["emergency_card"]
    assert "Demo AED (placed by team), at the Gothic arcade gate (level 2)" in card
    assert core_docs.TEAM_PLACED_NOTE in card
    facts = fixer.collect_facts(bid)
    assert facts["aeds"] == [] and facts["measured"]["aed"]["visible_in_scan"] == 0
    assert facts["measured"]["aed"]["team_placed"] == 1
    for kind, text in docs.items():
        assert core_docs.unexpected_numbers(text, facts) == [], kind
    assert any("demo AED placed by the team" in e["message"] for e in events.events)


def test_demo_building_never_counts(demo):
    fake, bid, _ = demo
    real = seed(fake, _real_copy())
    other_fixture = seed(fake)  # FALLBACK-TEST
    assert census_run._candidates(census_run.RunConfig(budget_usd=5.0)) == [real]
    for b in (bid, real, other_fixture):
        census_run.process_building(b)
    assert cli.report()["buildings_scanned"] == 1
    groups = ranking.rerank()["groups"]
    assert groups.get("fixture") == 2 and groups.get("Houston") == 1
    ranks = {s["building_id"]: s["rank"] for s in fake.rows("building_scores")}
    assert ranks == {bid: 1, real: 1, other_fixture: 1}  # fixtures are ranked alone
    # Named explicitly (rerun), it still runs.
    assert census_run._candidates(census_run.RunConfig(budget_usd=5.0, building_ids=[bid])) == [bid]


def _real_copy():
    import copy

    from census.tests.fixture_building import fixture_building

    data = copy.deepcopy(fixture_building())
    data["building"].update(costar_property_id="REAL-1", name="Real Gym")
    data.pop("camera")
    return data


def test_letter_wording_with_both_scan_and_team_placed_aeds():
    show = lambda t, s: None if s is None else (2 * s if t == "aed" else s)
    facts = core_docs.build_facts(
        building={"name": "X"}, score={"aed_worst_s": 30, "aed_red_frac": 0.1}, sweeps_scanned=10,
        assets={"aed": [{"type": "aed", "label": "front desk", "floor": 1}]}, fix=None, fix_where=None,
        ems_door=None, occupancy_basis=None, show_s=show,
        team_placed={"aed": [{"type": "aed", "label": "Demo AED (placed by team)", "floor": 1, "place": "hall"}]},
    )
    assert [a["where"] for a in facts["aeds"]] == ["front desk"]
    body = core_docs.owner_letter_template(facts)
    assert "these times also include an AED placed by our team for a demo, not found in the scan" in body
    reg = core_docs.registry_list(facts)
    assert "front desk" in reg and "Demo AED" not in reg.split("not listed")[0]
    card = core_docs.emergency_card(facts)
    assert "- front desk (level 1)" in card and "Demo AED (placed by team), at the hall (level 1)" in card
    assert "No other AED" not in card
