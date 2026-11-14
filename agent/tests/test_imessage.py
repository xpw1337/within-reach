"""iMessage on the live path (FakeMessenger) and POST /photon/webhook. FIXTURE VALUES only."""

import asyncio
import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest

from agent.api.photon import SignatureError, parse_reply, verify_signature
from agent.io.messaging import FakeMessenger
from agent.io.telephony import FakeTelephony
from agent.live.imessage import BRIEFING_TEXT_FALLBACK_S
from agent.main import create_app
from agent.tests.fixtures import T0, default_responders, responder, runtime

SIM = "+15550001111"
SECRET = "whsec_" + base64.b64encode(b"within-reach-test-signing-key-01").decode()
SPACE = "pho_spc_0" + "d" * 25
AGENT = "pho_usr_0" + "b" * 25


def photon_events(rt, kind=None):
    return [e for e in rt.store.events if e["actor"] == "photon" and (kind is None or e["kind"] == kind)]


def purposes(rt, kind="imessage_sent"):
    return [e["payload"]["purpose"] for e in photon_events(rt, kind)]


def wave(rt):
    return sorted((d for d in rt.store.dispatches.values() if d.get("role") != "staff"), key=lambda d: d["id"])


async def start(rt, witnessed=True):
    iid, _ = await rt.start_incident(camera_id="cam-test", victim_track_id=7, witnessed=witnessed,
                                     event_ts=T0, frame=b"jpeg")
    await rt.settle()
    return iid


def stop_background(rt):
    for task in list(rt._tasks):
        task.cancel()


# ---------------------------------------------------------------------------
# Alerts, channel, briefing
# ---------------------------------------------------------------------------


async def test_alert_goes_with_the_app_alert_and_the_call(tmp_path):
    m = FakeMessenger()
    async with runtime(tmp_path, messenger=m) as rt:
        iid = await start(rt)
        await rt.clock.advance(5)  # classify: staff alert
        staff_rows = [d for d in rt.store.dispatches.values() if d["role"] == "staff"]
        assert [d["channel"] for d in staff_rows] == ["imessage"]  # r0 staff, callable: never called
        assert m.texts_to("+15550100000")[0].startswith("Within Reach staff alert. Possible cardiac arrest")
        assert not m.texts_to("+15550100001")  # no responder text before the gate opens
        await rt.clock.advance(5)  # auto-proceed: wave 1 + briefing
        r1 = next(d for d in wave(rt) if d["responder_id"] == "r1")
        assert r1["channel"] == "call" and r1["call_sid"]  # a call was placed: stays "call"
        others = [d for d in wave(rt) if d["responder_id"] != "r1"]
        assert others and all(d["channel"] == "app" for d in others)  # not callable: no text either
        (alert,) = m.texts_to("+15550100001")
        assert "east elevators at Test Gym" in alert and "(14 meters, left of the elevators)" in alert
        assert "Reply 1 to help. Reply 2 if you can't." in alert
        # FakeTelephony does not ring: the briefing text goes out right after the call attempt
        (briefing,) = m.texts_to(SIM)
        spoken = rt.store.events_of("ems_briefed")[0]["payload"]["briefing_text"]
        assert briefing.endswith(spoken) and briefing.startswith("Within Reach 911 briefing")
        assert sorted(purposes(rt)) == ["alert", "briefing", "staff_alert"]
        sent = photon_events(rt, "imessage_sent")
        assert all(e["incident_id"] == iid and e["payload"]["message_id"] for e in sent)
        assert "+1555" not in json.dumps([e["payload"] for e in photon_events(rt)])  # no phone numbers


async def test_channel_is_imessage_only_when_no_call_was_placed(tmp_path):
    async with runtime(tmp_path, messenger=FakeMessenger(), telephony=FakeTelephony(fail=True)) as rt:
        await start(rt)
        await rt.clock.advance(10)
        r1 = next(d for d in wave(rt) if d["responder_id"] == "r1")
        assert r1["channel"] == "imessage" and r1["call_sid"] is None
        sent = [e for e in rt.store.events_of("dispatch_sent") if e["payload"]["dispatch_id"] == r1["id"]]
        assert sent[0]["payload"]["channel"] == "imessage"


async def test_found_down_without_a_confirm_never_texts_strangers(tmp_path):
    m = FakeMessenger()
    async with runtime(tmp_path, messenger=m) as rt:
        await start(rt, witnessed=False)
        await rt.clock.advance(120)
        assert wave(rt) == []
        assert "alert" not in purposes(rt)
        assert purposes(rt).count("briefing") == 1  # 911 briefing only, after 60 s
        assert not m.texts_to("+15550100001")


@pytest.mark.parametrize("bad", ["hang", "fail"])
async def test_a_broken_messenger_never_blocks_calls_or_the_briefing(tmp_path, bad):
    m = FakeMessenger(**{bad: True})
    async with runtime(tmp_path, messenger=m) as rt:
        iid = await start(rt)
        await rt.clock.advance(10)
        assert len(wave(rt)) == 4
        assert [c["kind"] for c in rt.telephony.calls].count("briefing") == 1
        assert [c["kind"] for c in rt.telephony.calls].count("responder") == 1
        assert rt.store.incidents[iid]["ems_notified_at"] is not None
        assert rt.speaker.played()[:2] == ["voice_check", "cardiac_main"]
        assert purposes(rt) == []
        if bad == "fail":
            assert sorted(purposes(rt, "imessage_failed")) == ["alert", "briefing", "staff_alert"]
            assert all("error" in e["payload"] for e in photon_events(rt, "imessage_failed"))
        stop_background(rt)


async def test_role_follow_up_and_stand_down(tmp_path):
    people = default_responders()
    people = [responder(i, "public", callable_=True) if i in (2, 3) else r for i, r in enumerate(people)]
    m = FakeMessenger()
    async with runtime(tmp_path, messenger=m, responders=people) as rt:
        iid = await start(rt)
        await rt.clock.advance(10)
        by = {d["responder_id"]: d for d in wave(rt)}
        await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": by["r1"]["id"]})
        await rt.deliver(iid, {"kind": "accept", "source": "twilio", "dispatch_id": by["r2"]["id"]})
        await rt.settle()
        patient = m.texts_to("+15550100001")[-1]
        assert patient.startswith("You are going to the person. Go to east elevators, floor 0, Test Gym, 1 Test St.")
        assert patient.endswith("Reply HERE when you arrive.")
        runner = m.texts_to("+15550100002")[-1]
        assert runner.startswith("You are the AED runner. Get the AED: 14 meters, left of the elevators.")
        assert runner.endswith("Reply HERE when you arrive with the AED.")
        # r3 was texted the alert and is released once both roles are taken
        assert rt.store.dispatches[by["r3"]["id"]]["status"] == "released"
        assert m.texts_to("+15550100003")[-1] == ("Two responders are already on the way. "
                                                   "Thank you, you can stand down.")
        assert not m.texts_to("+15550100004")  # never texted: no stand-down either
        roles = [e["payload"].get("role") for e in photon_events(rt, "imessage_sent")
                 if e["payload"]["purpose"] == "role"]
        assert sorted(roles) == ["aed_runner", "patient"]


async def test_briefing_text_follows_the_spoken_briefing(tmp_path):
    m = FakeMessenger()
    telephony = FakeTelephony()
    telephony.rings = True  # behave like Twilio: the TwiML is fetched when the phone answers
    async with runtime(tmp_path, messenger=m, telephony=telephony) as rt:
        app = create_app(rt, camera_id="cam-test", warm=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            iid = await start(rt)
            await rt.clock.advance(10)
            assert not m.texts_to(SIM)  # not before it is spoken
            r = await c.post(f"/twilio/briefing/{iid}")
            assert r.text.count("<Say>") == 2
            assert f'<Redirect method="POST">/twilio/briefing/{iid}?spoken=1</Redirect>' in r.text
            assert not m.texts_to(SIM)
            r = await c.post(f"/twilio/briefing/{iid}?spoken=1")
            assert "<Hangup" in r.text and "<Say>" not in r.text
            await rt.settle()
            (text,) = m.texts_to(SIM)
            await rt.clock.advance(BRIEFING_TEXT_FALLBACK_S)
            assert m.texts_to(SIM) == [text]  # the fallback does not send it twice


async def test_briefing_text_fallback_when_the_call_never_finishes(tmp_path):
    m = FakeMessenger()
    telephony = FakeTelephony()
    telephony.rings = True
    async with runtime(tmp_path, messenger=m, telephony=telephony) as rt:
        await start(rt)
        await rt.clock.advance(10)
        assert not m.texts_to(SIM)
        await rt.clock.advance(BRIEFING_TEXT_FALLBACK_S)
        assert len(m.texts_to(SIM)) == 1


async def test_twiml_unchanged_without_messaging(tmp_path):
    async with runtime(tmp_path) as rt:
        app = create_app(rt, camera_id="cam-test", warm=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            iid = await start(rt)
            r = await c.post(f"/twilio/briefing/{iid}")
            assert "<Redirect" not in r.text and "<Hangup" in r.text


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def sign(raw: bytes, msg_id: str, ts: int, secret: str = SECRET) -> str:
    key = base64.b64decode(secret.removeprefix("whsec_"))
    return "v1," + base64.b64encode(hmac.new(key, f"{msg_id}.{ts}.".encode() + raw, hashlib.sha256).digest()).decode()


def inbound(text, handle="+15550100001", event_id="evt_1"):
    return {"id": event_id, "type": "message.received", "apiVersion": "2026-07-01", "source": "imessage.photon",
            "timestamp": "2026-11-14T00:00:00.000Z",
            "data": {"projectId": "pho_prj_0" + "a" * 25, "object": {
                "id": "pho_msg_0" + "e" * 25, "platform": "imessage", "status": "received",
                "space": {"id": SPACE, "kind": "direct", "platform": "imessage"},
                "sentBy": {"id": "pho_usr_0" + "c" * 25, "handle": handle, "kind": "human", "platform": "imessage"},
                "receivedBy": {"id": AGENT, "handle": "+15550009999", "kind": "agent", "platform": "imessage"},
                "content": {"type": "text", "format": "plain", "text": text}}}}


async def post_event(c, event, *, msg_id=None, ts=None, secret=SECRET):
    raw = json.dumps(event).encode()
    msg_id = msg_id or event["id"]
    ts = int(time.time()) if ts is None else ts
    headers = {"webhook-id": msg_id, "webhook-timestamp": str(ts), "webhook-signature": sign(raw, msg_id, ts, secret),
               "content-type": "application/json"}
    return await c.post("/photon/webhook", content=raw, headers=headers)


@pytest.fixture
async def hook(tmp_path):
    people = default_responders()
    people = [responder(2, "public", callable_=True) if r["id"] == "r2" else r for r in people]
    m = FakeMessenger()
    async with runtime(tmp_path, messenger=m, responders=people) as rt:
        app = create_app(rt, camera_id="cam-test", warm=False)
        app.state.photon_webhook_secret = SECRET
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield rt, c, m


def test_standard_webhooks_vector():
    # The published Standard Webhooks example (secret, id, timestamp, payload -> signature).
    secret = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"
    headers = {"webhook-id": "msg_p5jXN8AQM9LWM0D4loKWxJek", "webhook-timestamp": "1614265330",
               "webhook-signature": "v2,abc v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE="}
    verify_signature(secret, headers, b'{"test": 2432232314}', now=1614265330)
    with pytest.raises(SignatureError):
        verify_signature(secret, headers, b'{"test": 2432232315}', now=1614265330)
    with pytest.raises(SignatureError):
        verify_signature(secret, headers, b'{"test": 2432232314}', now=1614265330 + 301)


def test_parse_reply():
    assert [parse_reply(t) for t in ("1", " 1. ", "2", "HERE", "here!", "Here", "yes", "12", "I'm here", None)] == [
        "accept", "accept", "decline", "arrived", "arrived", "arrived", None, None, None, None]


async def test_webhook_rejects_bad_signatures_and_missing_secret(hook):
    _rt, c, _ = hook
    r = await post_event(c, inbound("1"), secret="whsec_" + base64.b64encode(b"wrong-key").decode())
    assert r.status_code == 400 and "detail" in r.json()
    r = await post_event(c, inbound("1"), ts=int(time.time()) - 600)
    assert r.status_code == 400
    r = await c.post("/photon/webhook", json=inbound("1"))
    assert r.status_code == 400
    c._transport.app.state.photon_webhook_secret = None
    from agent import deps
    if not deps.settings().photon_webhook_secret:
        r = await post_event(c, inbound("1"))
        assert r.status_code == 503


async def test_reply_1_accepts_then_here_arrives_with_the_aed(hook):
    rt, c, m = hook
    iid = await start(rt)
    await rt.clock.advance(10)
    by = {d["responder_id"]: d for d in wave(rt)}
    await rt.deliver(iid, {"kind": "accept", "source": "app", "dispatch_id": by["r1"]["id"]})  # patient
    r = await post_event(c, inbound("1", handle="+15550100002", event_id="evt_a"))
    assert r.json() == {"ok": True}
    await rt.settle()
    d2 = rt.store.dispatches[by["r2"]["id"]]
    assert d2["status"] == "accepted" and d2["role"] == "aed_runner"
    assert m.texts_to("+15550100002")[-1].startswith("You are the AED runner.")
    # Photon redelivers the same event: nothing happens twice
    r = await post_event(c, inbound("1", handle="+15550100002", event_id="evt_a"))
    assert r.json() == {"ok": True}
    assert len(rt.store.events_of("imessage_received")) == 1
    r = await post_event(c, inbound("here", handle="+15550100002", event_id="evt_b"))
    assert r.json() == {"ok": True}
    state = await rt.get_state(iid)
    assert rt.store.dispatches[by["r2"]["id"]]["status"] == "arrived"
    assert state["milestones"].get("aed_arrived") is not None  # the AED runner brought it
    received = [e["payload"]["reply"] for e in rt.store.events_of("imessage_received")]
    assert received == ["accept", "arrived"]
    assert all(e["actor"] == "photon" for e in rt.store.events_of("imessage_received"))
    # the chat from the inbound message is remembered for later sends
    assert m.remembered["+15550100002"] == (SPACE, AGENT)


async def test_reply_2_declines_and_noise_is_ignored(hook):
    rt, c, _ = hook
    iid = await start(rt)
    await rt.clock.advance(10)
    by = {d["responder_id"]: d for d in wave(rt)}
    for i, (text, handle) in enumerate([("hello", "+15550100002"), ("1", "+15550199999"), ("1", "person@example.com"),
                                        ("here", "+15550100002"), ("1", SIM)]):
        r = await post_event(c, inbound(text, handle=handle, event_id=f"evt_n{i}"))
        assert r.status_code == 200 and r.json() == {"ok": True}
    assert rt.store.events_of("imessage_received") == []
    assert rt.store.dispatches[by["r2"]["id"]]["status"] == "sent"
    r = await post_event(c, {"id": "evt_x", "type": "message.delivered", "data": {}})
    assert r.json() == {"ok": True}
    r = await post_event(c, inbound("2", handle="+1 555 010 0002", event_id="evt_d"))
    assert r.json() == {"ok": True}
    assert rt.store.dispatches[by["r2"]["id"]]["status"] == "declined"
    await rt.deliver(iid, {"kind": "resolve", "source": "desk", "by": "desk"})
    r = await post_event(c, inbound("1", handle="+15550100001", event_id="evt_late"))
    assert r.json() == {"ok": True}
    assert rt.store.dispatches[by["r1"]["id"]]["status"] == "released"


async def test_webhook_without_messaging_still_answers(tmp_path):
    async with runtime(tmp_path) as rt:
        app = create_app(rt, camera_id="cam-test", warm=False)
        app.state.photon_webhook_secret = SECRET
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            iid = await start(rt)
            await rt.clock.advance(10)
            r = await post_event(c, inbound("1"))
            assert r.json() == {"ok": True}
            await asyncio.sleep(0)
            assert (await rt.get_state(iid))["roles"]["patient"] == "r1"
