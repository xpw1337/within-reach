"""The live SOS path end to end with fakes: no network, no model."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from agent.main import create_app
from agent.sos.geo import decode_polyline, haversine_m, offset, path_hits_circle
from agent.sos.hub import Hub
from agent.sos.places import parse_overpass
from agent.sos.routing import Router
from agent.sos.settings import SosSettings

CAM = (40.3500, -74.6500)


class FakePlaces:
    def __init__(self, items):
        self.items = items

    async def osm(self, lat, lng):
        return list(self.items)

    async def _http(self):
        raise RuntimeError("offline")

    async def aclose(self):
        pass


def settings(tmp_path, **kw) -> SosSettings:
    s = SosSettings()
    s.offline = True
    s.state_file = tmp_path / "state.json"
    s.camera_lat = s.camera_lng = None
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def make_hub(tmp_path, places=(), **kw) -> Hub:
    s = settings(tmp_path, **kw)
    hub = Hub(s, places=FakePlaces(places), router=Router(s), use_llm=False, call_pace_s=0.01)
    hub.set_camera("cam", *CAM, 5, "the lobby")
    return hub


def phone(hub: Hub, rid: str, dist_m: float | None, bearing: float = 90):
    sent: list[dict] = []

    async def send(msg):
        sent.append(msg)

    hub.responder_hello(rid, rid.title(), send)
    if dist_m is not None:
        lat, lng = offset(*CAM, bearing, dist_m)
        hub.responder_update(rid, {"lat": lat, "lng": lng})
    return sent


def pending(hub: Hub):
    return next(o for o in hub.incident["offers"] if o["status"] == "sent")


async def settle():
    for _ in range(5):
        await asyncio.sleep(0.02)


async def test_alert_goes_to_nearest_then_next_on_decline(tmp_path):
    hub = make_hub(tmp_path)
    phone(hub, "far", 300)
    phone(hub, "near", 40)
    phone(hub, "nowhere", None)
    await hub.open_incident("fall", "cam", witnessed=True)
    assert pending(hub)["responder_id"] == "near"
    assert hub.respond(pending(hub)["id"], "near", "declined")["ok"]
    assert pending(hub)["responder_id"] == "far"
    # Someone else cannot answer for them.
    assert not hub.respond(pending(hub)["id"], "near", "accepted")["ok"]
    hub.respond(pending(hub)["id"], "far", "declined")
    assert pending(hub)["responder_id"] == "nowhere"  # no location: asked last
    hub.respond(pending(hub)["id"], "nowhere", "declined")
    assert hub.incident["status"] == "no_responders"
    await hub.aclose()


async def test_timeout_moves_on(tmp_path):
    hub = make_hub(tmp_path, accept_timeout_s=0.05)
    phone(hub, "a", 10)
    phone(hub, "b", 20)
    await hub.open_incident("fall", "cam")
    await asyncio.sleep(0.12)
    statuses = {o["responder_id"]: o["status"] for o in hub.incident["offers"]}
    assert statuses["a"] == "timeout" and statuses["b"] in ("sent", "timeout")
    await hub.aclose()


async def test_off_duty_and_disconnected_are_skipped(tmp_path):
    hub = make_hub(tmp_path)
    s1 = phone(hub, "off", 5)
    hub.responder_update("off", {"on_duty": False})

    async def other(msg):
        pass

    phone(hub, "gone", 6)
    hub.responder_gone("gone", hub.phone_sockets["gone"])
    phone(hub, "ok", 50)
    await hub.open_incident("fall", "cam")
    assert pending(hub)["responder_id"] == "ok"
    assert s1 is not None
    await hub.aclose()


async def test_accept_gives_plan_with_aed_on_the_way(tmp_path):
    aed_lat, aed_lng = offset(*CAM, 90, 20)
    places = [{"id": "osm-1", "kind": "aed", "lat": aed_lat, "lng": aed_lng, "label": "Front desk",
               "source": "openstreetmap"}]
    hub = make_hub(tmp_path, places)
    phone(hub, "me", 45)
    await hub.open_incident("fall", "cam", witnessed=True)
    await settle()
    hub.respond(pending(hub)["id"], "me", "accepted")
    await settle()
    plan = hub.incident["plan"]
    assert [leg["kind"] for leg in plan["legs"]] == ["aed", "person"]
    assert hub.incident["status"] == "en_route"
    view = hub.phone_state("me")
    assert view["mission"]["plan"]["legs"][-1]["kind"] == "person"
    assert hub.collected("me", "aed")["ok"]
    await settle()
    assert [leg["kind"] for leg in hub.incident["plan"]["legs"]] == ["person"]
    assert hub.arrived("me")["ok"] and hub.incident["status"] == "on_scene"
    await hub.aclose()


async def test_far_aed_is_not_a_detour(tmp_path):
    aed = offset(*CAM, 270, 900)
    hub = make_hub(tmp_path, [{"id": "x", "kind": "aed", "lat": aed[0], "lng": aed[1], "label": "Far"}])
    phone(hub, "me", 30)
    await hub.open_incident("fall", "cam")
    await settle()
    hub.respond(pending(hub)["id"], "me", "accepted")
    await settle()
    plan = hub.incident["plan"]
    assert [leg["kind"] for leg in plan["legs"]] == ["person"]
    assert plan["aed_too_far"]["id"] == "x"
    await hub.aclose()


async def test_fire_adds_extinguisher_outside_the_fire_zone(tmp_path):
    inside = offset(*CAM, 0, 5)  # within the 15 m fire radius: unusable
    outside = offset(*CAM, 90, 30)
    places = [
        {"id": "in", "kind": "extinguisher", "lat": inside[0], "lng": inside[1], "label": "next to fire"},
        {"id": "out", "kind": "extinguisher", "lat": outside[0], "lng": outside[1], "label": "hallway"},
    ]
    hub = make_hub(tmp_path, places)
    phone(hub, "me", 50)
    await hub.open_incident("fall", "cam")
    await settle()
    hub.respond(pending(hub)["id"], "me", "accepted")
    hub.set_fire({"source": "camera", "label": "fire"})
    await settle()
    legs = hub.incident["plan"]["legs"]
    assert legs[0]["kind"] == "extinguisher" and legs[0]["to"]["id"] == "out"
    assert legs[-1]["kind"] == "person"
    assert any("fire" in s["text"].lower() for s in legs[-1]["steps"])
    hub.clear_fire("camera")
    await settle()
    assert [leg["kind"] for leg in hub.incident["plan"]["legs"]] == ["person"]
    await hub.aclose()


async def test_simulated_911_call_runs_and_reports_updates(tmp_path):
    hub = make_hub(tmp_path)
    phone(hub, "me", 20)
    await hub.open_incident("fall", "cam", witnessed=True)
    await asyncio.sleep(0.3)
    lines = hub.incident["call"]["lines"]
    assert lines[0]["who"] == "system" and "SIMULATED" in lines[0]["text"]
    assert any(line["who"] == "dispatcher" for line in lines)
    assert any(line["who"] == "ai" and "lobby" in line["text"] for line in lines)
    hub.respond(pending(hub)["id"], "me", "accepted")
    await asyncio.sleep(0.2)
    assert any("accepted" in line["text"] for line in hub.incident["call"]["lines"] if line["who"] == "ai")
    hub.resolve("test")
    await asyncio.sleep(0.05)
    assert hub.incident["call"]["status"] == "ended"
    await hub.aclose()


async def test_new_phone_gets_alert_when_nobody_was_available(tmp_path):
    hub = make_hub(tmp_path)
    await hub.open_incident("fall", "cam")
    assert hub.incident["status"] == "no_responders"
    phone(hub, "late", 80)
    assert pending(hub)["responder_id"] == "late"
    await hub.aclose()


async def test_no_camera_location_is_an_error(tmp_path):
    s = settings(tmp_path)
    hub = Hub(s, places=FakePlaces([]), use_llm=False)
    with pytest.raises(LookupError):
        await hub.open_incident("fall", "cam")
    await hub.aclose()


def test_geo_helpers():
    a = offset(*CAM, 45, 100)
    assert abs(haversine_m(*CAM, *a) - 100) < 0.5
    assert decode_polyline("_izlhA~rlgdF_{geC~ywl@_kwzCn`{nI", 6)[0] == pytest.approx((38.5, -120.2))
    assert path_hits_circle([offset(*CAM, 270, 50), offset(*CAM, 90, 50)], CAM, 10)
    assert not path_hits_circle([offset(*CAM, 0, 50), offset(*CAM, 0, 80)], CAM, 10)


def test_parse_overpass():
    data = {"elements": [
        {"type": "node", "id": 1, "lat": 1.0, "lon": 2.0,
         "tags": {"emergency": "defibrillator", "defibrillator:location": "Lobby wall"}},
        {"type": "way", "id": 2, "center": {"lat": 3.0, "lon": 4.0}, "tags": {"emergency": "fire_extinguisher"}},
        {"type": "node", "id": 3, "lat": 1.0, "lon": 2.0, "tags": {"emergency": "fire_hydrant"}},
    ]}
    out = parse_overpass(data)
    assert [(p["kind"], p["label"]) for p in out] == [("aed", "Lobby wall"), ("extinguisher", "Fire extinguisher")]


def test_http_and_websocket_flow(tmp_path):
    hub = Hub(settings(tmp_path), places=FakePlaces([]), use_llm=False, call_pace_s=0.01)
    app = create_app(hub)
    with TestClient(app) as client:
        assert client.post("/events", json={"camera_id": "cam", "kind": "person_down"}).status_code == 409
        assert client.put("/sos/cameras/cam", json={"lat": CAM[0], "lng": CAM[1], "label": "lab"}).status_code == 200
        with client.websocket_connect("/sos/ws/console") as console, client.websocket_connect("/sos/ws/phone") as ph:
            assert console.receive_json()["type"] == "state"
            lat, lng = offset(*CAM, 90, 25)
            ph.send_json({"type": "hello", "id": "p1", "name": "Sam", "lat": lat, "lng": lng})
            assert ph.receive_json()["type"] == "state"
            r = client.post("/events", json={"camera_id": "cam", "kind": "person_down", "witnessed": True,
                                             "victim_track_id": 3})
            assert r.status_code == 200
            offer = None
            for _ in range(20):
                msg = ph.receive_json()
                if msg.get("offer"):
                    offer = msg["offer"]
                    break
            assert offer and offer["kind"] == "fall" and offer["distance_m"] == 25
            ph.send_json({"type": "accept", "offer_id": offer["id"]})
            for _ in range(30):
                msg = ph.receive_json()
                if msg.get("type") == "result":
                    assert msg["ok"]
                if msg.get("mission") and msg["mission"].get("plan"):
                    break
            assert msg["mission"]["plan"]["legs"][-1]["kind"] == "person"
        assert client.post("/sos/fire", json={}).status_code == 200
        assert client.get("/sos/state").json()["incident"]["fire"]["active"]
        assert client.post("/sos/reset").json()["ok"]


class FakeTexter:
    configured = True

    def __init__(self):
        self.sent = []

    async def send(self, to, text, key):
        from agent.sos.texts import TextResult

        self.sent.append((to, text, key))
        return TextResult(True, id="pho_msg_1")

    async def aclose(self):
        pass


class FakeCaller:
    configured = True
    token = ""
    public_url = ""

    def __init__(self):
        self.calls = []

    async def call(self, to, text, offer_id):
        from agent.sos.calls import CallResult

        self.calls.append((to, text, offer_id))
        return CallResult(True, sid="CA123")

    async def aclose(self):
        pass


async def test_alert_also_phones_the_responder_even_with_the_app_closed(tmp_path):
    s = settings(tmp_path)
    caller = FakeCaller()
    hub = Hub(s, places=FakePlaces([]), router=Router(s), use_llm=False, call_pace_s=0.01, caller=caller)
    hub.set_camera("cam", *CAM, 5, "the lobby")
    phone(hub, "me", 30)
    hub.responder_update("me", {"phone": "(609) 555-0142"})
    hub.responder_gone("me", hub.phone_sockets["me"])  # app closed
    await hub.open_incident("fall", "cam")
    await settle()
    assert pending(hub)["responder_id"] == "me"
    assert caller.calls and caller.calls[0][0] == "+16095550142"
    assert "collapsed" in caller.calls[0][1] and "the lobby" in caller.calls[0][1]
    assert hub.console_state()["responders"][0]["phone"] == "•••0142"
    await hub.aclose()


def test_phone_numbers_are_normalized_and_emergency_numbers_refused():
    from agent.sos.calls import Caller, normalize_phone

    assert normalize_phone("609-555-0142") == "+16095550142"
    assert normalize_phone("+44 20 7946 0958") == "+442079460958"
    assert normalize_phone("911") is None and normalize_phone("112") is None
    assert normalize_phone("hello") is None
    xml = Caller().twiml("Someone fell <here>", "o1")
    assert "&lt;here&gt;" in xml and "911" not in xml


def test_gather_accepts_from_the_keypad(tmp_path):
    s = settings(tmp_path)
    hub = Hub(s, places=FakePlaces([]), use_llm=False, call_pace_s=0.01, caller=FakeCaller())
    with TestClient(create_app(hub)) as client:
        client.put("/sos/cameras/cam", json={"lat": CAM[0], "lng": CAM[1]})
        with client.websocket_connect("/sos/ws/phone") as ph:
            lat, lng = offset(*CAM, 90, 20)
            ph.send_json({"type": "hello", "id": "p1", "name": "Sam", "lat": lat, "lng": lng, "phone": "6095550142"})
            ph.receive_json()
            client.post("/sos/simulate/fall", json={})
            offer_id = client.get("/sos/state").json()["incident"]["offers"][0]["id"]
            r = client.post(f"/sos/twilio/gather/{offer_id}", data={"Digits": "1"})
            assert r.status_code == 200 and "Thank you" in r.text
            assert client.get("/sos/state").json()["incident"]["status"] == "en_route"


def test_calls_go_through_the_photon_number_over_sip(monkeypatch):
    from agent.sos.calls import Caller

    for k, v in {"SOS_CALLS": "on", "TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM_NUMBER": "",
                 "PHOTON_NUMBER": "+16095550100", "PHOTON_SIP_SERVER": "sip.example.com:5061",
                 "PHOTON_SIP_USERNAME": "u", "PHOTON_SIP_PASSWORD": "p"}.items():
        monkeypatch.setenv(k, v)
    c = Caller()
    assert c.configured and c.via_photon
    r = c.route("+16095550142")
    assert r["To"] == "sip:+16095550142@sip.example.com:5061;transport=tls;secure=true"
    assert r["From"] == "+16095550100" and r["SipAuthUsername"] == "u"


async def test_alert_also_texts_the_responder(tmp_path):
    s = settings(tmp_path)
    texter = FakeTexter()
    caller = FakeCaller()
    caller.configured = False
    hub = Hub(s, places=FakePlaces([]), router=Router(s), use_llm=False, call_pace_s=0.01, caller=caller, texter=texter)
    hub.set_camera("cam", *CAM, 5, "the lobby")
    phone(hub, "me", 40)
    hub.responder_update("me", {"phone": "609 555 0142"})
    hub.responder_gone("me", hub.phone_sockets["me"])  # app closed: the text is what reaches them
    await hub.open_incident("fall", "cam")
    await settle()
    assert texter.sent and texter.sent[0][0] == "+16095550142"
    assert "collapsed" in texter.sent[0][1] and "Open the Within Reach app" in texter.sent[0][1]
    assert pending(hub)["text"] == "sent"
    assert any("Texted" in t["text"] for t in hub.incident["timeline"])
    await hub.aclose()
