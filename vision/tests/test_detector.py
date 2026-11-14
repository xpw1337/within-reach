"""Detector state machine on synthetic keypoint sequences with a fake clock (frame timestamps)."""

from __future__ import annotations

import pytest

from vision.config import DetectorConfig
from vision.detector import (
    PERSON_DOWN,
    POSSIBLE_SEIZURE,
    RESPONDER_ARRIVED,
    RESPONSIVE,
    Detector,
    VisionEvent,
)
from vision.tests import synth as S
from vision.tests.synth import Clip, flail, hold, lying, move, raise_arm, shake, standing

FALL_S = 0.8


def run(clip: Clip, cfg: DetectorConfig | None = None) -> list[VisionEvent]:
    d = Detector(cfg or DetectorConfig())
    out: list[VisionEvent] = []
    for t, frame in clip.frames:
        out.extend(d.update(t, frame))
    return out


def kinds(events: list[VisionEvent]) -> list[str]:
    return [e.kind for e in events]


def fallen(tid: int = 1, fps: float = 15.0, lie_s: float = 6.0, **kw) -> Clip:
    """Stand 3 s, fall in 0.8 s, lie still ``lie_s``: person_down is sent during the lie."""
    return (
        Clip(fps, **kw)
        .add(3.0, hold(tid, standing()))
        .add(FALL_S, move(tid, standing(), lying()))
        .add(lie_s, hold(tid, lying()))
    )


# ---------------------------------------------------------------------------
# person_down: witnessed vs found_down, and what must never trigger
# ---------------------------------------------------------------------------


def test_witnessed_fall():
    events = run(fallen(lie_s=10.0))
    assert kinds(events) == [PERSON_DOWN]
    e = events[0]
    assert e.witnessed is True
    assert e.victim_track_id == 1
    # Down pose starts during the fall; person_down follows DOWN_SECONDS later.
    assert 3.0 + 5.0 <= e.t <= 3.0 + FALL_S + 5.0 + 0.1


def test_witnessed_fall_with_keypoint_noise():
    events = run(fallen(lie_s=10.0, noise_px=2.0, seed=3))
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].witnessed is True


def test_down_seconds_is_respected():
    events = run(fallen(lie_s=10.0), DetectorConfig(down_seconds=2.0))
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].t < 3.0 + FALL_S + 2.1


def test_brief_down_pose_does_not_trigger():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()))
        .add(FALL_S, move(1, standing(), lying()))
        .add(3.0, hold(1, lying()))  # less than DOWN_SECONDS
        .add(1.0, move(1, lying(), standing()))
        .add(10.0, hold(1, standing()))
    )
    assert run(clip) == []


def test_slow_lie_down_is_found_down():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()))
        .add(6.0, move(1, standing(), lying()))  # slow: no 40% drop within 2 s
        .add(10.0, hold(1, lying()))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].witnessed is False


def test_already_down_when_first_seen_is_found_down():
    events = run(Clip().add(8.0, hold(4, lying())))
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].witnessed is False
    assert events[0].victim_track_id == 4
    assert events[0].t == pytest.approx(5.0, abs=0.1)


def test_sitting_on_a_chair_never_triggers():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()))
        .add(1.0, move(1, standing(), S.sitting_chair()))
        .add(30.0, hold(1, S.sitting_chair()))
    )
    assert run(clip) == []


def test_sitting_on_the_floor_never_triggers():
    clip = (
        Clip(noise_px=1.5, seed=1)
        .add(3.0, hold(1, standing()))
        .add(1.0, move(1, standing(), S.sitting_floor()))
        .add(30.0, hold(1, S.sitting_floor()))
    )
    assert run(clip) == []


def test_sitting_when_first_seen_never_triggers():
    assert run(Clip().add(30.0, hold(1, S.sitting_floor()))) == []
    assert run(Clip().add(30.0, hold(2, S.sitting_chair()))) == []


def test_bending_over_never_triggers():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()))
        .add(0.5, move(1, standing(), S.bending()))
        .add(10.0, hold(1, S.bending()))
        .add(0.5, move(1, S.bending(), standing()))
    )
    assert run(clip) == []


# ---------------------------------------------------------------------------
# responsive: victim only, held, flailing does not count
# ---------------------------------------------------------------------------


def test_raised_hand_is_responsive():
    clip = fallen(lie_s=7.0).add(2.5, raise_arm(1)).add(3.0, hold(1, lying()))
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN, RESPONSIVE]
    raise_start = 3.0 + FALL_S + 7.0
    assert events[1].victim_track_id == 1
    assert events[1].t >= raise_start + 1.5
    assert events[1].t <= raise_start + 0.3 + 1.5 + 0.2


def test_short_raise_is_not_responsive():
    clip = fallen(lie_s=7.0).add(1.0, raise_arm(1)).add(5.0, hold(1, lying()))
    assert kinds(run(clip)) == [PERSON_DOWN]


def test_flailing_is_not_responsive():
    clip = fallen(lie_s=7.0).add(8.0, flail(1, hz=2.0))
    assert RESPONSIVE not in kinds(run(clip))


def test_hand_raised_by_someone_else_is_ignored():
    bystander_up = standing(x0=800)
    bystander_up[S.R_WRIST] = (bystander_up[S.R_SHOULDER][0], bystander_up[S.R_SHOULDER][1] - 0.3 * S.H)
    clip = fallen(lie_s=7.0).add(5.0, hold(1, lying()), hold(2, bystander_up))
    assert RESPONSIVE not in kinds(run(clip))


def test_raise_must_be_seen_continuously():
    # The victim's track drops out mid-hold: the hold restarts and 1.5 s is never reached.
    clip = (
        fallen(lie_s=7.0)
        .add(1.0, raise_arm(1))
        .add(0.2, lambda u, d: None)
        .add(1.0, hold(1, lying(raised=1.0)))
        .add(3.0, hold(1, lying()))
    )
    assert kinds(run(clip)) == [PERSON_DOWN]


def test_responsive_sent_once():
    clip = (
        fallen(lie_s=7.0)
        .add(2.5, raise_arm(1))
        .add(2.0, hold(1, lying()))
        .add(2.5, raise_arm(1))
        .add(2.0, hold(1, lying()))
    )
    assert kinds(run(clip)) == [PERSON_DOWN, RESPONSIVE]


# ---------------------------------------------------------------------------
# possible_seizure: 1 to 5 Hz limb oscillation while down
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hz", [1.5, 3.0, 4.5])
def test_shaking_is_possible_seizure(hz):
    clip = fallen(lie_s=1.0, fps=15.0).add(10.0, shake(1, lying(), hz=hz, amp=0.06 * S.H))
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN, POSSIBLE_SEIZURE]
    assert events[1].victim_track_id == 1


def test_shaking_at_30_fps():
    clip = fallen(lie_s=1.0, fps=30.0).add(10.0, shake(1, lying(), hz=3.0, amp=0.06 * S.H))
    assert kinds(run(clip)) == [PERSON_DOWN, POSSIBLE_SEIZURE]


def test_shaking_does_not_count_as_responsive():
    # Arm shaking while raised above the shoulder: rhythmic movement is never a response.
    raised = lying(raised=1.0)
    clip = fallen(lie_s=7.0).add(8.0, shake(1, raised, hz=3.0, amp=0.06 * S.H))
    events = run(clip)
    assert RESPONSIVE not in kinds(events)
    assert POSSIBLE_SEIZURE in kinds(events)


def test_slow_movement_is_not_seizure():
    clip = fallen(lie_s=1.0).add(10.0, shake(1, lying(), hz=0.4, amp=0.06 * S.H))
    assert kinds(run(clip)) == [PERSON_DOWN]


def test_keypoint_jitter_is_not_seizure():
    assert kinds(run(fallen(lie_s=20.0, noise_px=1.5, seed=7))) == [PERSON_DOWN]


def test_raising_a_hand_is_not_seizure():
    clip = fallen(lie_s=7.0).add(4.0, raise_arm(1)).add(4.0, hold(1, lying()))
    assert POSSIBLE_SEIZURE not in kinds(run(clip))


def test_seizure_sent_once():
    clip = (
        fallen(lie_s=1.0)
        .add(6.0, shake(1, lying(), hz=3.0, amp=0.06 * S.H))
        .add(5.0, hold(1, lying()))
        .add(6.0, shake(1, lying(), hz=3.0, amp=0.06 * S.H))
    )
    assert kinds(run(clip)).count(POSSIBLE_SEIZURE) == 1


# ---------------------------------------------------------------------------
# responder_arrived: a second track near the victim
# ---------------------------------------------------------------------------


def test_helper_arrives():
    far, near = standing(x0=1000), standing(x0=680)
    clip = (
        fallen(lie_s=7.0)
        .add(2.0, hold(1, lying()), hold(2, far))
        .add(1.5, hold(1, lying()), move(2, far, near))
        .add(4.0, hold(1, lying()), hold(2, near))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN, RESPONDER_ARRIVED]
    assert events[1].victim_track_id == 1


def test_helper_kneeling_over_hidden_victim_counts():
    # The helper hides the victim entirely: the victim's track is lost, the helper stays near
    # the victim's last position.
    near = standing(x0=450)
    clip = fallen(lie_s=7.0).add(1.0, hold(1, lying()), hold(2, near)).add(4.0, hold(2, near))
    assert kinds(run(clip)) == [PERSON_DOWN, RESPONDER_ARRIVED]


def test_passerby_does_not_count():
    clip = fallen(lie_s=7.0).add(2.0, hold(1, lying()), move(2, standing(x0=1100), standing(x0=-200)))
    assert kinds(run(clip)) == [PERSON_DOWN]


def test_no_responder_without_an_incident():
    clip = Clip().add(5.0, hold(1, standing()), hold(2, standing(x0=380)))
    assert run(clip) == []


# ---------------------------------------------------------------------------
# One victim, ID switches, once per incident, clearing
# ---------------------------------------------------------------------------


def test_id_switch_keeps_victim_id():
    clip = (
        fallen(lie_s=7.0)
        .add(0.2, lambda u, d: None)  # tracker loses the victim...
        .add(0.5, hold(7, lying()))  # ...and re-acquires them as track 7
        .add(2.5, raise_arm(7))
        .add(1.0, hold(7, lying()))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN, RESPONSIVE]
    assert [e.victim_track_id for e in events] == [1, 1]


def test_id_switch_during_fall_is_still_witnessed():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()))
        .add(0.4, move(1, standing(), S.lerp(standing(), lying(), 0.5)))
        .add(0.4, move(5, S.lerp(standing(), lying(), 0.5), lying()))
        .add(8.0, hold(5, lying()))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].witnessed is True
    assert events[0].victim_track_id == 5


def test_helper_never_takes_over_the_victim():
    # Victim hidden, a new standing track appears on top: it must not inherit the victim, so its
    # raised hand is not responsive.
    helper = standing(x0=450)
    helper[S.R_WRIST] = (helper[S.R_SHOULDER][0], helper[S.R_SHOULDER][1] - 0.3 * S.H)
    clip = fallen(lie_s=7.0).add(0.3, lambda u, d: None).add(4.0, hold(9, helper))
    events = run(clip)
    assert RESPONSIVE not in kinds(events)


def test_one_victim_at_a_time():
    clip = (
        Clip()
        .add(3.0, hold(1, standing()), hold(2, standing(x0=900)))
        .add(FALL_S, move(1, standing(), lying()), hold(2, standing(x0=900)))
        .add(1.0, hold(1, lying()), hold(2, standing(x0=900)))
        .add(FALL_S, hold(1, lying()), move(2, standing(x0=900), lying(x_feet=900)))
        .add(15.0, hold(1, lying()), hold(2, lying(x_feet=900)))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN]
    assert events[0].victim_track_id == 1


def test_stand_up_clears_and_allows_a_new_incident():
    clip = (
        fallen(lie_s=7.0)
        .add(1.0, move(1, lying(), standing()))
        .add(5.0, hold(1, standing()))
        .add(FALL_S, move(1, standing(), lying()))
        .add(7.0, hold(1, lying()))
    )
    events = run(clip)
    assert kinds(events) == [PERSON_DOWN, PERSON_DOWN]
    assert all(e.witnessed for e in events)


def test_victim_lost_for_long_clears():
    cfg = DetectorConfig(victim_lost_clear_seconds=5.0)
    clip = fallen(lie_s=7.0).add(6.0, lambda u, d: None).add(7.0, hold(3, lying(x_feet=50)))
    events = run(clip, cfg)
    assert kinds(events) == [PERSON_DOWN, PERSON_DOWN]
    assert [e.victim_track_id for e in events] == [1, 3]


def test_clock_must_not_go_backwards():
    d = Detector()
    d.update(1.0, [])
    with pytest.raises(ValueError):
        d.update(0.5, [])


def test_reset_forgets_everything():
    d = Detector()
    for t, frame in fallen(lie_s=7.0).frames:
        d.update(t, frame)
    assert d.victim_track_id == 1
    d.reset()
    assert d.victim_track_id is None and d.tracks == {}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_config_from_env_uses_spec_names():
    cfg = DetectorConfig.from_env(
        {"DOWN_SECONDS": "3", "RESPONSIVE_HOLD_SECONDS": "2.5", "VISION_TORSO_DOWN_DEG": "50"}
    )
    assert cfg.down_seconds == 3.0
    assert cfg.responsive_hold_seconds == 2.5
    assert cfg.torso_down_deg == 50.0
    assert cfg.down_aspect_ratio == 1.3
    assert DetectorConfig.env_name("oscillation_min_samples") == "VISION_OSCILLATION_MIN_SAMPLES"
    assert DetectorConfig.from_env({"VISION_OSCILLATION_MIN_SAMPLES": "20"}).oscillation_min_samples == 20


def test_config_overrides():
    cfg = DetectorConfig().with_overrides(["down_seconds=2", "wrist_raise_margin=0.2"])
    assert cfg.down_seconds == 2.0 and cfg.wrist_raise_margin == 0.2
    with pytest.raises(ValueError):
        DetectorConfig().with_overrides(["nope=1"])
    with pytest.raises(ValueError):
        DetectorConfig().with_overrides(["down_seconds=abc"])
