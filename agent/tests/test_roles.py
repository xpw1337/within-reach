"""The demo flow approved by the team lead on 2026-11-14: role order, nearest first, staff accept and
the two app milestones (aed_picked_up, aed_help_started). FIXTURE VALUES only, not measurements."""

from agent.io.messaging import FakeMessenger
from agent.live import responders as rs
from agent.live.config import LiveConfig
from agent.live.playbooks import desired_script
from agent.live.reducer import apply_signal, derive_status, plan
from agent.live.state import merge_state
from agent.tests.fixtures import T0, responder, runtime
from agent.tests.test_reducer import base, end_voice_check, step, wave_state

NOW = 1_800_000_000.0
BUILDING = {"id": "b1", "lat": 29.76, "lng": -95.37, "geofence_m": 60}
CAMERA_NORTH = {"id": "cam", "lat": 29.7604, "lng": -95.37}  # about 44 m north of the building point


def person(id, role="public", cpr=False, dlat=0.0, **kw):
    base_row = {"id": id, "name": id, "phone": "+15550000000", "role": role, "cpr_trained": cpr,
                "callable": False, "consent_calls": False, "consent_location": True, "on_duty": True,
                "building_id": "b1", "last_lat": 29.76 + dlat, "last_lng": -95.37, "last_seen_at": NOW - 30}
    base_row.update(kw)
    return base_row


# ---------------------------------------------------------------------------
# Ranking (pure)
# ---------------------------------------------------------------------------


def test_incident_origin_prefers_the_camera_then_the_building():
    assert rs.incident_origin(CAMERA_NORTH, BUILDING) == (29.7604, -95.37)
    assert rs.incident_origin({"lat": None, "lng": None}, BUILDING) == (29.76, -95.37)
    assert rs.incident_origin({}, {"lat": None}) is None
    assert rs.incident_origin(None, None) is None


def test_nearest_to_the_camera_first_then_cpr_then_id():
    people = [
        person("at_building"),  # about 44 m from the camera
        person("near_cam", dlat=0.0003),  # about 11 m from the camera
        person("near_cam_cpr", cpr=True, dlat=0.0003),  # same spot, CPR-trained
        person("tenant_far", role="tenant", dlat=-0.0002),  # tenant, farthest from the camera
    ]
    origin = rs.incident_origin(CAMERA_NORTH, BUILDING)
    order = [p["id"] for p in rs.rank_eligible(people, BUILDING, NOW, cardiac=True, seen_window_s=600,
                                                origin=origin)]
    assert order == ["near_cam_cpr", "near_cam", "at_building", "tenant_far"]
    # not cardiac: CPR does not reorder, id breaks the tie
    order = [p["id"] for p in rs.rank_eligible(people, BUILDING, NOW, cardiac=False, seen_window_s=600,
                                                origin=origin)]
    assert order == ["near_cam", "near_cam_cpr", "at_building", "tenant_far"]


def test_building_point_when_the_camera_has_no_coordinates():
    people = [person("north", dlat=0.0003), person("center"), person("south", dlat=-0.0001)]
    origin = rs.incident_origin({"id": "cam"}, BUILDING)
    order = [p["id"] for p in rs.rank_eligible(people, BUILDING, NOW, cardiac=True, seen_window_s=600,
                                                origin=origin)]
    assert order == ["center", "south", "north"]
    # a responder with no position sorts after everyone with one
    assert rs.priority_key(person("x", last_lat=None), BUILDING, True, origin)[0] == float("inf")


def test_no_coordinates_falls_back_to_the_role_order():
    b = {"id": "b1", "lat": None, "lng": None}
    people = [person("pub_cpr", cpr=True), person("tenant", role="tenant"), person("pub")]
    assert rs.incident_origin({}, b) is None
    order = [p["id"] for p in rs.rank_eligible(people, b, NOW, cardiac=True, seen_window_s=600, origin=None)]
    assert order == ["tenant", "pub_cpr", "pub"]


def test_wave_size_and_staff_never_in_a_wave():
    people = [person("s", role="staff"), person("sec", role="security", dlat=0.0004),
              person("near", dlat=0.0004), person("mid", dlat=0.0002), person("far")]
    origin = rs.incident_origin(CAMERA_NORTH, BUILDING)
    w1 = rs.next_wave(people, BUILDING, NOW, cardiac=True, wave_size=1, seen_window_s=600, already_sent=[],
                      origin=origin)
    assert [p["id"] for p in w1] == ["near"]  # the building's staff and security are the staff pool
    w2 = rs.next_wave(people, BUILDING, NOW, cardiac=True, wave_size=4, seen_window_s=600,
                      already_sent=["near"], origin=origin)
    assert [p["id"] for p in w2] == ["mid", "far"]


def test_staff_pool_nearest_first():
    people = [person("staff_far", role="staff", dlat=-0.0003), person("sec_near", role="security", dlat=0.0004),
              person("staff_mid", role="staff")]
    origin = rs.incident_origin(CAMERA_NORTH, BUILDING)
    assert [p["id"] for p in rs.staff_to_alert(people, BUILDING, origin=origin)] == [
        "sec_near", "staff_mid", "staff_far"]
    # no coordinates: staff before security, then id (unchanged)
    assert [p["id"] for p in rs.staff_to_alert(people, BUILDING)] == ["staff_far", "staff_mid", "sec_near"]


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------


def test_no_aed_route_first_accept_is_patient_and_the_rest_are_released():
    s = wave_state()
    s = dict(s, routes={})  # no camera_routes row with target aed
    s, tr = step(s, "accept", ts=107.0, dispatch_id="d2")
    assert s["roles"] == {"patient": "r2"}
    by_id = {d["id"]: d for d in s["dispatches"]}
    assert by_id["d2"]["role"] == "patient" and by_id["d2"]["status"] == "accepted"
    assert {by_id[i]["status"] for i in ("d1", "d3", "d4")} == {"released"}
    assert {e["call_sid"] for e in tr.effects if e["type"] == "hangup"} == {"CA1", "CA3"}
    assert "wave_1" not in s["timers"] and "dispatch" not in plan(s)
    _, tr = step(s, "accept", ts=108.0, dispatch_id="d4")
    assert not tr.applied  # released stays released


def test_aed_route_roles_filled_then_late_accept_is_released():
    s = wave_state()
    s, _ = step(s, "accept", ts=107.0, dispatch_id="d1")
    assert s["roles"] == {"aed_runner": "r1"}
    # wave 1 times out with two dispatches still open
    s, _ = step(s, "timeout", ts=127.0, name="wave_1", token="tw1")
    assert "dispatch" in plan(s)  # the patient role is still open: next wave
    s, _ = step(s, "accept", ts=128.0, dispatch_id="d3")  # timed out, still accepted
    assert s["roles"] == {"aed_runner": "r1", "patient": "r3"}
    by_id = {d["id"]: d for d in s["dispatches"]}
    assert by_id["d2"]["status"] == "released" and by_id["d4"]["status"] == "released"
    assert "dispatch" not in plan(s)


def test_staff_accept_acknowledges_without_taking_a_helper_role():
    s = wave_state()
    s = merge_state(s, {"dispatches": [{"id": "ds", "responder_id": "r0", "wave": 0, "status": "sent",
                                        "role": "staff", "call_sid": None}], "staff_alerted": True})
    s, tr = step(s, "accept", ts=107.0, dispatch_id="ds")
    assert tr.applied
    d = next(x for x in s["dispatches"] if x["id"] == "ds")
    assert d["status"] == "accepted" and d["role"] == "staff" and d["responded_at"] == 107.0
    assert s["roles"] == {} and s.get("first_accept_at") is None
    (ev,) = tr.events
    assert ev["actor"] == "responder:r0" and ev["kind"] == "dispatch_accepted"
    assert ev["payload"]["role"] == "staff" and ev["payload"]["dispatch_id"] == "ds"
    assert all(x["status"] == "sent" for x in s["dispatches"] if x["id"] != "ds")  # nobody released
    _, tr = step(s, "accept", ts=108.0, dispatch_id="ds")
    assert not tr.applied  # idempotent
    s, tr = step(s, "arrived", ts=130.0, dispatch_id="ds")
    assert next(x for x in s["dispatches"] if x["id"] == "ds")["status"] == "arrived"


def test_app_milestones_are_recorded_only_and_idempotent():
    s = end_voice_check(base())
    s = merge_state(s, {"spoken_key": ["cardiac_main"], "timers": {"announce_repeat": "ta"}})
    script, status, todo = desired_script(s), derive_status(s), plan(s)
    for i, kind in enumerate(("aed_picked_up", "aed_help_started")):
        s, tr = step(s, "milestone", ts=120.0 + i, milestone=kind, by="r1")
        assert tr.applied and s["milestones"][kind] == 120.0 + i
        assert tr.events == [{"actor": "desk", "kind": "milestone", "payload": {"kind": kind, "by": "r1"}}]
        assert tr.effects == [] and "announce_repeat" in s["timers"]  # the speaker keeps repeating
        assert set(tr.updates) == {"milestones"}
        assert desired_script(s) == script and derive_status(s) == status and plan(s) == todo
        _, again = step(s, "milestone", ts=130.0, milestone=kind, by="r1")
        assert not again.applied  # idempotent


def test_app_milestone_after_resolve_is_ignored():
    s = end_voice_check(base())
    s, _ = step(s, "resolve", ts=200.0, by="desk")
    tr = apply_signal(s, {"kind": "milestone", "ts": 201.0, "milestone": "aed_picked_up"})
    assert not tr.applied


# ---------------------------------------------------------------------------
# Graph with fakes
# ---------------------------------------------------------------------------


async def start(rt):
    iid, _ = await rt.start_incident(camera_id="cam-test", victim_track_id=7, witnessed=True, event_ts=T0,
                                     frame=b"jpeg")
    await rt.settle()
    return iid


def wave(rt):
    return [d for d in rt.store.dispatches.values() if d.get("role") != "staff"]


async def test_graph_nearest_helper_and_nearest_staff_with_wave_size_one(tmp_path):
    people = [responder(0, "staff", last_lat=29.7600), responder(5, "security", last_lat=29.7603),
              responder(1, "public", last_lat=29.7600), responder(2, "public", last_lat=29.7603),
              responder(3, "public", last_lat=29.7601)]
    async with runtime(tmp_path, responders=people, cfg=LiveConfig(wave_size=1)) as rt:
        rt.store.cameras["cam-test"].update(lat=29.7604, lng=-95.37)
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"})
        await rt.clock.advance(5)
        staff = [d["responder_id"] for d in rt.store.dispatches.values() if d["role"] == "staff"]
        assert staff == ["r5", "r0"]  # both alerted, nearest to the camera first
        assert [d["responder_id"] for d in wave(rt)] == ["r2"]  # the nearest helper only
        await rt.clock.advance(20)  # wave 1 times out: next nearest
        assert [d["responder_id"] for d in wave(rt) if d["wave"] == 2] == ["r3"]


async def test_graph_staff_accept_is_on_the_row_and_the_timeline(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)  # classify: staff alert to r0
        staff = next(d for d in rt.store.dispatches.values() if d["role"] == "staff")
        state = await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": staff["id"]})
        assert rt.store.dispatches[staff["id"]]["status"] == "accepted"
        assert rt.store.dispatches[staff["id"]]["role"] == "staff"
        ev = [e for e in rt.store.events_of("dispatch_accepted") if e["payload"]["dispatch_id"] == staff["id"]]
        assert len(ev) == 1 and ev[0]["actor"] == "responder:r0" and ev[0]["payload"]["role"] == "staff"
        assert state["roles"] == {}


async def test_graph_no_aed_route_patient_then_released_with_stand_down_text(tmp_path):
    people = [responder(0, "staff")] + [responder(i, "public", callable_=(i in (1, 2))) for i in range(1, 6)]
    m = FakeMessenger()
    async with runtime(tmp_path, routes=[], responders=people, messenger=m) as rt:
        iid = await start(rt)
        await rt.deliver(iid, {"kind": "confirm", "source": "desk", "by": "desk"})
        await rt.clock.advance(5)
        await rt.settle()
        assert "If you can help, you will go to the person." in m.texts_to("+15550100002")[0]
        by = {d["responder_id"]: d for d in wave(rt)}
        state = await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": by["r1"]["id"]})
        assert state["roles"] == {"patient": "r1"}
        await rt.settle()
        assert all(rt.store.dispatches[by[r]["id"]]["status"] == "released" for r in ("r2", "r3", "r4"))
        assert m.texts_to("+15550100001")[-1].startswith("You are going to the person.")
        assert "Another responder" not in m.texts_to("+15550100001")[-1]
        assert m.texts_to("+15550100002")[-1] == "A responder is already on the way. Thank you, you can stand down."
        out = await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": by["r2"]["id"]})
        assert next(d for d in out["dispatches"] if d["id"] == by["r2"]["id"])["status"] == "released"
        await rt.clock.advance(60)
        assert len(wave(rt)) == 4  # no second wave


async def test_graph_app_milestones_on_the_timeline_only(tmp_path):
    async with runtime(tmp_path) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)
        plays = list(rt.speaker.played())
        before = dict(rt.store.incidents[iid])
        for kind in ("aed_picked_up", "aed_picked_up", "aed_help_started", "aed_help_started"):
            await rt.deliver(iid, {"kind": "milestone", "source": "desk", "milestone": kind, "by": "r1"})
        ms = [e for e in rt.store.events_of("milestone")]
        assert [e["payload"] for e in ms] == [{"kind": "aed_picked_up", "by": "r1"},
                                             {"kind": "aed_help_started", "by": "r1"}]
        assert rt.speaker.played() == plays  # no script switch
        assert rt.store.incidents[iid] == before  # no column changes
        state = await rt.get_state(iid)
        assert set(state["milestones"]) == {"aed_picked_up", "aed_help_started"}
