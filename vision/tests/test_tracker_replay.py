"""tracker.py result conversion and the replay harness, without model weights or real video.

The replay tests write a synthetic video of blank frames to a temp dir (no person in it) and use
a fake tracker that returns scripted synthetic skeletons per frame.
"""

from __future__ import annotations

import io
import json

import numpy as np
import pytest

pytest.importorskip("cv2", reason="needs the vision extra: uv sync --extra vision")
pytest.importorskip("ultralytics", reason="needs the vision extra: uv sync --extra vision")

from vision import replay
from vision.config import DetectorConfig
from vision.detector import PERSON_DOWN, RESPONSIVE, Detector, VisionEvent
from vision.tests import synth as S
from vision.tracker import tracks_from_result

# ---------------------------------------------------------------------------
# tracker.tracks_from_result on real Ultralytics Results objects
# ---------------------------------------------------------------------------


def _results(boxes: np.ndarray, kpts: np.ndarray):
    from ultralytics.engine.results import Results

    return Results(
        orig_img=np.zeros((480, 640, 3), dtype=np.uint8),
        path="frame",
        names={0: "person"},
        boxes=boxes,
        keypoints=kpts,
    )


def test_tracks_from_result_with_ids():
    k = S.lying()
    kp = np.concatenate([k, np.full((17, 1), 0.9)], axis=1)[None]  # (1, 17, 3)
    # Tracked boxes: x1, y1, x2, y2, track_id, conf, cls
    boxes = np.array([[10.0, 20.0, 300.0, 80.0, 7.0, 0.88, 0.0]])
    out = tracks_from_result(_results(boxes, kp))
    assert len(out) == 1
    o = out[0]
    assert o.track_id == 7
    assert o.bbox == (10.0, 20.0, 300.0, 80.0)
    assert o.keypoints.shape == (17, 2)
    np.testing.assert_allclose(o.keypoints, k)
    assert o.kp_conf is not None and o.kp_conf.shape == (17,)


def test_tracks_from_result_without_ids_is_empty():
    kp = np.zeros((1, 17, 3))
    boxes = np.array([[10.0, 20.0, 300.0, 80.0, 0.88, 0.0]])  # untracked: no id column
    assert tracks_from_result(_results(boxes, kp)) == []


def test_tracks_from_result_no_detections():
    assert tracks_from_result(_results(np.zeros((0, 7)), np.zeros((0, 17, 3)))) == []


# ---------------------------------------------------------------------------
# check_events
# ---------------------------------------------------------------------------


def ev(kind: str, t: float, tid: int = 1, witnessed: bool | None = None) -> VisionEvent:
    return VisionEvent(kind, tid, t, witnessed)


def test_check_exact_pass_and_fail():
    spec = {
        "clip": "x.mp4",
        "events": [{"kind": "person_down", "witnessed": True}],
        "allow_other_events": False,
    }
    assert replay.check_events([ev(PERSON_DOWN, 8.0, witnessed=True)], spec) == []
    assert replay.check_events([ev(PERSON_DOWN, 8.0, witnessed=False)], spec)
    assert replay.check_events([], spec)
    assert replay.check_events([ev(PERSON_DOWN, 8.0, witnessed=True), ev(RESPONSIVE, 10.0)], spec)


def test_check_nothing_expected():
    spec = {"clip": "sit.mp4", "events": []}
    assert replay.check_events([], spec) == []
    assert replay.check_events([ev(PERSON_DOWN, 8.0, witnessed=False)], spec)


def test_check_timing_window():
    spec = {"clip": "x.mp4", "events": [{"kind": "person_down", "min_t": 5, "max_t": 9}]}
    assert replay.check_events([ev(PERSON_DOWN, 8.0, witnessed=True)], spec) == []
    assert replay.check_events([ev(PERSON_DOWN, 4.0, witnessed=True)], spec)
    assert replay.check_events([ev(PERSON_DOWN, 9.5, witnessed=True)], spec)


def test_check_allow_other_events_is_ordered_subsequence():
    spec = {
        "clip": "x.mp4",
        "events": [{"kind": "person_down"}, {"kind": "responsive"}],
        "allow_other_events": True,
    }
    events = [ev(PERSON_DOWN, 8.0, witnessed=True), ev("possible_seizure", 9.0), ev(RESPONSIVE, 12.0)]
    assert replay.check_events(events, spec) == []
    assert replay.check_events([ev(RESPONSIVE, 1.0), ev(PERSON_DOWN, 8.0, witnessed=True)], spec)


def test_check_events_must_name_the_victim():
    spec = {"clip": "x.mp4", "events": [{"kind": "person_down"}, {"kind": "responsive"}]}
    events = [ev(PERSON_DOWN, 8.0, tid=1, witnessed=True), ev(RESPONSIVE, 12.0, tid=2)]
    assert any("victim" in p for p in replay.check_events(events, spec))


def test_validate_expected():
    assert (
        replay.validate_expected({"clip": "a.mp4", "events": [{"kind": "person_down", "witnessed": True}]})
        == []
    )
    assert replay.validate_expected({"events": []})
    assert replay.validate_expected({"clip": "a.mp4", "events": [{"kind": "fell"}]})
    assert replay.validate_expected({"clip": "a.mp4", "events": [{"kind": "responsive", "witnessed": True}]})
    assert replay.validate_expected({"clip": "a.mp4", "events": [{"kind": "responsive", "min_t": "soon"}]})


def test_repo_expected_files_are_valid():
    from pathlib import Path

    clips = Path(__file__).resolve().parents[2] / "demo" / "clips"
    for path in clips.glob("*.json"):
        replay.load_expected(path)


# ---------------------------------------------------------------------------
# replay_video over a synthetic blank video with a scripted fake tracker
# ---------------------------------------------------------------------------

FPS = 15.0


def _write_blank_video(path, n_frames: int, fps: float = FPS) -> None:
    import cv2

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
    assert writer.isOpened()
    frame = np.zeros((48, 64, 3), dtype=np.uint8)
    for _ in range(n_frames):
        writer.write(frame)
    writer.release()


class ScriptedTracker:
    """Returns the synthetic tracks of clip frame i on the i-th call (ignores the pixels)."""

    def __init__(self, clip: S.Clip):
        self.frames = [f for _, f in clip.frames]
        self.i = 0

    def __call__(self, frame: np.ndarray):
        out = self.frames[self.i] if self.i < len(self.frames) else []
        self.i += 1
        return out


def _fall_and_raise() -> S.Clip:
    return (
        S.Clip(FPS)
        .add(3.0, S.hold(1, S.standing()))
        .add(0.8, S.move(1, S.standing(), S.lying()))
        .add(7.0, S.hold(1, S.lying()))
        .add(2.5, S.raise_arm(1))
        .add(1.0, S.hold(1, S.lying()))
    )


def test_replay_video_uses_the_video_clock(tmp_path):
    clip = _fall_and_raise()
    video = tmp_path / "fall_then_raise_hand.avi"
    _write_blank_video(video, len(clip.frames))
    result = replay.replay_video(video, ScriptedTracker(clip), Detector(DetectorConfig()))
    assert result.frames == len(clip.frames)
    assert result.fps == pytest.approx(FPS)
    assert [e.kind for e in result.events] == [PERSON_DOWN, RESPONSIVE]
    assert result.events[0].witnessed is True


def test_replay_missing_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        replay.replay_video(tmp_path / "nope.avi", lambda f: [], Detector())


def test_check_all_reports_pass_fail_and_missing(tmp_path):
    clip = _fall_and_raise()
    _write_blank_video(tmp_path / "good.avi", len(clip.frames))
    (tmp_path / "good.json").write_text(
        json.dumps(
            {
                "clip": "good.avi",
                "events": [{"kind": "person_down", "witnessed": True}, {"kind": "responsive"}],
            }
        )
    )
    (tmp_path / "missing.json").write_text(json.dumps({"clip": "missing.avi", "events": []}))
    out = io.StringIO()
    status = replay.check_all(tmp_path, lambda: ScriptedTracker(clip), DetectorConfig(), out)
    text = out.getvalue()
    assert status == replay.EXIT_MISSING
    assert "good.avi: PASS" in text and "missing.avi: MISSING" in text

    (tmp_path / "bad.json").write_text(json.dumps({"clip": "good.avi", "events": []}))
    out = io.StringIO()
    status = replay.check_all(tmp_path, lambda: ScriptedTracker(clip), DetectorConfig(), out)
    assert status == replay.EXIT_FAILED


def test_main_check_and_overrides(tmp_path, capsys):
    clip = _fall_and_raise()
    video = tmp_path / "c.avi"
    _write_blank_video(video, len(clip.frames))
    (tmp_path / "c.json").write_text(json.dumps({"clip": "c.avi", "events": [{"kind": "person_down"}]}))
    # With the default hold the raise is responsive, so an exact "person_down only" spec fails...
    assert (
        replay.main([str(video), "--check"], make_tracker=lambda: ScriptedTracker(clip)) == replay.EXIT_FAILED
    )
    # ...and with a hold longer than the raise it passes.
    status = replay.main(
        [str(video), "--check", "--set", "responsive_hold_seconds=5"],
        make_tracker=lambda: ScriptedTracker(clip),
    )
    assert status == replay.EXIT_OK
    assert '"kind": "person_down"' in capsys.readouterr().out
