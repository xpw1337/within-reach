"""POST /events to the live agent (docs/CONTRACTS.md section 2), with retry.

Body: ``{camera_id, kind, victim_track_id:int, witnessed?:bool, ts, frame_jpeg_b64?:string}``,
with ``witnessed`` and ``frame_jpeg_b64`` on ``person_down`` only.

Privacy rules, enforced here (vision/DESIGN.md, spec section 16):

* A frame leaves the device only inside a ``person_down`` event: one JPEG, downscaled. A frame
  handed in with any other kind is dropped, never encoded.
* The JPEG is encoded in memory. Nothing is written to disk.
* No face processing of any kind (no detection, blurring or recognition).
"""

from __future__ import annotations

import base64
import logging
import queue
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import numpy as np

from vision.detector import EVENT_KINDS, PERSON_DOWN, VisionEvent

log = logging.getLogger("vision.client")

RETRY_STATUS = {408, 429}


def iso_utc(wall_ts: float) -> str:
    """ISO 8601 UTC timestamp, e.g. ``2026-11-14T20:15:03.123+00:00``."""
    return datetime.fromtimestamp(wall_ts, tz=UTC).isoformat(timespec="milliseconds")


def encode_snapshot(frame: np.ndarray, max_side: int, quality: int) -> str:
    """Downscale so the longest side is at most ``max_side`` and JPEG-encode in memory (base64)."""
    import cv2

    h, w = frame.shape[:2]
    scale = min(1.0, max_side / float(max(h, w)))
    if scale < 1.0:
        frame = cv2.resize(
            frame, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA
        )
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise ValueError("JPEG encoding failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def build_payload(
    camera_id: str,
    event: VisionEvent,
    wall_ts: float,
    frame: np.ndarray | None = None,
    *,
    snapshot_max_side: int = 640,
    snapshot_jpeg_quality: int = 70,
) -> dict[str, Any]:
    if event.kind not in EVENT_KINDS:
        raise ValueError(f"unknown event kind {event.kind!r}")
    payload: dict[str, Any] = {
        "camera_id": camera_id,
        "kind": event.kind,
        "victim_track_id": int(event.victim_track_id),
        "ts": iso_utc(wall_ts),
    }
    if event.kind == PERSON_DOWN:
        payload["witnessed"] = bool(event.witnessed)
        if frame is not None:
            payload["frame_jpeg_b64"] = encode_snapshot(frame, snapshot_max_side, snapshot_jpeg_quality)
    elif frame is not None:
        log.warning("dropped a frame passed with %s: frames are only sent with person_down", event.kind)
    return payload


class EventClient:
    """Synchronous client for ``POST /events`` with bounded retry and exponential backoff."""

    def __init__(
        self,
        agent_url: str,
        camera_id: str,
        *,
        timeout: float = 2.0,
        max_attempts: int = 4,
        backoff_seconds: float = 0.25,
        snapshot_max_side: int = 640,
        snapshot_jpeg_quality: int = 70,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.camera_id = camera_id
        self.max_attempts = max(1, max_attempts)
        self.backoff_seconds = backoff_seconds
        self.snapshot_max_side = snapshot_max_side
        self.snapshot_jpeg_quality = snapshot_jpeg_quality
        self._sleep = sleep
        self._http = httpx.Client(base_url=agent_url.rstrip("/"), timeout=timeout, transport=transport)

    def payload(self, event: VisionEvent, wall_ts: float, frame: np.ndarray | None = None) -> dict[str, Any]:
        return build_payload(
            self.camera_id,
            event,
            wall_ts,
            frame,
            snapshot_max_side=self.snapshot_max_side,
            snapshot_jpeg_quality=self.snapshot_jpeg_quality,
        )

    def post(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """POST one payload. Returns the agent's JSON reply, or ``None`` if it never got through."""
        kind = payload.get("kind")
        for attempt in range(self.max_attempts):
            try:
                r = self._http.post("/events", json=payload)
            except httpx.TransportError as exc:
                log.warning("POST /events %s attempt %d failed: %s", kind, attempt + 1, exc)
            else:
                if r.status_code < 300:
                    try:
                        return r.json()
                    except ValueError:
                        return {}
                if r.status_code not in RETRY_STATUS and r.status_code < 500:
                    log.error("POST /events %s rejected (%d): %s", kind, r.status_code, r.text[:200])
                    return None
                log.warning("POST /events %s attempt %d got %d", kind, attempt + 1, r.status_code)
            if attempt < self.max_attempts - 1:
                self._sleep(self.backoff_seconds * (2**attempt))
        log.error("POST /events %s gave up after %d attempts", kind, self.max_attempts)
        return None

    def send(
        self, event: VisionEvent, wall_ts: float, frame: np.ndarray | None = None
    ) -> dict[str, Any] | None:
        return self.post(self.payload(event, wall_ts, frame))

    def close(self) -> None:
        self._http.close()


class BackgroundSender:
    """Posts events from a worker thread so retries never stall the camera loop.

    One worker and a FIFO queue keep the order (person_down always goes before responsive). The
    snapshot is encoded in the caller's thread at submit time, so the raw frame is not kept.
    """

    def __init__(
        self,
        client: EventClient,
        on_reply: Callable[[dict[str, Any], dict[str, Any] | None], None] | None = None,
    ):
        self.client = client
        self.on_reply = on_reply
        self._q: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="vision-events", daemon=True)
        self._thread.start()

    def submit(self, event: VisionEvent, wall_ts: float, frame: np.ndarray | None = None) -> dict[str, Any]:
        payload = self.client.payload(event, wall_ts, frame)
        self._q.put(payload)
        return payload

    def _run(self) -> None:
        while True:
            payload = self._q.get()
            if payload is None:
                return
            reply = self.client.post(payload)
            if self.on_reply is not None:
                self.on_reply(payload, reply)

    def close(self, timeout: float = 5.0) -> None:
        self._q.put(None)
        self._thread.join(timeout)
        self.client.close()
