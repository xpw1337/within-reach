from pathlib import Path

import pytest

from agent.live import playbooks as pb

SPEC = (Path(__file__).resolve().parents[2] / "CLAUDE.md").read_text(encoding="utf-8")
EM_DASH = chr(0x2014)


def _spec_quote(start: str) -> str:
    """The quoted template that starts with ``start`` in spec section 3, with bold markers removed
    and each em-dash replaced by a comma (the one allowed edit)."""
    section = SPEC[SPEC.index("## 3. Live triage"): SPEC.index("## 4. Architecture")]
    i = section.index('"' + start)
    j = section.index('"', i + 1)
    text = section[i + 1: j].replace("**", "")
    return text.replace(" " + EM_DASH + " ", ", ")


@pytest.mark.parametrize(
    "script_id,start",
    [
        ("voice_check", "Are you okay?"),
        ("cardiac_main", "Emergency: someone"),
        ("cardiac_cpr_coach", "Push at least"),
        ("mod_breathing", "If they are breathing"),
        ("mod_seizure", "If they're shaking"),
        ("mod_overdose", "Naloxone is in"),
        ("fall_main", "Help is on the way"),
    ],
)
def test_script_text_is_spec_verbatim(script_id, start):
    assert pb.SCRIPTS[script_id] == _spec_quote(start)


def test_no_em_dash_anywhere_in_scripts():
    for text in pb.SCRIPTS.values():
        assert text is None or EM_DASH not in text


def test_script_ids_match_contract():
    assert set(pb.SCRIPTS) == set(pb.SCRIPT_IDS)
    assert len(pb.SCRIPT_IDS) == 10


def test_team_lead_approved_wording():
    # NOT spec text: approved by the team lead on 2026-11-14
    assert pb.SCRIPTS["unsafe_stay_back"] == (
        "Emergency by {landmark}. The area may not be safe. Stay back, keep others away, and call 911.")
    assert pb.SCRIPTS["cardiac_aed_arrived"] == "The AED is here. Turn it on and follow its voice."
    assert pb.SCRIPTS["all_clear"] == "All clear. Thank you."
    assert pb.render("unsafe_stay_back", {"landmark": "east elevators"}).startswith("Emergency by east elevators.")


ROUTES = {"aed": {"distance_m": 13.6, "directions": "left of the elevators"}}
CAMERA = {"landmark": "east elevators"}


def test_render_cardiac_main_fills_census_values():
    text = pb.render("cardiac_main", pb.camera_context(CAMERA, ROUTES))
    assert "collapsed by east elevators." in text
    assert text.endswith("get the AED, 14 meters, left of the elevators.")


def test_no_aed_route_drops_only_the_aed_sentence():
    full = pb.render("cardiac_main", pb.camera_context(CAMERA, ROUTES))
    text = pb.render("cardiac_main", pb.camera_context(CAMERA, {}))
    assert "AED" not in text
    assert text.endswith("push hard and fast in the center of the chest.")
    assert full.startswith(text)
    assert "cardiac_main" in pb.renderable_scripts(CAMERA, {})  # never skipped


def test_overdose_only_when_naloxone_mapped():
    assert "mod_overdose" not in pb.renderable_scripts(CAMERA, ROUTES)
    routes = {**ROUTES, "naloxone": {"distance_m": 5, "directions": "past the lockers"}}
    scripts = pb.renderable_scripts(CAMERA, routes)
    assert scripts["mod_overdose"].startswith("Naloxone is in past the lockers.")  # fallback
    routes["naloxone"]["location_label"] = "the front desk first aid box"
    scripts = pb.renderable_scripts(CAMERA, routes)
    assert scripts["mod_overdose"].startswith("Naloxone is in the front desk first aid box.")


ALL = set(pb.SCRIPT_IDS)


def _state(**kw):
    base = {"playbook": "cardiac", "modifiers": [], "milestones": {}, "routes": ROUTES}
    base.update(kw)
    return base


def test_desired_cardiac_with_modifiers_in_order():
    s = _state(modifiers=["seizure", "breathing", "overdose", "notify_police"])
    # overdose dropped: no naloxone mapped; notify_police has no script
    assert pb.desired_script(s, ALL) == ["cardiac_main", "mod_breathing", "mod_seizure"]


def test_desired_switches_on_milestones():
    assert pb.desired_script(_state(milestones={"cpr_started": 1.0}), ALL) == ["cardiac_cpr_coach"]
    assert pb.desired_script(_state(milestones={"cpr_started": 1.0, "aed_arrived": 2.0}), ALL) == [
        "cardiac_aed_arrived"
    ]
    # no AED-arrived audio: keep coaching (the coach script covers the AED)
    no_aed = ALL - {"cardiac_aed_arrived"}
    assert pb.desired_script(_state(milestones={"aed_arrived": 2.0}), no_aed) == ["cardiac_cpr_coach"]


def test_unsafe_never_falls_back_to_cardiac():
    assert pb.desired_script(_state(playbook="unsafe"), ALL) == ["unsafe_stay_back"]
    assert pb.desired_script(_state(playbook="unsafe"), ALL - {"unsafe_stay_back"}) == []


def test_fall_and_unclassified():
    assert pb.desired_script(_state(playbook="fall"), ALL) == ["fall_main"]
    assert pb.desired_script(_state(playbook=None), ALL) == []


def test_repeat_rules():
    cfg = {"announce_repeat_seconds": 20, "guide_repeat_seconds": 20}
    assert pb.repeat_seconds(["cardiac_main", "mod_seizure"], cfg) == 20
    assert pb.repeat_seconds(["cardiac_cpr_coach"], cfg) == 20
    assert pb.repeat_seconds(["fall_main"], cfg) is None
    assert pb.is_guide(["cardiac_cpr_coach"]) and not pb.is_guide(["cardiac_main"])
