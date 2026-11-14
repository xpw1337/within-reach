"""apply_signal / classify / plan: every branch of the spec section 3 tree, waves and roles."""

from agent.live.config import LiveConfig
from agent.live.playbooks import SCRIPT_IDS
from agent.live.reducer import apply_signal, classify, derive_status, plan, sanitize_verification
from agent.live.state import initial_state, merge_state

ALL_SCRIPTS = list(SCRIPT_IDS)


def base(witnessed=True, **kw):
    s = initial_state(incident_id="i1", camera_id="cam", victim_track_id=7, witnessed=witnessed,
                      detected_at=100.0, collapse_at=95.0 if witnessed else None, cfg=LiveConfig().as_state())
    s["camera"] = {"landmark": "east elevators", "scripts": ALL_SCRIPTS}
    s["routes"] = {"aed": {"distance_m": 14, "directions": "left"}}
    s["done"] = {"verify": True, "request_confirm": True, "voice_check": True}
    s["timers"] = {"voice_check": "t-vc", "confirm_auto" if witnessed else "found_down_escalate": "t-c"}
    s["first_instruction_at"] = 100.2
    s["spoken_key"] = ["voice_check"]
    s.update(kw)
    return s


def step(s, kind, ts=101.0, **kw):
    tr = apply_signal(s, {"kind": kind, "ts": ts, **kw})
    return merge_state(s, tr.updates), tr


def end_voice_check(s, ts=105.0):
    s, _ = step(s, "timeout", ts=ts, name="voice_check", token="t-vc")
    s = merge_state(s, classify(s).updates)
    return s


def test_unresponsive_after_voice_check_is_cardiac():
    s = base()
    assert plan(s) == []
    s, tr = step(base(), "timeout", ts=105.0, name="voice_check", token="t-vc")
    assert s["voice_check_done"] and not s["responsive"]
    assert plan(s) == ["classify"]
    tr = classify(s)
    assert tr.updates == {"type": "cardiac", "playbook": "cardiac", "classified": True}
    s = merge_state(s, tr.updates)
    # speaker is not gated; responders and 911 are
    assert plan(s) == ["announce", "staff"]


def test_raised_hand_from_victim_track_is_fall():
    s, tr = step(base(), "responsive", victim_track_id=7)
    assert s["responsive"] and s["voice_check_done"]
    assert {"type": "cancel_timer", "name": "voice_check"} in tr.effects
    s = merge_state(s, classify(s).updates)
    assert s["type"] == "fall" and s["playbook"] == "fall"
    assert plan(s) == ["announce", "staff", "fall_timer"]
    assert derive_status(s) == "responding"


def test_responsive_from_another_track_or_late_is_ignored():
    _, tr = step(base(), "responsive", victim_track_id=8)
    assert not tr.applied
    _, tr = step(base(), "responsive", victim_track_id=None)
    assert not tr.applied
    s = end_voice_check(base())
    _, tr = step(s, "responsive", ts=106.0, victim_track_id=7)
    assert not tr.applied and s["type"] == "cardiac"


def test_seizure_adds_modifier_and_still_escalates():
    s, _ = step(base(), "possible_seizure", victim_track_id=7)
    assert s["modifiers"] == ["seizure"]
    s = end_voice_check(s)
    assert s["playbook"] == "cardiac"
    from agent.live.playbooks import desired_script
    assert desired_script(s) == ["cardiac_main", "mod_seizure"]


def test_unsafe_scene_from_verify():
    s, _tr = step(base(), "verify_result", result={"is_emergency": True, "scene_safe": False,
                                                    "hazards": ["traffic"], "modifiers": []})
    assert s["scene_safe"] is False and s["hazards"] == ["traffic"]
    s = end_voice_check(s)
    assert s["playbook"] == "unsafe" and s["type"] == "cardiac"
    assert plan(s) == ["announce", "police"]  # no staff, no responders
    s, _ = step(s, "timeout", ts=110.0, name="confirm_auto", token="t-c")
    assert "dispatch" not in plan(s) and "brief_911" in plan(s)


def test_verify_cannot_remove_modifiers_or_unmark_unsafe_or_cancel():
    s, _ = step(base(), "possible_seizure", victim_track_id=7)
    s, _ = step(s, "verify_result", result={"is_emergency": False, "scene_safe": True,
                                            "modifiers": ["breathing", "cancel_incident", "remove:seizure"]})
    assert s["modifiers"] == ["seizure", "breathing"]
    assert not s["resolved"] and s["confirm"] == "pending"
    s2 = dict(s, scene_safe=False)
    s2, _ = step(s2, "verify_result", result={"scene_safe": True})
    assert s2["scene_safe"] is False


def test_verify_junk_is_ignored():
    for junk in ["nonsense", None, 42, {"modifiers": "seizure", "scene_safe": "no"}, {"foo": 1}]:
        s, _tr = step(base(), "verify_result", result=junk)
        assert s["modifiers"] == [] and s["scene_safe"] is None and s["hazards"] == []
        assert s["verification"] == {"error": "invalid output"}
    assert sanitize_verification({"modifiers": ["overdose", "x"], "hazards": [" ", "fire", 3]}) == {
        "modifiers": ["overdose"], "hazards": ["fire"]}


def test_late_unsafe_releases_everyone_and_stops_waves():
    s = end_voice_check(base())
    s, _ = step(s, "confirm", ts=106.0, by="desk")
    s = merge_state(s, {"dispatches": [
        {"id": "d1", "responder_id": "r1", "wave": 1, "status": "accepted", "role": "patient", "call_sid": "CA1"},
        {"id": "d2", "responder_id": "r2", "wave": 1, "status": "sent", "call_sid": None}],
        "waves_sent": 1, "roles": {"patient": "r1"}, "timers": {"wave_1": "tw"}})
    s, tr = step(s, "verify_result", ts=107.0, result={"scene_safe": False})
    assert s["playbook"] == "unsafe"
    assert {d["id"]: d["status"] for d in s["dispatches"]} == {"d1": "released", "d2": "released"}
    assert {"type": "hangup", "call_sid": "CA1", "dispatch_id": "d1"} in tr.effects
    assert "wave_1" not in s["timers"]
    assert "dispatch" not in plan(s)


def test_witnessed_gate_auto_proceeds():
    s = end_voice_check(base())
    assert "dispatch" not in plan(s) and "brief_911" not in plan(s)
    assert derive_status(s) == "awaiting_confirm"
    s, tr = step(s, "timeout", ts=110.0, name="confirm_auto", token="t-c")
    assert s["confirm"] == "auto" and s["confirmed_at"] == 110.0
    assert any(e["kind"] == "gate_opened" for e in tr.events)
    assert {"brief_911", "dispatch"} <= set(plan(s))


def test_desk_confirm_before_classify_opens_gate_at_classify():
    s, tr = step(base(), "confirm", ts=103.0, by="desk-1")
    assert s["confirm"] == "confirmed" and s["confirmed_by"] == "desk-1"
    assert {"type": "cancel_timer", "name": "confirm_auto"} in tr.effects
    assert plan(s) == []  # still in the voice check
    s, _ = step(s, "timeout", ts=105.0, name="voice_check", token="t-vc")
    tr = classify(s)
    assert any(e["kind"] == "gate_opened" for e in tr.events)
    s = merge_state(s, tr.updates)
    assert {"brief_911", "dispatch"} <= set(plan(s))


def test_found_down_needs_human_and_escalates_to_911_only():
    s = end_voice_check(base(witnessed=False))
    s, tr = step(s, "timeout", ts=110.0, name="confirm_auto", token="t-c")
    assert not tr.applied  # no auto-proceed timer for found down
    s, tr = step(s, "timeout", ts=160.0, name="found_down_escalate", token="t-c")
    assert s["confirm"] == "escalated_911_only"
    assert "brief_911" in plan(s) and "dispatch" not in plan(s)
    # a later human confirm opens responders too
    s, _ = step(s, "confirm", ts=170.0, by="desk")
    assert "dispatch" in plan(s)


def test_fall_911_after_timer_unless_cancelled():
    s, _ = step(base(), "responsive", victim_track_id=7)
    s = merge_state(s, classify(s).updates)
    s = merge_state(s, {"fall_911": "armed", "timers": {"fall_911": "tf"}})
    assert "brief_911" not in plan(s)
    s2, tr = step(s, "timeout", ts=170.0, name="fall_911", token="tf")
    assert s2["fall_911"] == "fired" and "brief_911" in plan(s2)
    s3, tr = step(s, "cancel_911", ts=150.0, by="staff")
    assert s3["fall_911"] == "cancelled" and "fall_911" not in s3["timers"]
    assert any(e["kind"] == "fall_911_cancelled" for e in tr.events)
    s3, tr = step(s3, "timeout", ts=170.0, name="fall_911", token="tf")
    assert not tr.applied and "brief_911" not in plan(s3)


def test_cancel_911_only_for_fall():
    s = end_voice_check(base())
    _, tr = step(s, "cancel_911", by="desk")
    assert not tr.applied


def test_false_alarm_stops_everything():
    s = end_voice_check(base())
    s = merge_state(s, {"dispatches": [
        {"id": "d1", "responder_id": "r1", "wave": 1, "status": "sent", "call_sid": "CA1"},
        {"id": "d2", "responder_id": "r2", "wave": 1, "status": "accepted", "role": "patient", "call_sid": "CA2"}],
        "timers": {"announce_repeat": "ta", "wave_1": "tw"}})
    s, tr = step(s, "false_alarm", ts=108.0, by="desk")
    assert s["resolved"] and s["confirm"] == "false_alarm" and derive_status(s) == "false_alarm"
    assert tr.effects[0] == {"type": "stop_audio"}
    assert {e["call_sid"] for e in tr.effects if e["type"] == "hangup"} == {"CA1", "CA2"}
    assert s["timers"] == {}
    assert all(d["status"] == "released" for d in s["dispatches"])
    assert plan(s) == ["handoff"]
    for kind in ("confirm", "accept", "milestone", "resolve"):
        _, tr = step(s, kind, ts=109.0, by="desk", dispatch_id="d1", milestone="cpr_started")
        assert not tr.applied


def wave_state():
    s = end_voice_check(base())
    s, _ = step(s, "confirm", ts=106.0, by="desk")
    rows = [{"id": f"d{i}", "responder_id": f"r{i}", "wave": 1, "status": "sent",
             "call_sid": f"CA{i}" if i % 2 else None, "role": None} for i in range(1, 5)]
    return merge_state(s, {"dispatches": rows, "waves_sent": 1, "timers": {"wave_1": "tw1"}})


def test_two_accepts_then_third_patient_runner_released():
    s = wave_state()
    s, tr = step(s, "accept", ts=107.0, dispatch_id="d2")
    assert s["roles"] == {"patient": "r2"} and s["first_accept_at"] == 107.0
    s, tr = step(s, "accept", ts=108.0, dispatch_id="d4")
    assert s["roles"] == {"patient": "r2", "aed_runner": "r4"}
    by_id = {d["id"]: d for d in s["dispatches"]}
    assert by_id["d2"]["role"] == "patient" and by_id["d4"]["role"] == "aed_runner"
    assert by_id["d1"]["status"] == "released" and by_id["d3"]["status"] == "released"
    assert {e["call_sid"] for e in tr.effects if e["type"] == "hangup"} == {"CA1", "CA3"}
    assert "wave_1" not in s["timers"] and "dispatch" not in plan(s)
    # a third accept (from a released dispatch) stays released
    s, tr = step(s, "accept", ts=109.0, dispatch_id="d1")
    assert not tr.applied


def test_duplicate_accept_is_idempotent():
    s = wave_state()
    s, _ = step(s, "accept", ts=107.0, dispatch_id="d1")
    s2, tr = step(s, "accept", ts=107.5, dispatch_id="d1")
    assert not tr.applied and s2["roles"] == {"patient": "r1"}


def test_wave_timeout_then_next_wave_then_stop_after_three():
    s = wave_state()
    _, tr = step(s, "timeout", ts=126.0, name="wave_1", token="stale")
    assert not tr.applied
    s, tr = step(s, "timeout", ts=126.0, name="wave_1", token="tw1")
    assert s["waves_closed"] == 1
    assert all(d["status"] == "timeout" for d in s["dispatches"])
    assert "dispatch" in plan(s)
    # late accept of a timed-out dispatch still takes a role
    s2, tr = step(s, "accept", ts=127.0, dispatch_id="d3")
    assert s2["roles"] == {"patient": "r3"}
    s = merge_state(s, {"waves_sent": 3, "waves_closed": 3})
    assert "dispatch" not in plan(s)


def test_decline_and_arrived():
    s = wave_state()
    s, tr = step(s, "decline", ts=107.0, dispatch_id="d1", source="app")
    assert {d["id"]: d["status"] for d in s["dispatches"]}["d1"] == "declined"
    assert {"type": "hangup", "call_sid": "CA1", "dispatch_id": "d1"} in tr.effects
    _, tr = step(s, "decline", ts=107.0, dispatch_id="d3", source="twilio")
    assert not [e for e in tr.effects if e["type"] == "hangup"]
    _, tr = step(s, "arrived", ts=108.0, dispatch_id="d2")
    assert not tr.applied  # not accepted yet
    s, _ = step(s, "accept", ts=108.0, dispatch_id="d2")
    s, tr = step(s, "arrived", ts=130.0, dispatch_id="d2", with_aed=True)
    assert s["milestones"] == {"responder_arrived": 130.0, "aed_arrived": 130.0}


def test_milestones_switch_the_speaker():
    s = end_voice_check(base())
    s = merge_state(s, {"spoken_key": ["cardiac_main"], "timers": {"announce_repeat": "ta"}})
    assert "announce" not in plan(s)
    s, tr = step(s, "milestone", ts=120.0, milestone="cpr_started", by="desk")
    assert {"type": "cancel_timer", "name": "announce_repeat"} in tr.effects
    assert plan(s)[0] == "guide"
    _, tr = step(s, "milestone", ts=121.0, milestone="cpr_started")
    assert not tr.applied
    _, tr = step(s, "milestone", ts=121.0, milestone="bogus")
    assert not tr.applied


def test_repeat_timer_sets_speak_due():
    s = end_voice_check(base())
    s = merge_state(s, {"spoken_key": ["cardiac_main"], "timers": {"announce_repeat": "ta"}})
    s, _ = step(s, "timeout", ts=125.0, name="announce_repeat", token="ta")
    assert s["speak_due"] and plan(s)[0] == "announce"


def test_police_on_hazards_or_notify_police():
    s, _ = step(base(), "verify_result", result={"modifiers": ["notify_police"], "scene_safe": True})
    s = end_voice_check(s)
    assert "police" in plan(s)


def test_resolve_keeps_accepted_and_releases_pending():
    s = wave_state()
    s, _ = step(s, "accept", ts=107.0, dispatch_id="d1")
    s, tr = step(s, "resolve", ts=300.0, by="desk")
    by_id = {d["id"]: d["status"] for d in s["dispatches"]}
    assert by_id["d1"] == "accepted" and by_id["d2"] == "released"
    assert s["resolved"] and derive_status(s) == "resolved" and plan(s) == ["handoff"]
    _, tr = step(s, "resolve", ts=301.0)
    assert not tr.applied


def test_first_nodes_then_wait():
    s = base(done={})
    assert plan(s) == ["verify", "request_confirm", "voice_check"]
