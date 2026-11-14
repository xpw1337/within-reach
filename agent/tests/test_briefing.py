from agent.live.briefing import briefing_parts, build_briefing, spoken_duration

STATE = {
    "type": "cardiac",
    "witnessed": True,
    "collapse_at": 1000.0,
    "detected_at": 1005.0,
    "camera": {"floor": 1, "landmark": "east elevators"},
    "building": {
        "address": "1 Test St",
        "ems_door": {"desc": "north lobby doors", "staging": {"desc": "loading bay"}},
        "monitoring_callback": "+1 555 0100",
    },
    "routes": {"aed": {"distance_m": 14.2, "directions": "left of the elevators"}},
    "milestones": {},
    "roles": {},
    "modifiers": ["seizure"],
    "hazards": [],
    "scene_safe": True,
}


def test_order_matches_spec():
    parts = briefing_parts(STATE, now=1095.0)
    assert parts[0] == "Possible cardiac arrest, witnessed collapse."
    assert parts[1] == "Location: 1 Test St, floor 1, by east elevators."
    assert parts[2] == "Collapse 1 minute 35 seconds ago."
    assert parts[3] == "CPR not confirmed yet, nearest AED visible in the scan is 14 meters away."
    assert parts[4] == "Possible seizure."
    assert parts[5] == "EMS entrance: north lobby doors, ambulance staging: loading bay."
    assert parts[6] == "Callback for the caller of record: 1 5 5 5 0 1 0 0."
    assert build_briefing(STATE, 1095.0) == " ".join(parts)


def test_found_down_and_status_variants():
    s = dict(STATE, witnessed=False, collapse_at=None, modifiers=[], scene_safe=False, hazards=["smoke"],
             milestones={"cpr_started": 1050.0}, roles={"aed_runner": "r2"},
             building={"name": "Gym"})
    parts = briefing_parts(s, now=1065.0)
    assert parts[0] == "Possible cardiac arrest, found down."
    assert parts[1] == "Location: Gym, floor 1, by east elevators."
    assert parts[2] == "Time of collapse unknown, found down 1 minute 0 seconds ago."
    assert parts[3] == "CPR started 15 seconds ago, a responder is bringing the AED."
    assert parts[4].startswith("Scene reported unsafe") and "hazards reported: smoke" in parts[4]
    assert parts[5] == "EMS entrance not mapped."
    assert parts[6] == "No callback number on file."


def test_no_aed_wording_says_visible_in_the_scan():
    s = dict(STATE, routes={})
    assert "no AED visible in the scan" in briefing_parts(s, 1001.0)[3]


def test_fall_type_and_vexcel_parking_fallback():
    s = dict(STATE, type="fall", building={"ems_door": {"desc": "door A"},
                                           "vexcel": {"ambulance_parking": [{"desc": "lot B"}]}})
    parts = briefing_parts(s, 1001.0)
    assert parts[0] == "Fall, the person is responsive, witnessed collapse."
    assert parts[5] == "EMS entrance: door A, ambulance staging: lot B."


def test_spoken_duration():
    assert spoken_duration(1) == "1 second"
    assert spoken_duration(61) == "1 minute 1 second"
    assert spoken_duration(125) == "2 minutes 5 seconds"
