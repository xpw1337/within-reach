from datetime import UTC

from agent.live import responders as rs

NOW = 1_800_000_000.0
BUILDING = {"id": "b1", "lat": 29.76, "lng": -95.37, "geofence_m": 60}


def r(id, role="public", cpr=False, callable_=False, consent_calls=False, seen_ago=30, dlat=0.0, **kw):
    base = {
        "id": id, "name": id, "phone": "+15550000000", "role": role, "cpr_trained": cpr, "callable": callable_,
        "consent_calls": consent_calls, "consent_location": True, "on_duty": True, "building_id": "b1",
        "last_lat": 29.76 + dlat, "last_lng": -95.37, "last_seen_at": NOW - seen_ago,
    }
    base.update(kw)
    return base


def test_eligibility_rules():
    assert rs.is_eligible(r("a"), BUILDING, NOW, 600)
    assert not rs.is_eligible(r("a", consent_location=False), BUILDING, NOW, 600)
    assert not rs.is_eligible(r("a", on_duty=False), BUILDING, NOW, 600)
    assert not rs.is_eligible(r("a", seen_ago=600), BUILDING, NOW, 600)  # seen < 10 min required
    assert not rs.is_eligible(r("a", last_seen_at=None), BUILDING, NOW, 600)
    assert not rs.is_eligible(r("a", dlat=0.001), BUILDING, NOW, 600)  # about 111 m away
    assert rs.is_eligible(r("a", dlat=0.0004), BUILDING, NOW, 600)  # about 44 m away


def test_iso_last_seen_is_parsed():
    from datetime import datetime

    iso = datetime.fromtimestamp(NOW - 60, tz=UTC).isoformat()
    assert rs.is_eligible(r("a", last_seen_at=iso), BUILDING, NOW, 600)


def test_no_building_coordinates_falls_back_to_building_id():
    b = {"id": "b1", "lat": None, "lng": None}
    assert rs.in_geofence(r("a"), b)
    assert not rs.in_geofence(r("a", building_id="other"), b)


def test_priority_role_then_cpr_for_cardiac():
    people = [
        r("pub_cpr", "public", cpr=True),
        r("tenant", "tenant"),
        r("sec", "security"),
        r("staff_nocpr", "staff"),
        r("staff_cpr", "staff", cpr=True),
    ]
    order = [p["id"] for p in rs.rank_eligible(people, BUILDING, NOW, cardiac=True, seen_window_s=600)]
    assert order == ["staff_cpr", "staff_nocpr", "sec", "tenant", "pub_cpr"]
    # not cardiac: CPR does not reorder within a role (tie broken by distance, then id)
    order = [p["id"] for p in rs.rank_eligible(people, BUILDING, NOW, cardiac=False, seen_window_s=600)]
    assert order[:2] == ["staff_cpr", "staff_nocpr"] or order[:2] == ["staff_nocpr", "staff_cpr"]


def test_waves_never_repeat_people():
    people = [r(f"p{i}") for i in range(10)]
    w1 = rs.next_wave(people, BUILDING, NOW, cardiac=True, wave_size=4, seen_window_s=600, already_sent=[])
    w2 = rs.next_wave(people, BUILDING, NOW, cardiac=True, wave_size=4, seen_window_s=600,
                      already_sent=[p["id"] for p in w1])
    w3 = rs.next_wave(people, BUILDING, NOW, cardiac=True, wave_size=4, seen_window_s=600,
                      already_sent=[p["id"] for p in w1 + w2])
    assert len(w1) == 4 and len(w2) == 4 and len(w3) == 2
    assert not {p["id"] for p in w1} & {p["id"] for p in w2}


def test_can_call_needs_callable_and_consent():
    assert rs.can_call(r("a", callable_=True, consent_calls=True))
    assert not rs.can_call(r("a", callable_=True, consent_calls=False))
    assert not rs.can_call(r("a", callable_=False, consent_calls=True))


def test_roles_aed_runner_then_patient_when_an_aed_route_is_mapped():
    routes = {"aed": {"distance_m": 14, "directions": "left"}}
    assert rs.open_role({}, routes) == "aed_runner"
    assert rs.open_role({"aed_runner": "x"}, routes) == "patient"
    assert rs.open_role({"aed_runner": "x", "patient": "y"}, routes) is None
    assert rs.roles_filled({"aed_runner": "x", "patient": "y"}, routes)
    assert not rs.roles_filled({"aed_runner": "x"}, routes)


def test_roles_patient_only_without_an_aed_route():
    for routes in ({}, None, {"exit": {"distance_m": 5}}):
        assert rs.open_role({}, routes) == "patient"
        assert rs.open_role({"patient": "x"}, routes) is None
        assert rs.roles_filled({"patient": "x"}, routes)


def test_staff_alert_targets():
    people = [r("s", "staff"), r("sec", "security"), r("t", "tenant"), r("off", "staff", on_duty=False),
              r("other", "staff", building_id="b2")]
    assert [p["id"] for p in rs.staff_to_alert(people, BUILDING)] == ["s", "sec"]
