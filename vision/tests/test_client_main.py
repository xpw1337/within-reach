"""client.py request shapes (docs/CONTRACTS.md section 2), retry, privacy rules; main.py loop.

The HTTP side runs against httpx.MockTransport and a local stdlib HTTP server; no agent needed.
"""

from __future__ import annotations

import base64
import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import httpx
import numpy as np
import pytest

from vision import client as C
from vision import main as M
from vision.config import DetectorConfig, load_settings
from vision.detector import (
    PERSON_DOWN,
    POSSIBLE_SEIZURE,
    RESPONDER_ARRIVED,
    RESPONSIVE,
    Detector,
    VisionEvent,
)
from vision.tests import synth as S

WALL = 1_794_000_000.0  # a fixed wall-clock time for payload timestamps

# docs/CONTRACTS.md section 2, POST /events
REQUIRED = {"camera_id": str, "kind": str, "victim_track_id": int, "ts": str}
OPTIONAL = {"witnessed": bool, "frame_jpeg_b64": str}
KINDS = {"person_down", "responsive", "possible_seizure", "responder_arrived"}


def assert_contract_shape(body: dict) -> None:
    assert set(body) <= set(REQUIRED) | set(OPTIONAL), (
        f"unexpected keys {set(body) - set(REQUIRED) - set(OPTIONAL)}"
    )
    for key, typ in REQUIRED.items():
        assert isinstance(body[key], typ) and not isinstance(body[key], bool), key
    assert body["kind"] in KINDS
    ts = datetime.fromisoformat(body["ts"])
    assert ts.utcoffset() is not None and ts.utcoffset().total_seconds() == 0, "ts must be UTC"
    for key, typ in OPTIONAL.items():
        if key in body:
            assert isinstance(body[key], typ), key
    if body["kind"] != "person_down":
        assert "witnessed" not in body and "frame_jpeg_b64" not in body


def frame(h: int = 720, w: int = 1280) -> np.ndarray:
    """A synthetic frame: a gradient, no person."""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[..., 1] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    return img


def decode_jpeg(b64: str) -> np.ndarray:
    import cv2

    raw = base64.b64decode(b64)
    assert raw[:2] == b"\xff\xd8", "not a JPEG"
    img = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return img


# ---------------------------------------------------------------------------
# Payloads and privacy
# ---------------------------------------------------------------------------


def test_person_down_payload_matches_contract():
    e = VisionEvent(PERSON_DOWN, 3, t=12.0, witnessed=True)
    body = C.build_payload("cam-lobby-1", e, WALL, frame())
    assert_contract_shape(body)
    assert body["camera_id"] == "cam-lobby-1"
    assert body["victim_track_id"] == 3
    assert body["witnessed"] is True
    img = decode_jpeg(body["frame_jpeg_b64"])
    assert max(img.shape[:2]) <= 640
    assert img.shape[:2] == (360, 640)  # aspect kept


def test_person_down_found_down_without_frame():
    body = C.build_payload("cam-lobby-1", VisionEvent(PERSON_DOWN, 1, 0.0, witnessed=False), WALL)
    assert_contract_shape(body)
    assert body["witnessed"] is False
    assert "frame_jpeg_b64" not in body


@pytest.mark.parametrize("kind", [RESPONSIVE, POSSIBLE_SEIZURE, RESPONDER_ARRIVED])
def test_other_kinds_never_carry_a_frame(kind):
    body = C.build_payload("cam-lobby-1", VisionEvent(kind, 1, 5.0), WALL, frame())
    assert_contract_shape(body)
    assert "frame_jpeg_b64" not in body and "witnessed" not in body


def test_small_frames_are_not_upscaled():
    img = decode_jpeg(C.encode_snapshot(frame(240, 320), max_side=640, quality=70))
    assert img.shape[:2] == (240, 320)


def test_unknown_kind_rejected():
    with pytest.raises(ValueError):
        C.build_payload("cam", VisionEvent("fell", 1, 0.0), WALL)


def test_ts_is_iso_utc():
    assert C.iso_utc(0.0) == "1970-01-01T00:00:00.000+00:00"


def test_nothing_written_to_disk(tmp_path, monkeypatch):
    import cv2

    monkeypatch.chdir(tmp_path)

    def refuse(*a, **k):
        raise AssertionError("cv2.imwrite must never be called")

    monkeypatch.setattr(cv2, "imwrite", refuse)
    seen = []
    client = C.EventClient(
        "http://agent",
        "cam-lobby-1",
        transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(200, json={})),
    )
    client.send(VisionEvent(PERSON_DOWN, 1, 0.0, witnessed=True), WALL, frame())
    client.close()
    assert len(seen) == 1
    assert list(tmp_path.iterdir()) == []


def test_vision_source_has_no_disk_writes_or_face_processing():
    forbidden = [
        "imwrite",
        "VideoWriter",
        "CascadeClassifier",
        "face_recognition",
        "mediapipe",
        "dlib",
        "deepface",
    ]
    src = Path(__file__).resolve().parents[1]
    for path in src.glob("*.py"):
        text = path.read_text()
        for token in forbidden:
            assert token not in text, f"{path.name} uses {token}"


# ---------------------------------------------------------------------------
# HTTP and retry
# ---------------------------------------------------------------------------


def _client(handler, **kw) -> tuple[C.EventClient, list[float]]:
    sleeps: list[float] = []
    c = C.EventClient(
        "http://agent:8000/", "cam-lobby-1", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw
    )
    return c, sleeps


def test_post_sends_json_to_events():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"incident_id": "abc", "status": "detected"})

    c, sleeps = _client(handler)
    reply = c.send(VisionEvent(RESPONSIVE, 2, 9.0), WALL)
    assert reply == {"incident_id": "abc", "status": "detected"}
    assert seen[0].method == "POST" and seen[0].url.path == "/events"
    assert seen[0].headers["content-type"].startswith("application/json")
    assert_contract_shape(json.loads(seen[0].content))
    assert sleeps == []


def test_retries_5xx_with_backoff_then_succeeds():
    codes = iter([503, 500, 200])
    c, sleeps = _client(lambda r: httpx.Response(next(codes), json={"incident_id": "x", "status": "s"}))
    assert c.send(VisionEvent(RESPONSIVE, 1, 0.0), WALL) == {"incident_id": "x", "status": "s"}
    assert sleeps == [0.25, 0.5]


def test_retries_connection_errors():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("agent down", request=req)
        return httpx.Response(200, json={"incident_id": None, "status": "ignored"})

    c, _ = _client(handler)
    assert c.send(VisionEvent(RESPONSIVE, 1, 0.0), WALL) == {"incident_id": None, "status": "ignored"}
    assert calls["n"] == 3


def test_gives_up_after_max_attempts():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503)

    c, sleeps = _client(handler, max_attempts=3)
    assert c.send(VisionEvent(RESPONSIVE, 1, 0.0), WALL) is None
    assert calls["n"] == 3
    assert sleeps == [0.25, 0.5]


def test_no_retry_on_4xx():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(422, json={"detail": "bad"})

    c, _ = _client(handler)
    assert c.send(VisionEvent(RESPONSIVE, 1, 0.0), WALL) is None
    assert calls["n"] == 1


class _FakeAgent(BaseHTTPRequestHandler):
    received: ClassVar[list[tuple[str, dict]]] = []
    fail_first: ClassVar[int] = 0

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).received.append((self.path, body))
        if type(self).fail_first > 0:
            type(self).fail_first -= 1
            self.send_response(503)
            self.end_headers()
            return
        out = json.dumps({"incident_id": "inc-1", "status": "detected"}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


def test_against_a_local_http_server_in_order():
    _FakeAgent.received = []
    _FakeAgent.fail_first = 1
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAgent)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}"
        replies = []
        sender = C.BackgroundSender(
            C.EventClient(url, "cam-lobby-1", sleep=lambda s: None), on_reply=lambda p, r: replies.append(r)
        )
        sender.submit(VisionEvent(PERSON_DOWN, 4, 1.0, witnessed=True), WALL, frame())
        sender.submit(VisionEvent(RESPONSIVE, 4, 3.0), WALL + 2, frame())
        sender.close()
    finally:
        server.shutdown()
        server.server_close()
    bodies = [b for _, b in _FakeAgent.received]
    assert all(path == "/events" for path, _ in _FakeAgent.received)
    # First person_down got a 503 and was retried; order is kept.
    assert [b["kind"] for b in bodies] == [PERSON_DOWN, PERSON_DOWN, RESPONSIVE]
    for b in bodies:
        assert_contract_shape(b)
    assert "frame_jpeg_b64" in bodies[0] and "frame_jpeg_b64" not in bodies[2]
    assert replies == [{"incident_id": "inc-1", "status": "detected"}] * 2


# ---------------------------------------------------------------------------
# main.py loop and overlay
# ---------------------------------------------------------------------------


class FakeCapture:
    def __init__(self, n: int, shape=(480, 640, 3)):
        self.n = n
        self.shape = shape

    def read(self):
        if self.n <= 0:
            return False, None
        self.n -= 1
        return True, frame(*self.shape[:2])


class FakeClock:
    def __init__(self, fps: float):
        self.i = -1
        self.fps = fps

    def __call__(self) -> float:
        self.i += 1
        return self.i / self.fps


def test_loop_sends_frame_only_with_person_down():
    clip = (
        S.Clip(15.0)
        .add(3.0, S.hold(1, S.standing()))
        .add(0.8, S.move(1, S.standing(), S.lying()))
        .add(7.0, S.hold(1, S.lying()))
        .add(2.5, S.raise_arm(1))
    )
    frames = [f for _, f in clip.frames]
    it = iter(frames)
    calls = []
    n = M.run(
        FakeCapture(len(frames)),
        lambda img: next(it),
        Detector(DetectorConfig()),
        lambda e, wall, img: calls.append((e.kind, wall, img is not None)),
        clock=FakeClock(15.0),
        wall_offset=WALL,
    )
    assert n == len(frames)
    assert [(k, has) for k, _, has in calls] == [(PERSON_DOWN, True), (RESPONSIVE, False)]
    assert calls[0][1] >= WALL + 3.0


def test_loop_quits_on_q_and_resets_on_r():
    resets = []

    class D(Detector):
        def reset(self):
            resets.append(True)
            super().reset()

    keys = iter([ord("r"), -1, ord("q")])
    n = M.run(
        FakeCapture(10),
        lambda img: [],
        D(),
        lambda *a: None,
        clock=FakeClock(15.0),
        show=lambda img: next(keys),
    )
    assert n == 3 and resets == [True]


def test_overlay_is_skeletons_on_black():
    det = Detector()
    tracks = [S.obs(1, S.standing())]
    det.update(0.0, tracks)
    img = M.render_overlay((480, 640, 3), tracks, det, ["status"])
    assert img.shape == (480, 640, 3)
    assert img.dtype == np.uint8
    assert img.any()
    # Mostly black: only lines, joints and text are drawn.
    assert (img.sum(axis=2) == 0).mean() > 0.9


def test_describe_hides_snapshot():
    body = C.build_payload("cam", VisionEvent(PERSON_DOWN, 1, 0.0, witnessed=True), WALL, frame())
    line = M.describe(body)
    assert body["frame_jpeg_b64"] not in line and "<jpeg," in line


def test_cli_defaults_from_env(monkeypatch):
    monkeypatch.setenv("CAMERA_INDEX", "2")
    monkeypatch.setenv("CAMERA_ID", "cam-test")
    monkeypatch.setenv("AGENT_URL", "http://example.test:9000/")
    s = load_settings()
    args = M.parse_args(["--dry-run", "--set", "down_seconds=3"], s)
    assert (args.camera, args.camera_id, args.agent_url) == (2, "cam-test", "http://example.test:9000")
    assert args.dry_run and args.set == ["down_seconds=3"]
