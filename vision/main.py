"""Live capture loop: webcam -> pose tracks -> detector -> POST /events.

    uv run python -m vision.main                 # camera CAMERA_INDEX, posts to AGENT_URL
    uv run python -m vision.main --dry-run       # print events instead of posting
    uv run python -m vision.main --no-overlay    # headless (Raspberry Pi)

Keys in the overlay window: q quits, r resets the detector (forget the current victim).

The overlay shows the camera image with every person's box and pose skeleton, fire/smoke boxes,
and a FALL / FIRE banner. It is shown in a local window and on http://127.0.0.1:8001/stream.mjpg
for the dashboard. Nothing is saved to disk; the only frame sent to the agent is the one
downscaled JPEG inside a person_down event (client.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Callable, Iterable
from typing import Any, Protocol

import numpy as np

from vision.config import DetectorConfig, Settings, load_dotenv_if_available, load_settings
from vision.detector import DOWN, DOWN_PENDING, PERSON_DOWN, Detector, VisionEvent
from vision.features import SKELETON, TrackObs
from vision.fire import FireBox, FireEvent, FireTracker
from vision.stream import FrameHub

log = logging.getLogger("vision")

# Sink: (event, wall-clock seconds, frame or None) -> None. The frame is only ever given with person_down.
Sink = Callable[[VisionEvent | FireEvent, float, np.ndarray | None], None]


class Capture(Protocol):
    def read(self) -> tuple[bool, np.ndarray | None]: ...


# ---------------------------------------------------------------------------
# Annotated overlay: the camera image with boxes, skeletons and labels
# ---------------------------------------------------------------------------

GREEN = (90, 210, 90)
AMBER = (0, 190, 255)
RED = (60, 60, 255)
ORANGE = (0, 140, 255)
WHITE = (240, 240, 240)
COLORS = {"upright": GREEN, DOWN_PENDING: AMBER, DOWN: RED}
LABELS = {"upright": "OK", DOWN_PENDING: "GOING DOWN", DOWN: "DOWN"}


def render_overlay(
    frame: np.ndarray,
    tracks: list[TrackObs],
    detector: Detector,
    status: list[str] | None = None,
    fire_boxes: list[FireBox] | None = None,
    fire_active: bool = False,
) -> np.ndarray:
    """A copy of the frame with every person's box and skeleton, fire boxes, and a status banner."""
    import cv2

    img = frame.copy()
    h, w = img.shape[:2]
    min_conf = detector.cfg.keypoint_min_conf
    for o in tracks:
        victim = detector.is_victim(o.track_id)
        phase = detector.phase_of(o.track_id) or "upright"
        color = RED if victim else COLORS.get(phase, WHITE)
        x1, y1, x2, y2 = (round(v) for v in o.bbox)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3 if victim else 2, cv2.LINE_AA)
        k = o.keypoints
        ok = np.ones(len(k), dtype=bool) if o.kp_conf is None else o.kp_conf >= min_conf
        for a, b in SKELETON:
            if ok[a] and ok[b]:
                cv2.line(img, _pt(k[a]), _pt(k[b]), color, 2, cv2.LINE_AA)
        for i, p in enumerate(k):
            if ok[i]:
                cv2.circle(img, _pt(p), 4, WHITE, -1, cv2.LINE_AA)
                cv2.circle(img, _pt(p), 4, color, 1, cv2.LINE_AA)
        label = f"#{o.track_id} {'FALLEN' if victim else LABELS.get(phase, phase)}"
        _tag(img, label, (x1, max(0, y1 - 26)), color)
        why = detector.explain(o.track_id)
        if why:
            cv2.putText(img, why, (x1 + 4, min(h - 6, y2 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(img, why, (x1 + 4, min(h - 6, y2 + 18)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1, cv2.LINE_AA)
    for fb in fire_boxes or []:
        x1, y1, x2, y2 = (round(v) for v in fb.bbox)
        cv2.rectangle(img, (x1, y1), (x2, y2), ORANGE, 3, cv2.LINE_AA)
        _tag(img, f"{fb.label.upper()} {fb.conf:.0%}", (x1, max(0, y1 - 26)), ORANGE)

    banners = []
    if detector.victim is not None:
        banners.append(("FALL DETECTED", RED))
    if fire_active:
        banners.append(("FIRE DETECTED", ORANGE))
    for i, (text, color) in enumerate(banners):
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 1.1, 2)
        y = 14 + i * (th + 26)
        cv2.rectangle(img, (w - tw - 34, y), (w - 10, y + th + 18), color, -1)
        cv2.putText(img, text, (w - tw - 22, y + th + 8), cv2.FONT_HERSHEY_DUPLEX, 1.1, WHITE, 2, cv2.LINE_AA)
    for i, line in enumerate(status or []):
        y = h - 12 - 22 * (len(status or []) - 1 - i)
        cv2.putText(img, line, (11, y + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1, cv2.LINE_AA)
    return img


def _tag(img: np.ndarray, text: str, origin: tuple[int, int], color: tuple[int, int, int]) -> None:
    import cv2

    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    x, y = origin
    cv2.rectangle(img, (x, y), (x + tw + 12, y + th + 12), color, -1)
    cv2.putText(img, text, (x + 6, y + th + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2, cv2.LINE_AA)


def _pt(p: np.ndarray) -> tuple[int, int]:
    return round(float(p[0])), round(float(p[1]))


# ---------------------------------------------------------------------------
# Loop
# ---------------------------------------------------------------------------


def run(
    capture: Capture,
    tracker: Callable[[np.ndarray], list[TrackObs]],
    detector: Detector,
    sink: Sink,
    *,
    clock: Callable[[], float] = time.monotonic,
    wall_offset: float | None = None,
    show: Callable[[np.ndarray], int] | None = None,
    max_frames: int | None = None,
    fire: Callable[[np.ndarray], list[FireBox]] | None = None,
    fire_every: int = 3,
    hub: FrameHub | None = None,
    debug: bool = False,
) -> int:
    """Process frames until the capture ends, ``q`` is pressed or ``max_frames`` is reached.

    ``show`` displays the overlay and returns the key pressed (or -1); ``None`` runs headless.
    ``fire`` (optional) runs every ``fire_every`` frames; ``hub`` (optional) gets every annotated
    frame for the dashboard stream. Returns the number of frames processed.
    """
    if wall_offset is None:
        wall_offset = time.time() - clock()
    n = 0
    sent: list[str] = []
    fps = 0.0
    last = clock()
    last_debug = -1e9
    fire_state = FireTracker()
    fire_boxes: list[FireBox] = []
    resets: list[bool] = []

    def reset() -> None:
        resets.append(True)

    if hub is not None:
        hub.on_reset = reset
    while max_frames is None or n < max_frames:
        ok, frame = capture.read()
        if not ok or frame is None:
            log.warning("camera returned no frame; stopping")
            break
        if resets:
            resets.clear()
            detector.reset()
            fire_state.reset()
            sent.clear()
            log.info("detector reset")
        t = clock()
        tracks = tracker(frame)
        for e in detector.update(t, tracks):
            sink(e, wall_offset + e.t, frame if e.kind == PERSON_DOWN else None)
            sent.append(e.kind)
        if fire is not None and n % max(1, fire_every) == 0:
            try:
                fire_boxes = fire(frame)
            except Exception as exc:  # noqa: BLE001 - fire is an add-on; never stop the fall loop
                log.warning("fire model failed: %s", exc)
                fire_boxes = []
            for fe in fire_state.update(t, fire_boxes, frame.shape):
                sink(fe, wall_offset + fe.t, None)
                sent.append(fe.kind)
        if debug and tracks and t - last_debug >= 1.0:
            last_debug = t
            log.info("pose: %s", " | ".join(f"#{o.track_id} {detector.phase_of(o.track_id)}: "
                                              f"{detector.explain(o.track_id)}" for o in tracks))
        n += 1
        dt = t - last
        last = t
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
        if show is not None or hub is not None:
            status = [
                f"{fps:4.1f} fps   people {len(tracks)}   fire {'YES' if fire_state.active else 'no'}",
                "sent: " + (", ".join(sent[-4:]) or "-"),
            ]
            img = render_overlay(frame, tracks, detector, status, fire_boxes, fire_state.active)
            if hub is not None:
                hub.publish(img, {
                    "fps": round(fps, 1),
                    "people": len(tracks),
                    "victim_track_id": detector.victim_track_id,
                    "fall": detector.victim is not None,
                    "fire": fire_state.active,
                    "fire_boxes": len(fire_boxes),
                    "sent": sent[-8:],
                    "fire_enabled": fire is not None,
                    "tracks": [{"id": o.track_id, "phase": detector.phase_of(o.track_id),
                                "why": detector.explain(o.track_id)} for o in tracks],
                })
            if show is not None:
                key = show(img)
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    reset()
        del frame
    return n


class ReopeningCapture:
    """A webcam that reopens itself when it stops giving frames (macOS drops cameras now and then)."""

    def __init__(self, cap: Any, reopen: Callable[[], Any], attempts: int = 15, wait_s: float = 1.0):
        self.cap = cap
        self.reopen = reopen
        self.attempts = attempts
        self.wait_s = wait_s

    def read(self) -> tuple[bool, np.ndarray | None]:
        ok, frame = self.cap.read()
        tries = 0
        while (not ok or frame is None) and tries < self.attempts:
            tries += 1
            log.warning("camera gave no frame; reopening (%d/%d)", tries, self.attempts)
            self.cap.release()
            time.sleep(self.wait_s)
            self.cap = self.reopen()
            ok, frame = self.cap.read()
        return ok, frame

    def release(self) -> None:
        self.cap.release()


def describe(payload: dict[str, Any]) -> str:
    """Payload as one log line, with the snapshot replaced by its size."""
    shown = dict(payload)
    if "frame_jpeg_b64" in shown:
        shown["frame_jpeg_b64"] = f"<jpeg, {len(payload['frame_jpeg_b64']) * 3 // 4} bytes>"
    return json.dumps(shown)


def parse_args(argv: Iterable[str] | None, settings: Settings) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m vision.main", description="Live person-down detection.")
    p.add_argument("--camera", type=int, default=settings.camera_index, help="camera index (CAMERA_INDEX)")
    p.add_argument("--camera-id", default=settings.camera_id, help="camera id sent with events (CAMERA_ID)")
    p.add_argument("--agent-url", default=settings.agent_url, help="agent base URL (AGENT_URL)")
    p.add_argument("--dry-run", action="store_true", help="print events, post nothing")
    p.add_argument("--no-overlay", action="store_true", help="no window (headless / Raspberry Pi)")
    p.add_argument("--model", default=settings.model_path, help="pose model path (VISION_MODEL)")
    p.add_argument("--tracker", default=settings.tracker, help="Ultralytics tracker yaml (VISION_TRACKER)")
    p.add_argument("--imgsz", type=int, default=settings.imgsz, help="model input size (VISION_IMGSZ)")
    p.add_argument("--device", default=None, help="torch device for the model, e.g. cpu or mps")
    p.add_argument("--width", type=int, default=None, help="requested capture width")
    p.add_argument("--height", type=int, default=None, help="requested capture height")
    p.add_argument("--no-fire", action="store_true", help="turn off fire/smoke detection")
    p.add_argument("--debug-pose", action="store_true", help="log what the detector sees once a second")
    p.add_argument("--no-window", action="store_true", help="no local window (the dashboard stream still runs)")
    p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="detector override")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    load_dotenv_if_available()
    settings = load_settings()
    args = parse_args(argv, settings)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(name)s %(message)s"
    )
    cfg = DetectorConfig.from_env().with_overrides(args.set)

    import cv2

    from vision.client import BackgroundSender, EventClient
    from vision.tracker import PoseTracker

    log.info(
        "camera %d as %s -> %s%s",
        args.camera,
        args.camera_id,
        args.agent_url,
        " (dry run)" if args.dry_run else "",
    )
    log.info("WITNESSED_DOWN_SECONDS=%s DOWN_SECONDS=%s", cfg.witnessed_down_seconds, cfg.down_seconds)

    tracker = PoseTracker(args.model, tracker=args.tracker, imgsz=args.imgsz, device=args.device)
    tracker.warm_up()
    fire = None
    if not args.no_fire and settings.fire_model_path:
        from vision.fire import FireDetector

        try:
            fire = FireDetector(settings.fire_model_path, conf=settings.fire_conf, device=args.device)
            fire.warm_up()
            log.info("fire/smoke detection on (%s, every %d frames)", settings.fire_model_path, settings.fire_every)
        except Exception as exc:  # noqa: BLE001 - run without fire rather than not at all
            log.warning("fire detection off: %s", exc)

    client = EventClient(
        args.agent_url,
        args.camera_id,
        timeout=settings.http_timeout_seconds,
        max_attempts=settings.http_max_attempts,
        backoff_seconds=settings.http_backoff_seconds,
        snapshot_max_side=settings.snapshot_max_side,
        snapshot_jpeg_quality=settings.snapshot_jpeg_quality,
    )
    sender: BackgroundSender | None = None
    if args.dry_run:

        def sink(e: VisionEvent | FireEvent, wall: float, frame: np.ndarray | None) -> None:
            log.info("event (dry run) %s", describe(client.payload(e, wall, frame)))

    else:

        def on_reply(payload: dict[str, Any], reply: dict[str, Any] | None) -> None:
            log.info("sent %s -> %s", payload["kind"], reply)

        sender = BackgroundSender(client, on_reply=on_reply)

        def sink(e: VisionEvent | FireEvent, wall: float, frame: np.ndarray | None) -> None:
            log.info("event %s", describe(sender.submit(e, wall, frame)))

    cap = cv2.VideoCapture(args.camera)
    # On macOS the first open triggers the camera permission prompt and fails at once; keep trying
    # while the user answers it.
    deadline = time.monotonic() + 60
    while not cap.isOpened() and time.monotonic() < deadline:
        log.warning("waiting for camera %d (allow camera access if macOS asks)...", args.camera)
        time.sleep(2)
        cap.release()
        cap = cv2.VideoCapture(args.camera)
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        log.error("cannot open camera %d (on macOS, allow camera access for this terminal)", args.camera)
        return 1

    hub = None
    if not args.no_overlay and settings.stream_port:
        from vision.stream import serve

        hub = FrameHub()
        serve(hub, settings.stream_host, settings.stream_port)

    cap = ReopeningCapture(cap, lambda: cv2.VideoCapture(args.camera))

    show = None
    if not args.no_overlay and not args.no_window:
        window = f"Within Reach camera ({args.camera_id})"

        def show(img: np.ndarray) -> int:
            cv2.imshow(window, img)
            return cv2.waitKey(1) & 0xFF

    try:
        frames = run(cap, tracker, Detector(cfg), sink, show=show, fire=fire,
                     fire_every=settings.fire_every, hub=hub, debug=args.debug_pose)
        log.info("stopped after %d frames", frames)
    except KeyboardInterrupt:
        log.info("interrupted")
    finally:
        cap.release()
        if show is not None:
            cv2.destroyAllWindows()
        if sender is not None:
            sender.close()
        else:
            client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
