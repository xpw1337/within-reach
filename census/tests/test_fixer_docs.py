import pytest

from census.core import docs as core_docs
from census.tests.fakes import TEST_LIMITS_S, EventSink, FakeLLM, FakeSupabase, make_context
from census.tests.fixture_building import seed
from census.tools import fixer, mapper, records
from census.tools.context import use_context


@pytest.fixture
def env():
    db, events, llm = FakeSupabase(), EventSink(), FakeLLM()
    with use_context(make_context(db, events, llm=llm, run_id="run-1")):
        bid = seed(db)
        records.estimate_occupancy(bid)
        mapper.map_building(bid)
        yield db, events, llm, bid


def test_propose_fix_writes_fix_proposed_asset_and_proposed_coverage(env):
    db, events, _, bid = env
    fix_id = fixer.propose_fix(bid)
    (fix,) = db.rows("fixes", building_id=bid)
    assert fix["id"] == fix_id and fix["asset_type"] == "aed"
    assert fix["sweep_id"] is not None
    assert fix["after_worst_s"] < fix["before_worst_s"]  # one-way seconds (D4)
    assert fix["after_red_frac"] <= fix["before_red_frac"]
    (proposed,) = db.rows("assets", building_id=bid, source="proposed")
    assert proposed["sweep_id"] == fix["sweep_id"] and proposed["type"] == "aed"
    prop = db.rows("coverage", building_id=bid, scenario="proposed")
    assert len(prop) == 20 * 3
    aed_prop = {r["sweep_id"]: r["time_s"] for r in prop if r["asset_type"] == "aed"}
    assert aed_prop[fix["sweep_id"]] == 0.0
    assert max(aed_prop.values()) == pytest.approx(fix["after_worst_s"])
    # Current coverage is untouched by the proposal.
    cur = {r["sweep_id"]: r["time_s"] for r in db.rows("coverage", building_id=bid, scenario="current")
           if r["asset_type"] == "aed"}
    assert max(cur.values()) == pytest.approx(fix["before_worst_s"])
    assert any(e["kind"] == "decision" and e["agent"] == "fixer" and "Placing one new AED" in e["message"]
               for e in events.events)


def test_propose_fix_replaces_earlier_proposal_and_validates_type(env):
    db, _, _, bid = env
    fixer.propose_fix(bid)
    fixer.propose_fix(bid)
    assert len(db.rows("fixes", building_id=bid, asset_type="aed")) == 1
    assert len(db.rows("assets", building_id=bid, source="proposed")) == 1
    fixer.propose_fix(bid, "extinguisher")
    assert len(db.rows("fixes", building_id=bid)) == 2
    with pytest.raises(ValueError):
        fixer.propose_fix(bid, "exit")


def test_documents_with_a_good_llm_draft(env):
    db, _, llm, bid = env
    fixer.propose_fix(bid)
    facts = fixer.collect_facts(bid)
    rec = facts["recommendation"]
    llm.responses.append({"body_md": (
        f"We measured {facts['scan_positions']} scanned positions. The AED worst case is "
        f"{facts['measured']['aed']['worst_case']}. We recommend one AED at {rec['where']}, which "
        f"brings the worst case to {rec['worst_case_after']}.")})
    ids = fixer.write_documents(bid)
    assert set(ids) == {"owner_letter", "emergency_card", "registry_list"}
    docs = {d["kind"]: d["content_md"] for d in db.rows("documents", building_id=bid)}
    assert len(docs) == 3
    letter = docs["owner_letter"]
    assert core_docs.DRAFT_NOTICE in letter and core_docs.REGISTRY_INSTRUCTIONS in letter
    assert rec["worst_case_after"] in letter and "round trip" in letter
    assert len(llm.calls) == 1
    assert llm.calls[0]["user"][0]["type"] == "text" and llm.calls[0]["run_id"] == "run-1"
    # Only measured numbers anywhere in the three documents.
    for kind, text in docs.items():
        assert core_docs.unexpected_numbers(text, facts) == [], kind
    assert "by the front desk" in docs["emergency_card"] and "911" in docs["emergency_card"]
    assert "by the front desk" in docs["registry_list"]


def test_letter_with_invented_number_is_regenerated_then_templated(env):
    db, events, llm, bid = env
    fixer.propose_fix(bid)
    allowed = core_docs.allowed_numbers(fixer.collect_facts(bid))
    assert "4321" not in allowed and "8765" not in allowed
    llm.responses += [{"body_md": "Survival falls 4321% per minute."},
                      {"body_md": "This building has no AED. 8765 people could die."}]
    fixer.draft_owner_letter(bid)
    assert len(llm.calls) == 2
    assert "rejected" in llm.calls[1]["user"][0]["text"]
    (doc,) = db.rows("documents", building_id=bid, kind="owner_letter")
    assert "4321" not in doc["content_md"] and "8765" not in doc["content_md"]
    assert "has no AED" not in doc["content_md"]
    assert "Recommendation" in doc["content_md"]  # the template body
    assert any(e["payload"].get("code") == "letter_template" for e in events.events)


def test_letter_second_draft_accepted(env):
    db, _, llm, bid = env
    fixer.propose_fix(bid)
    llm.responses += [{"body_md": "Worst case 999 s."}, {"body_md": "Please review the measured gaps."}]
    fixer.draft_owner_letter(bid)
    (doc,) = db.rows("documents", building_id=bid, kind="owner_letter")
    assert "Please review the measured gaps." in doc["content_md"]


def test_letter_falls_back_when_llm_errors_or_missing():
    db, events = FakeSupabase(), EventSink()
    with use_context(make_context(db, events, llm=FakeLLM(responses=[RuntimeError("down")]))):
        bid = seed(db)
        mapper.map_building(bid)
        fixer.draft_owner_letter(bid)
    with use_context(make_context(db, events, llm=None)):
        fixer.draft_owner_letter(bid)
    (doc,) = db.rows("documents", building_id=bid, kind="owner_letter")
    assert "We measured walking access" in doc["content_md"]


def test_checker_and_wording_rules():
    facts = {"a": "188 s round trip", "b": "38%", "c": {"d": ["1,200 sq ft"]}, "n": "20"}
    assert core_docs.unexpected_numbers("Worst case 188 s, 38% red, 1200 sq ft, 20 positions.", facts) == []
    assert core_docs.unexpected_numbers("1. First item\n2. Second", facts) == []  # list markers
    assert core_docs.unexpected_numbers("Call 911.", facts) == []
    assert core_docs.unexpected_numbers("About 140 s and 4.0 m.", facts) == ["140", "4"]
    assert core_docs.wording_problems("The building has no AED.") == ["no AED"]
    assert core_docs.wording_problems("No AED is visible in the scan.") == []


def test_card_and_registry_without_equipment():
    facts = core_docs.build_facts(building={"name": "B", "address": "2 Road"}, score=None, sweeps_scanned=0,
                                  assets={}, fix=None, fix_where=None, ems_door=None, occupancy_basis=None,
                                  show_s=lambda t, s: s)
    card = core_docs.emergency_card(facts)
    assert "No AED visible in the scan" in card and "--" in card
    assert "No AED visible in the scan" in core_docs.registry_list(facts)


def test_fixed_limit_values_are_test_stand_ins():
    # Guard: the tool tests use the .env.example defaults through the fake context.
    assert TEST_LIMITS_S["aed"] == 90
