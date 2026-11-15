"""The 12 graph tests from agent/DESIGN.md, with FakeSpeaker, FakeTelephony and a fake clock."""

import asyncio

import pytest

from agent.io.speaker import FakeSpeaker
from agent.io.telephony import EmergencyNumberError, FakeTelephony, check_destination
from agent.io.verify import FakeVerifier
from agent.tests.fixtures import T0, responder, runtime


async def start(rt, witnessed=True, frame=b"jpeg"):
    iid, state = await rt.start_incident(camera_id="cam-test", victim_track_id=7, witnessed=witnessed,
                                         event_ts=T0, frame=frame)
    await rt.settle()
    return iid


def wave_dispatches(rt, wave=None):
    return [d for d in rt.store.dispatches.values()
            if d.get("role") != "staff" and (wave is None or d["wave"] == wave)]


def kinds(rt):
    return [e["kind"] for e in rt.store.events]


async def test_1_witnessed_cardiac_no_tap_auto_proceeds_at_10s(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        assert rt.speaker.played() == ["voice_check"]
        inc = rt.store.incidents[iid]
        assert inc["status"] == "voice_check" and inc["first_instruction_at"] is not None
        await rt.clock.advance(5)
        assert rt.speaker.played()[1:] == ["cardiac_main"]
        assert rt.store.incidents[iid]["type"] == "cardiac"
        assert wave_dispatches(rt) == [] and not [c for c in rt.telephony.calls if c["kind"] == "briefing"]
        await rt.clock.advance(5)  # t = 10 s
        assert len(wave_dispatches(rt, 1)) == 4
        # r0 (staff) already got the staff alert at classify: never a second alert in a wave
        assert "r0" not in {d["responder_id"] for d in wave_dispatches(rt)}
        sent = rt.store.events_of("dispatch_sent")
        assert set(sent[-1]["payload"]) >= {"dispatch_id", "responder_id", "role", "wave", "channel"}
        called = [d for d in wave_dispatches(rt, 1) if d["channel"] == "call"]
        assert called and all(d["call_sid"] for d in called)  # first-ring latency source
        assert [c["kind"] for c in rt.telephony.calls].count("briefing") == 1
        inc = rt.store.incidents[iid]
        assert inc["confirmed_by"] == "auto" and inc["status"] == "responding"
        assert inc["ems_notified_at"] is not None


async def test_2_desk_confirm_at_3s_phones_ring_before_15s_from_collapse(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(3)
        await rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"})
        await rt.clock.advance(2)  # voice check ends at 5 s
        calls = [c for c in rt.telephony.calls if c["kind"] == "responder"]
        assert calls, "a responder phone should ring"
        state = await rt.get_state(iid)
        first_ring = min(d["sent_at"] for d in state["dispatches"] if d.get("call_sid"))
        assert first_ring - state["collapse_at"] < 15
        # first CPR instruction within 12 s of the collapse (spec 9.8)
        assert rt.clock.now() - state["collapse_at"] <= 12


async def test_3_found_down_no_tap_no_responders_briefing_only_at_60s(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt, witnessed=False)
        await rt.clock.advance(5)
        assert "cardiac_main" in rt.speaker.played()
        await rt.clock.advance(50)  # 55 s
        assert not [c for c in rt.telephony.calls if c["kind"] == "briefing"]
        await rt.clock.advance(5)  # 60 s
        assert [c["kind"] for c in rt.telephony.calls] == ["briefing"]
        await rt.clock.advance(300)
        assert wave_dispatches(rt) == []
        assert rt.store.incidents[iid]["collapse_at"] is None


async def test_4_raised_hand_is_fall_staff_then_briefing_at_60s_unless_cancelled(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(2)
        await rt.deliver(iid, {"kind": "responsive", "source": "vision", "victim_track_id": 7})
        assert rt.store.incidents[iid]["type"] == "fall"
        assert rt.speaker.played()[-1] == "fall_main"
        staff = [d for d in rt.store.dispatches.values() if d["role"] == "staff"]
        assert [d["responder_id"] for d in staff] == ["r0"]
        await rt.clock.advance(59)  # classified at 2 s: 59 s after classify
        assert not [c for c in rt.telephony.calls if c["kind"] == "briefing"]
        await rt.clock.advance(1)
        assert [c["kind"] for c in rt.telephony.calls] == ["briefing"]
        assert wave_dispatches(rt) == []

    async with runtime(tmp_path / "b") as rt:
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "responsive", "source": "vision", "victim_track_id": 7})
        await rt.clock.advance(30)
        await rt.deliver(iid, {"kind": "cancel_911", "source": "desk", "by": "staff"})
        await rt.clock.advance(120)
        assert rt.telephony.calls == []
        assert "fall_911_cancelled" in kinds(rt)


async def test_5_seizure_adds_script_and_still_escalates(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "possible_seizure", "source": "vision", "victim_track_id": 7})
        await rt.clock.advance(5)
        assert rt.speaker.plays[-1][0] == ["cardiac_main", "mod_seizure"]
        await rt.clock.advance(5)
        assert len(wave_dispatches(rt, 1)) == 4
        assert rt.store.incidents[iid]["modifiers"] == ["seizure"]


async def test_6_unsafe_scene_from_verify(tmp_path):
    verifier = FakeVerifier({"is_emergency": True, "scene_safe": False, "hazards": ["smoke"], "modifiers": []})
    async with runtime(tmp_path, verifier=verifier) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)
        assert rt.store.incidents[iid]["scene_safe"] is False
        assert "cardiac_main" not in rt.speaker.played()
        assert rt.speaker.played()[-1] == "unsafe_stay_back"
        assert "police_notified" in kinds(rt)
        await rt.clock.advance(120)
        assert rt.store.dispatches == {}


async def test_6b_unsafe_without_audio_goes_quiet(tmp_path):
    speaker = FakeSpeaker(scripts=["voice_check", "cardiac_main"])
    verifier = FakeVerifier({"scene_safe": False, "is_emergency": True, "hazards": [], "modifiers": []})
    async with runtime(tmp_path, verifier=verifier, speaker=speaker) as rt:
        await start(rt)
        await rt.clock.advance(5)
        assert rt.speaker.played() == ["voice_check"] and rt.speaker.stops >= 1


async def test_7_verify_drops_modifier_or_returns_junk_is_ignored(tmp_path):
    verifier = FakeVerifier({"is_emergency": False, "scene_safe": True, "hazards": [], "modifiers": []},
                            delay_s=3)
    async with runtime(tmp_path, verifier=verifier) as rt:
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "possible_seizure", "source": "vision", "victim_track_id": 7})
        await rt.clock.advance(10)
        state = await rt.get_state(iid)
        assert state["modifiers"] == ["seizure"] and state["playbook"] == "cardiac"
        assert len(wave_dispatches(rt, 1)) == 4  # is_emergency=false did not cancel anything

    async with runtime(tmp_path / "junk", verifier=FakeVerifier("not json at all")) as rt:
        iid = await start(rt)
        await rt.clock.advance(10)
        state = await rt.get_state(iid)
        assert state["verification"] == {"error": "invalid output"} and state["playbook"] == "cardiac"

    async with runtime(tmp_path / "down", verifier=FakeVerifier(error="LLM unreachable")) as rt:
        iid = await start(rt)
        await rt.clock.advance(10)
        assert len(wave_dispatches(rt, 1)) == 4


@pytest.mark.parametrize("at", [2, 7, 12])
async def test_8_false_alarm_at_any_point_stops_everything(tmp_path, at):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(at)
        await rt.deliver(iid, {"kind": "false_alarm", "source": "desk", "by": "desk"})
        await rt.settle()
        calls_before = len(rt.telephony.calls)
        sids = {d["call_sid"] for d in rt.store.dispatches.values() if d.get("call_sid")}
        assert sids <= set(rt.telephony.hangups)
        assert all(d["status"] == "released" for d in rt.store.dispatches.values())
        assert rt.speaker.stops >= 1
        assert rt.store.incidents[iid]["status"] == "false_alarm"
        plays = len(rt.speaker.plays)
        await rt.clock.advance(300)
        assert len(rt.telephony.calls) == calls_before and len(rt.speaker.plays) == plays
        assert rt.timers.active(iid) == []


async def test_9_two_accepts_then_third(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"})
        await rt.clock.advance(5)
        ids = [d["id"] for d in sorted(wave_dispatches(rt, 1), key=lambda d: d["responder_id"])]
        roles = []
        for did in ids[:3]:
            state = await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": did})
            d = next(x for x in state["dispatches"] if x["id"] == did)
            roles.append((d.get("role"), d["status"]))
        assert roles == [("aed_runner", "accepted"), ("patient", "accepted"), (None, "released")]
        await rt.settle()
        released = [d for d in wave_dispatches(rt) if d["status"] == "released"]
        assert len(released) == 2
        assert {d["call_sid"] for d in released if d.get("call_sid")} <= set(rt.telephony.hangups)
        await rt.clock.advance(60)
        assert len(wave_dispatches(rt)) == 4  # no second wave


async def test_10_no_accepts_three_waves_then_stop_briefing_not_delayed(tmp_path):
    async with runtime(tmp_path, responders=[responder(i) for i in range(20)]) as rt:
        await start(rt)
        await rt.clock.advance(10)
        assert len(wave_dispatches(rt, 1)) == 4
        assert [c["kind"] for c in rt.telephony.calls].count("briefing") == 1  # with wave 1, not after
        await rt.clock.advance(20)
        assert len(wave_dispatches(rt, 2)) == 4
        await rt.clock.advance(20)
        assert len(wave_dispatches(rt, 3)) == 4
        await rt.clock.advance(100)
        assert len(wave_dispatches(rt)) == 12
        assert all(d["status"] == "timeout" for d in wave_dispatches(rt))


async def test_11_races(tmp_path):
    # confirm and the auto-proceed timeout in the same tick
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)
        state = await rt.get_state(iid)
        token = state["timers"]["confirm_auto"]
        rt.clock.t = T0 + 10
        await asyncio.gather(
            rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"}),
            rt.deliver(iid, {"kind": "timeout", "source": "timer", "name": "confirm_auto", "token": token}),
        )
        await rt.settle()
        assert len(wave_dispatches(rt, 1)) == 4
        assert [c["kind"] for c in rt.telephony.calls].count("briefing") == 1
        # duplicate accept
        did = wave_dispatches(rt, 1)[0]["id"]
        a = await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": did})
        b = await rt.deliver(iid, {"kind": "accept", "source": "twilio", "dispatch_id": did})
        assert a["roles"] == b["roles"] == {"aed_runner": did and wave_dispatches(rt, 1)[0]["responder_id"]}
        # signal after resolve
        await rt.deliver(iid, {"kind": "resolve", "source": "desk", "by": "desk"})
        await rt.settle()
        events = len(rt.store.events)
        out = await rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"})
        assert out["resolved"] and len(rt.store.events) == events
        assert "resolved" in kinds(rt)
        handoff = rt.store.events_of("resolved")[0]["payload"]["handoff"]
        assert handoff["witnessed"] is True and handoff["first_instruction_s"] is not None


async def test_12_telephony_refuses_911():
    for number in ("911", "+1911", "1-911", "(911) 555-0100", "112", "999", "+44 999", "000"):
        with pytest.raises(EmergencyNumberError):
            check_destination(number, {number})
    with pytest.raises(EmergencyNumberError):
        FakeTelephony(dispatch_sim_number="911")
    tel = FakeTelephony(dispatch_sim_number="+15550001111")
    with pytest.raises(EmergencyNumberError):
        await tel.call_responder({"id": "d"}, {"phone": "911", "callable": True, "consent_calls": True})
    assert tel.calls == []
    assert await tel.call_briefing("i1")  # the sim dispatcher number is allowed


async def test_one_open_incident_per_camera(tmp_path):
    async with runtime(tmp_path) as rt:
        a = await start(rt)
        b = await start(rt)
        assert a == b and len(rt.store.incidents) == 1


async def test_milestones_drive_cpr_coaching(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)
        await rt.clock.advance(20)
        assert rt.speaker.played().count("cardiac_main") == 2  # repeats every 20 s
        await rt.deliver(iid, {"kind": "milestone", "source": "desk", "milestone": "cpr_started", "by": "desk"})
        assert rt.speaker.played()[-1] == "cardiac_cpr_coach"
        await rt.clock.advance(20)
        assert rt.speaker.played()[-1] == "cardiac_cpr_coach" and rt.speaker.played().count("cardiac_main") == 2
        await rt.deliver(iid, {"kind": "milestone", "source": "desk", "milestone": "aed_arrived", "by": "desk"})
        assert rt.speaker.played()[-1] == "cardiac_aed_arrived"
        inc = rt.store.incidents[iid]
        assert inc["cpr_started_at"] and inc["aed_arrived_at"]


async def test_all_clear_on_false_alarm_and_resolve(tmp_path):
    for kind in ("false_alarm", "resolve"):
        async with runtime(tmp_path / kind) as rt:
            iid = await start(rt)
            await rt.clock.advance(6)
            await rt.deliver(iid, {"kind": kind, "source": "desk", "by": "desk"})
            assert rt.speaker.played()[-1] == "all_clear"
            vc = rt.store.events_of("voice_check_result")[0]["payload"]
            assert vc == {"responsive": False}
            vr = rt.store.events_of("verify_result")[0]["payload"]
            assert set(vr) >= {"is_emergency", "scene_safe", "hazards", "modifiers"}
