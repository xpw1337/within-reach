"""Live capture loop: webcam -> pose tracks -> detector -> POST /events.

    uv run python -m vision.main                 # camera CAMERA_INDEX, posts to AGENT_URL
    uv run python -m vision.main --dry-run       # print events instead of posting
    uv run python -m vision.main --no-overlay    # headless (Raspberry Pi)

Keys in the overlay window: q quits, r resets the detector (forget the current victim).

The overlay draws skeletons only, on a black canvas: no camera pixels are shown, saved or sent,
except the one downscaled JPEG that rides inside a person_down event (client.py).
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

log = logging.getLogger("vision")

# Sink: (event, wall-clock seconds, frame or None) -> None. The frame is only ever given with person_down.
Sink = Callable[[VisionEvent, float, np.ndarray | None], None]


class Capture(Protocol):
    def read(self) -> tuple[bool, np.ndarray | None]: ...


# ---------------------------------------------------------------------------
# Skeleton-only overlay
# ---------------------------------------------------------------------------

COLORS = {"upright": (90, 200, 90), DOWN_PENDING: (0, 200, 255), DOWN: (60, 60, 255)}


def render_overlay(
    shape: tuple[int, ...],
    tracks: list[TrackObs],
    detector: Detector,
    status: list[str] | None = None,
) -> np.ndarray:
    """Black canvas the size of the camera frame with each track's skeleton. Never the frame itself."""
    import cv2

    h, w = int(shape[0]), int(shape[1])
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    min_conf = detector.cfg.keypoint_min_conf
    for o in tracks:
        phase = detector.phase_of(o.track_id) or "upright"
        color = (60, 60, 255) if detector.is_victim(o.track_id) else COLORS.get(phase, (200, 200, 200))
        k = o.keypoints
        ok = np.ones(len(k), dtype=bool) if o.kp_conf is None else o.kp_conf >= min_conf
        for a, b in SKELETON:
            if ok[a] and ok[b]:
                cv2.line(canvas, _pt(k[a]), _pt(k[b]), color, 2, cv2.LINE_AA)
        for i, p in enumerate(k):
            if ok[i]:
                cv2.circle(canvas, _pt(p), 3, color, -1, cv2.LINE_AA)
        label = f"#{o.track_id} {'VICTIM' if detector.is_victim(o.track_id) else phase}"
        anchor = (int(o.bbox[0]), max(12, int(o.bbox[1]) - 6))
        cv2.putText(canvas, label, anchor, cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    for i, line in enumerate(status or []):
        cv2.putText(
            canvas, line, (8, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (230, 230, 230), 1, cv2.LINE_AA
        )
    return canvas


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
) -> int:
    """Process frames until the capture ends, ``q`` is pressed or ``max_frames`` is reached.

    ``show`` displays the overlay and returns the key pressed (or -1); ``None`` runs headless.
    Returns the number of frames processed.
    """
    if wall_offset is None:
        wall_offset = time.time() - clock()
    n = 0
    sent: list[str] = []
    fps = 0.0
    last = clock()
    while max_frames is None or n < max_frames:
        ok, frame = capture.read()
        if not ok or frame is None:
            log.warning("camera returned no frame; stopping")
            break
        t = clock()
        tracks = tracker(frame)
        for e in detector.update(t, tracks):
            sink(e, wall_offset + e.t, frame if e.kind == PERSON_DOWN else None)
            sent.append(e.kind)
        n += 1
        dt = t - last
        last = t
        if dt > 0:
            fps = 0.9 * fps + 0.1 * (1.0 / dt) if fps else 1.0 / dt
        if show is not None:
            status = [
                f"{fps:4.1f} fps   tracks {len(tracks)}   victim {detector.victim_track_id or '-'}",
                "sent: " + (", ".join(sent[-4:]) or "-"),
                "q quit   r reset",
            ]
            key = show(render_overlay(frame.shape, tracks, detector, status))
            if key in (ord("q"), 27):
                break
            if key == ord("r"):
                detector.reset()
                sent.clear()
                log.info("detector reset")
        del frame
    return n


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
    log.info("DOWN_SECONDS=%s RESPONSIVE_HOLD_SECONDS=%s", cfg.down_seconds, cfg.responsive_hold_seconds)

    tracker = PoseTracker(args.model, tracker=args.tracker, imgsz=args.imgsz, device=args.device)
    tracker.warm_up()

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

        def sink(e: VisionEvent, wall: float, frame: np.ndarray | None) -> None:
            log.info("event (dry run) %s", describe(client.payload(e, wall, frame)))

    else:

        def on_reply(payload: dict[str, Any], reply: dict[str, Any] | None) -> None:
            log.info("sent %s -> %s", payload["kind"], reply)

        sender = BackgroundSender(client, on_reply=on_reply)

        def sink(e: VisionEvent, wall: float, frame: np.ndarray | None) -> None:
            log.info("event %s", describe(sender.submit(e, wall, frame)))

    cap = cv2.VideoCapture(args.camera)
    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        log.error("cannot open camera %d (on macOS, allow camera access for this terminal)", args.camera)
        return 1

    show = None
    if not args.no_overlay:
        window = f"Within Reach vision ({args.camera_id}) - skeletons only"

        def show(img: np.ndarray) -> int:
            cv2.imshow(window, img)
            return cv2.waitKey(1) & 0xFF

    try:
        frames = run(cap, tracker, Detector(cfg), sink, show=show)
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
