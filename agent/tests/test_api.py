"""Every endpoint in docs/CONTRACTS.md section 2 answers with the right shape (fakes, in-memory store)."""

import base64

import httpx
import pytest

from agent.api.handcheck import sample_rows, summarize
from agent.io.tts import FakeTTS, render_camera_audio
from agent.main import create_app
from agent.tests.fixtures import CAMERA, ROUTES, T0, runtime


@pytest.fixture
async def ctx(tmp_path):
    async with runtime(tmp_path) as rt:
        app = create_app(rt, camera_id="cam-test", warm=False)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield rt, client


async def test_health_and_thresholds(ctx):
    rt, c = ctx
    r = await c.get("/health")
    assert r.status_code == 200 and set(r.json()) == {"ok", "warmed"}
    assert set(r.json()["warmed"]) == {"llm", "tts", "db"}
    r = await c.get("/config/thresholds")
    assert r.status_code == 200
    assert set(r.json()) == {"walk_speed_mps", "aed_roundtrip_target_s", "ext_max_travel_m",
                             "exit_max_travel_m", "yellow_fraction"}


async def test_live_flow_shapes(ctx):
    rt, c = ctx
    frame = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    r = await c.post("/events", json={"camera_id": "cam-test", "kind": "person_down", "victim_track_id": 7,
                                      "witnessed": True, "ts": T0, "frame_jpeg_b64": frame})
    assert r.status_code == 200
    body = r.json()
    iid = body["incident_id"]
    assert body["status"] == "voice_check"
    # repeat person_down returns the open incident
    r = await c.post("/events", json={"camera_id": "cam-test", "kind": "person_down", "victim_track_id": 7,
                                      "witnessed": True, "ts": T0})
    assert r.json()["incident_id"] == iid
    # vision event for a camera with no incident
    r = await c.post("/events", json={"camera_id": "nope", "kind": "responsive", "victim_track_id": 7, "ts": T0})
    assert r.json() == {"incident_id": None, "status": "ignored"}
    r = await c.post(f"/incidents/{iid}/confirm", json={"decision": "confirm", "by": "desk"})
    assert r.status_code == 200 and "status" in r.json()
    await rt.clock.advance(5)
    dispatches = [d for d in rt.store.dispatches.values() if d["role"] != "staff"]
    ids = [d["id"] for d in dispatches]
    r = await c.post(f"/dispatches/{ids[0]}/accept")
    assert r.json() == {"role": "patient", "status": "accepted"}
    r = await c.post(f"/dispatches/{ids[0]}/accept")  # idempotent
    assert r.json() == {"role": "patient", "status": "accepted"}
    r = await c.post(f"/dispatches/{ids[1]}/decline")
    assert r.json() == {"status": "declined"}
    r = await c.post(f"/dispatches/{ids[2]}/accept")
    assert r.json() == {"role": "aed_runner", "status": "accepted"}
    r = await c.post(f"/dispatches/{ids[3]}/accept")
    assert r.json() == {"status": "released"}
    r = await c.post(f"/dispatches/{ids[2]}/arrived", json={"with_aed": True})
    assert r.json() == {"status": "arrived"}
    r = await c.post(f"/incidents/{iid}/milestone", json={"kind": "cpr_started", "by": "desk"})
    assert r.json() == {"ok": True}
    r = await c.post(f"/incidents/{iid}/cancel_911", json={"by": "desk"})
    assert r.json() == {"ok": True}
    r = await c.post(f"/incidents/{iid}/resolve", json={"by": "desk"})
    assert r.json() == {"status": "resolved"}
    r = await c.post(f"/incidents/{iid}/resolve", json={"by": "desk"})
    assert r.json() == {"status": "resolved"}
    r = await c.post("/incidents/unknown/confirm", json={"decision": "confirm", "by": "d"})
    assert r.status_code == 404 and r.json() == {"detail": "unknown incident"}
    r = await c.post("/dispatches/unknown/accept")
    assert r.status_code == 404 and "detail" in r.json()


async def test_twilio_webhooks_return_twiml(ctx):
    rt, c = ctx
    r = await c.post("/simulate/cardiac", json={})
    iid = r.json()["incident_id"]
    await rt.clock.advance(10)
    d = next(d for d in rt.store.dispatches.values() if d["role"] != "staff")
    r = await c.post(f"/twilio/voice/{d['id']}", data={"CallSid": "CA1"})
    assert r.headers["content-type"].startswith("application/xml")
    assert "<Gather" in r.text and "Press 1" in r.text and "east elevators" in r.text
    r = await c.post(f"/twilio/gather/{d['id']}", data={"Digits": "1"})
    assert "going to the person" in r.text
    d2 = [x for x in rt.store.dispatches.values() if x["role"] != "staff"][1]
    r = await c.post(f"/twilio/gather/{d2['id']}", data={"Digits": "1"})
    assert "AED runner" in r.text and "14 meters, left of the elevators" in r.text
    r = await c.post(f"/twilio/briefing/{iid}", data={})
    assert r.text.count("Possible cardiac arrest, witnessed collapse.") == 2


async def test_simulate_fall_outdoor_and_reset(ctx):
    rt, c = ctx
    r = await c.post("/simulate/outdoor", json={})
    assert r.status_code == 501
    r = await c.post("/simulate/fall", json={})
    iid = r.json()["incident_id"]
    await rt.clock.advance(3)
    assert rt.store.incidents[iid]["type"] == "fall"
    r = await c.post("/reset")
    assert r.json() == {"ok": True}
    assert rt.store.incidents == {} and rt.open_by_camera == {}
    assert await rt.get_state(iid) is None
    r = await c.post("/simulate/cardiac", json={})
    assert r.json()["incident_id"] != iid


async def test_census_routes_503_when_db_missing(ctx, monkeypatch):
    rt, c = ctx
    import shared.config

    monkeypatch.setattr(shared.config.get_settings(), "supabase_url", None, raising=False)
    r = await c.get("/census/runs/x")
    assert r.status_code == 503 and r.json() == {"detail": "database not available"}
    r = await c.get("/census/handcheck/summary")
    assert r.status_code == 503


def test_handcheck_helpers():
    rows = [{"id": "a", "human_label": "correct"}, {"id": "b", "human_label": None},
            {"id": "c", "human_label": "unsure"}]
    assert sample_rows(rows, 2)[0]["detection_id"] == "b"  # unlabeled first
    assert summarize(rows) == {"labeled": 2, "correct": 1, "incorrect": 0, "unsure": 1}


async def test_render_camera_audio_with_fakes(tmp_path):
    from agent.live.store import MemoryStore

    store = MemoryStore(cameras=[CAMERA], routes=ROUTES)
    uploads = []

    def upload(bucket, path, data, ct):
        uploads.append((bucket, path))
        return f"https://storage/{bucket}/{path}"

    tts = FakeTTS()
    paths = await render_camera_audio("cam-test", store=store, tts=tts, audio_dir=tmp_path, upload=upload)
    assert set(paths) == {"voice_check", "cardiac_main", "cardiac_cpr_coach", "mod_breathing", "mod_seizure",
                          "fall_main"}
    assert ("audio", "cam-test/voice_check.mp3") in uploads
    assert store.routes[("cam-test", "aed")]["audio_url"].endswith("cam-test/cardiac_main.mp3")
    assert (tmp_path / "cam-test" / "voice_check.mp3").exists()
