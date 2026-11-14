"""The six demo/clips expected-events files, checked against synthetic versions of each scenario.

This does not replace recording the clips (subtask 5.4): it only shows the specs, the harness and
the detector agree on stick-figure keypoints. Real video is what tunes the constants.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from vision import replay
from vision.config import DetectorConfig
from vision.detector import Detector
from vision.tests import synth as S

CLIPS = Path(__file__).resolve().parents[2] / "demo" / "clips"


def _fall() -> S.Clip:
    return S.Clip(15.0).add(3.0, S.hold(1, S.standing())).add(0.8, S.move(1, S.standing(), S.lying()))


def synthetic(name: str) -> S.Clip:
    lie = S.lying()
    if name == "fall_witnessed":
        return _fall().add(15.0, S.hold(1, lie))
    if name == "lie_down_slowly":
        return (
            S.Clip(15.0)
            .add(3.0, S.hold(1, S.standing()))
            .add(6.0, S.move(1, S.standing(), lie))
            .add(15.0, S.hold(1, lie))
        )
    if name == "sit_down":
        return (
            S.Clip(15.0)
            .add(3.0, S.hold(1, S.standing()))
            .add(1.0, S.move(1, S.standing(), S.sitting_chair()))
            .add(30.0, S.hold(1, S.sitting_chair()))
            .add(1.0, S.move(1, S.sitting_chair(), S.standing()))
            .add(1.5, S.move(1, S.standing(), S.sitting_floor()))
            .add(30.0, S.hold(1, S.sitting_floor()))
        )
    if name == "fall_then_raise_hand":
        return _fall().add(8.0, S.hold(1, lie)).add(3.0, S.raise_arm(1)).add(5.0, S.hold(1, lie))
    if name == "fall_then_shake":
        return _fall().add(10.0, S.shake(1, lie, hz=3.0, amp=0.06 * S.H)).add(5.0, S.hold(1, lie))
    if name == "fall_then_helper_arrives":
        far, near = S.standing(x0=1000), S.standing(x0=680)
        return (
            _fall()
            .add(8.0, S.hold(1, lie), S.hold(2, far))
            .add(1.5, S.hold(1, lie), S.move(2, far, near))
            .add(10.0, S.hold(1, lie), S.hold(2, near))
        )
    raise KeyError(name)


SPECS = sorted(CLIPS.glob("*.json"))


def test_all_six_clips_have_specs():
    assert {p.stem for p in SPECS} == {
        "fall_witnessed",
        "lie_down_slowly",
        "sit_down",
        "fall_then_raise_hand",
        "fall_then_shake",
        "fall_then_helper_arrives",
    }


@pytest.mark.parametrize("spec_path", SPECS, ids=lambda p: p.stem)
def test_spec_passes_on_synthetic_scenario(spec_path):
    spec = replay.load_expected(spec_path)
    assert spec["clip"] == spec_path.stem + ".mp4"
    d = Detector(DetectorConfig())
    events = []
    for t, frame in synthetic(spec_path.stem).frames:
        events.extend(d.update(t, frame))
    assert replay.check_events(events, spec) == []
