"""Run the detector over a video file and print (or check) the events it would send.

Used for tests and for tuning with the clips in demo/clips/. The clock is the video's own
timeline (frame index / fps), so a replay is deterministic and runs as fast as the model allows.
Nothing is posted and nothing is written.

    python -m vision.replay demo/clips/fall_witnessed.mp4            # print events
    python -m vision.replay demo/clips/fall_witnessed.mp4 --check    # compare with the .json next to it
    python -m vision.replay --all demo/clips                         # check every clip that has a .json
    python -m vision.replay CLIP --set down_seconds=3                # try a detector setting

Expected-events JSON (one per clip, same name, ``.json``)::

    {
      "clip": "fall_witnessed.mp4",
      "scenario": "what the person does, for whoever records it",
      "events": [{"kind": "person_down", "witnessed": true, "min_t": 4.0, "max_t": 12.0}],
      "allow_other_events": false
    }

``events`` is the ordered list of events the clip must produce. ``witnessed`` (person_down only),
``min_t`` and ``max_t`` (seconds from the start of the clip) are optional. With
``allow_other_events: false`` the clip must produce exactly these events and nothing else; with
``true`` they must appear in this order with anything else in between. Every event after a
person_down must name that person_down's victim.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import numpy as np

from vision.config import DetectorConfig, load_dotenv_if_available, load_settings
from vision.detector import EVENT_KINDS, PERSON_DOWN, Detector, VisionEvent
from vision.features import TrackObs

Tracker = Callable[[np.ndarray], list[TrackObs]]

EXIT_OK, EXIT_FAILED, EXIT_MISSING = 0, 1, 2


@dataclass
class ReplayResult:
    events: list[VisionEvent]
    fps: float
    frames: int


def replay_video(
    path: str | Path, tracker: Tracker, detector: Detector, fps_fallback: float = 30.0
) -> ReplayResult:
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise FileNotFoundError(f"cannot open video {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if not fps or math.isnan(fps) or fps <= 0:
        fps = fps_fallback
    events: list[VisionEvent] = []
    n = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            events.extend(detector.update(n / fps, tracker(frame)))
            n += 1
    finally:
        cap.release()
    return ReplayResult(events=events, fps=fps, frames=n)


# ---------------------------------------------------------------------------
# Expected-events check
# ---------------------------------------------------------------------------


def load_expected(path: str | Path) -> dict[str, Any]:
    spec = json.loads(Path(path).read_text())
    problems = validate_expected(spec)
    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))
    return spec


def validate_expected(spec: dict[str, Any]) -> list[str]:
    problems = []
    if not isinstance(spec.get("clip"), str) or not spec["clip"]:
        problems.append("'clip' must name the video file")
    events = spec.get("events")
    if not isinstance(events, list):
        problems.append("'events' must be a list")
        events = []
    for i, e in enumerate(events):
        if not isinstance(e, dict) or e.get("kind") not in EVENT_KINDS:
            problems.append(f"events[{i}].kind must be one of {list(EVENT_KINDS)}")
            continue
        if "witnessed" in e and (e["kind"] != PERSON_DOWN or not isinstance(e["witnessed"], bool)):
            problems.append(f"events[{i}].witnessed is a bool and only for person_down")
        for key in ("min_t", "max_t"):
            if e.get(key) is not None and not isinstance(e[key], (int, float)):
                problems.append(f"events[{i}].{key} must be a number of seconds")
    if not isinstance(spec.get("allow_other_events", False), bool):
        problems.append("'allow_other_events' must be true or false")
    return problems


def check_events(events: list[VisionEvent], spec: dict[str, Any]) -> list[str]:
    """Problems with ``events`` against an expected-events spec; empty means the clip passes."""
    expected: list[dict[str, Any]] = spec.get("events", [])
    allow_other = bool(spec.get("allow_other_events", False))
    problems: list[str] = []

    victim = None
    for e in events:
        if e.kind == PERSON_DOWN:
            victim = e.victim_track_id
        elif victim is not None and e.victim_track_id != victim:
            problems.append(f"{e.kind} at {e.t:.2f}s names track {e.victim_track_id}, victim is {victim}")

    actual_kinds = [e.kind for e in events]
    want_kinds = [x["kind"] for x in expected]
    if allow_other:
        matched: list[int] = []
        j = 0
        for i, e in enumerate(events):
            if j < len(expected) and e.kind == want_kinds[j]:
                matched.append(i)
                j += 1
        if j < len(expected):
            problems.append(f"expected {want_kinds} in order, got {actual_kinds}")
            return problems
    else:
        if actual_kinds != want_kinds:
            problems.append(f"expected exactly {want_kinds}, got {actual_kinds}")
            return problems
        matched = list(range(len(events)))

    for want, i in zip(expected, matched, strict=True):
        e = events[i]
        if "witnessed" in want and e.witnessed != want["witnessed"]:
            problems.append(f"{e.kind} at {e.t:.2f}s: witnessed={e.witnessed}, expected {want['witnessed']}")
        if want.get("min_t") is not None and e.t < want["min_t"]:
            problems.append(f"{e.kind} at {e.t:.2f}s is earlier than min_t={want['min_t']}")
        if want.get("max_t") is not None and e.t > want["max_t"]:
            problems.append(f"{e.kind} at {e.t:.2f}s is later than max_t={want['max_t']}")
    return problems


def event_line(e: VisionEvent) -> str:
    d: dict[str, Any] = {"t": round(e.t, 2), "kind": e.kind, "victim_track_id": e.victim_track_id}
    if e.kind == PERSON_DOWN:
        d["witnessed"] = e.witnessed
    return json.dumps(d)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run_clip(
    clip: Path,
    spec: dict[str, Any] | None,
    make_tracker: Callable[[], Tracker],
    cfg: DetectorConfig,
    out: TextIO | None = None,
) -> list[str] | None:
    """Replay one clip, print its events, and return problems (``None`` if there is no spec)."""
    out = out or sys.stdout
    result = replay_video(clip, make_tracker(), Detector(cfg))
    print(f"# {clip.name}: {result.frames} frames at {result.fps:.2f} fps", file=out)
    for e in result.events:
        print(event_line(e), file=out)
    if spec is None:
        return None
    problems = check_events(result.events, spec)
    print(f"# {clip.name}: {'PASS' if not problems else 'FAIL'}", file=out)
    for p in problems:
        print(f"#   {p}", file=out)
    return problems


def check_all(
    clips_dir: Path, make_tracker: Callable[[], Tracker], cfg: DetectorConfig, out: TextIO | None = None
) -> int:
    out = out or sys.stdout
    specs = sorted(clips_dir.glob("*.json"))
    if not specs:
        print(f"# no expected-events .json files in {clips_dir}", file=out)
        return EXIT_MISSING
    failed, missing = [], []
    for spec_path in specs:
        spec = load_expected(spec_path)
        clip = spec_path.parent / spec["clip"]
        if not clip.exists():
            missing.append(spec["clip"])
            print(f"# {spec['clip']}: MISSING (not recorded yet)", file=out)
            continue
        if run_clip(clip, spec, make_tracker, cfg, out):
            failed.append(spec["clip"])
    ran = len(specs) - len(missing)
    print(f"# {ran - len(failed)}/{ran} recorded clips pass; {len(missing)} missing", file=out)
    if failed:
        return EXIT_FAILED
    return EXIT_MISSING if missing else EXIT_OK


def _default_tracker_factory(args: argparse.Namespace) -> Callable[[], Tracker]:
    def make() -> Tracker:
        from vision.tracker import PoseTracker

        s = load_settings()
        return PoseTracker(
            args.model or s.model_path, tracker=args.tracker or s.tracker, imgsz=args.imgsz or s.imgsz
        )

    return make


def main(argv: Iterable[str] | None = None, make_tracker: Callable[[], Tracker] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m vision.replay", description=__doc__.split("\n\n")[0])
    p.add_argument("clips", nargs="*", type=Path, help="video files to replay")
    p.add_argument("--check", action="store_true", help="compare each clip with the .json next to it")
    p.add_argument("--all", type=Path, metavar="DIR", help="check every clip in DIR that has a .json")
    p.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="detector override")
    p.add_argument("--model", help="pose model path (default: VISION_MODEL or the cached yolov8n-pose)")
    p.add_argument("--tracker", help="Ultralytics tracker yaml (default: bytetrack.yaml)")
    p.add_argument("--imgsz", type=int, help="model input size")
    args = p.parse_args(list(argv) if argv is not None else None)

    load_dotenv_if_available()
    cfg = DetectorConfig.from_env().with_overrides(args.set)
    make = make_tracker or _default_tracker_factory(args)

    if args.all:
        return check_all(args.all, make, cfg)
    if not args.clips:
        p.error("give a clip, or --all DIR")
    failed = missing = False
    for clip in args.clips:
        spec = None
        if args.check:
            spec_path = clip.with_suffix(".json")
            if not spec_path.exists():
                print(f"# {clip.name}: no {spec_path.name} to check against")
                missing = True
                continue
            spec = load_expected(spec_path)
        if run_clip(clip, spec, make, cfg):
            failed = True
    return EXIT_FAILED if failed else EXIT_MISSING if missing else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
