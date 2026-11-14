"""The real demo/fallback/building.json, loaded by the real data/load.py into the census fake DB,
then every census tool from 2.4 to 2.6 run on it. Real-database verification is pending
credentials; this is the closest offline check of the 2.4 to 2.6 done-when criteria."""

import pytest

from census.core import docs as core_docs
from census.tests.fakes import EventSink, FakeSupabase, make_context
from census.tools import fixer, mapper, outside, records, routes
from census.tools.context import use_context
from data import load as data_load
from data.fallback import FallbackAdapter
from shared import db as shared_db


@pytest.fixture
def loaded():
    fake = FakeSupabase()
    shared_db.set_db(fake)
    try:
        (summary,) = data_load.load(FallbackAdapter(), with_fixture_rows=True)
        yield fake, summary.building_id
    finally:
        shared_db.set_db(None)


def test_fallback_building_end_to_end(loaded):
    fake, bid = loaded
    events = EventSink()
    with use_context(make_context(fake, events, run_id="run-fb", adapter=FallbackAdapter())):
        records.estimate_occupancy(bid)
        mapper.map_building(bid)
        outside.get_vexcel(bid)
        outside.pick_ems_door(bid)
        fix_id = fixer.propose_fix(bid, "aed")
        docs = fixer.write_documents(bid)
        routes.precompute_camera_routes("cam-lobby-1")
        facts = fixer.collect_facts(bid)

    sweeps = len(fake.rows("twin_nodes", building_id=bid))
    assert sweeps > 0
    assert len(fake.rows("coverage", building_id=bid, scenario="current")) == 3 * sweeps
    assert len(fake.rows("coverage", building_id=bid, scenario="proposed")) == 3 * sweeps
    (score,) = fake.rows("building_scores", building_id=bid)
    assert score["aed_red_frac"] > 0  # the far end of floor 2 is red by design (demo/DESIGN.md)
    (fix,) = fake.rows("fixes", building_id=bid)
    assert fix["id"] == fix_id and fix["sweep_id"] and fix["after_worst_s"] < fix["before_worst_s"]
    assert len(fake.rows("assets", building_id=bid, source="proposed")) == 1
    kinds = sorted(d["kind"] for d in fake.rows("documents", building_id=bid))
    assert kinds == ["emergency_card", "owner_letter", "registry_list"] and len(docs) == 3
    for d in fake.rows("documents", building_id=bid):
        assert core_docs.unexpected_numbers(d["content_md"], facts) == [], d["kind"]
    door = fake.rows("buildings", id=bid)[0]["ems_door"]
    assert door["desc"] and door["reason"]
    aed_route = fake.rows("camera_routes", camera_id="cam-lobby-1", target="aed")[0]
    assert aed_route["directions"] and "meter" not in aed_route["directions"]
    assert aed_route["distance_m"] > 0 and aed_route["audio_url"] is None
    agents = {e["agent"] for e in events.events}
    assert {"records", "mapper", "outside", "fixer"} <= agents
