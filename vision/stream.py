"""Annotated webcam feed over HTTP, for the dashboard's live console.

    GET  /stream.mjpg   multipart MJPEG of the annotated frames (boxes, skeletons, labels)
    GET  /snapshot.jpg  the latest annotated frame
    GET  /status        JSON: fps, people, victim, fire, recent events
    POST /reset         forget the current victim and fire (same as the r key)

The server binds to ``VISION_STREAM_HOST`` (default 127.0.0.1: only this laptop's browser can
watch). Frames are encoded in memory and never written to disk.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import numpy as np

log = logging.getLogger("vision.stream")

BOUNDARY = b"frame"


class FrameHub:
    """Latest annotated JPEG plus status, shared between the camera loop and HTTP clients."""

    def __init__(self, quality: int = 75):
        self.quality = quality
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0
        self.status: dict[str, Any] = {}
        self.on_reset: Callable[[], None] | None = None

    def publish(self, frame: np.ndarray, status: dict[str, Any]) -> None:
        import cv2

        ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
        if not ok:
            return
        with self._cond:
            self._jpeg = buf.tobytes()
            self._seq += 1
            self.status = status
            self._cond.notify_all()

    def wait(self, after: int, timeout: float = 2.0) -> tuple[int, bytes | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq != after, timeout=timeout)
            return self._seq, self._jpeg


def _handler(hub: FrameHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # quiet
            log.debug(fmt, *args)

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Cache-Control", "no-store")

        def do_OPTIONS(self) -> None:
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:
            path = self.path.split("?")[0]
            if path == "/status":
                body = json.dumps(hub.status).encode()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == "/snapshot.jpg":
                _, jpeg = hub.wait(-1, timeout=0)
                if jpeg is None:
                    self.send_error(503, "no frame yet")
                    return
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
            elif path == "/stream.mjpg":
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}")
                self.end_headers()
                seq = -1
                try:
                    while True:
                        seq, jpeg = hub.wait(seq)
                        if jpeg is None:
                            continue
                        self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path.split("?")[0] != "/reset":
                self.send_error(404)
                return
            if hub.on_reset:
                hub.on_reset()
            self.send_response(204)
            self._cors()
            self.end_headers()

    return Handler


def serve(hub: FrameHub, host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _handler(hub))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="vision-stream", daemon=True).start()
    log.info("annotated feed at http://%s:%d/stream.mjpg", host, port)
    return server


def now_ms() -> int:
    return int(time.time() * 1000)
