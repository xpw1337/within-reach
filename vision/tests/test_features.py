"""Unit tests for vision/features.py on synthetic keypoints."""

from __future__ import annotations

import math

import numpy as np
import pytest

from vision import features as F
from vision.tests import synth as S


def test_torso_angle_upright_and_horizontal():
    assert F.torso_angle(S.standing()) == pytest.approx(0.0, abs=1e-6)
    assert F.torso_angle(S.lying()) == pytest.approx(90.0, abs=1.0)
    assert F.torso_angle(S.bending()) == pytest.approx(90.0, abs=3.0)
    assert F.torso_angle(S.sitting_chair()) < 5.0
    assert F.torso_angle(S.sitting_floor()) < 15.0


def test_torso_angle_45_degrees():
    k = np.zeros((17, 2))
    k[F.L_SHOULDER] = k[F.R_SHOULDER] = (0.0, 0.0)
    k[F.L_HIP] = k[F.R_HIP] = (100.0, 100.0)
    assert F.torso_angle(k) == pytest.approx(45.0)


def test_torso_angle_uses_one_side_when_the_other_is_hidden():
    k = S.lying()
    conf = np.ones(17)
    conf[F.R_SHOULDER] = 0.1
    conf[F.R_HIP] = 0.1
    assert F.torso_angle(k, conf, min_conf=0.5) == pytest.approx(90.0, abs=1.0)


def test_torso_angle_none_when_keypoints_missing():
    conf = np.ones(17)
    conf[[F.L_HIP, F.R_HIP]] = 0.0
    assert F.torso_angle(S.standing(), conf, min_conf=0.5) is None


def test_thigh_angle_standing_vs_chair():
    assert F.thigh_angle(S.standing()) == pytest.approx(0.0, abs=1e-6)
    assert F.thigh_angle(S.sitting_chair()) > 80.0


def test_bbox_aspect():
    assert F.bbox_aspect((0, 0, 130, 100)) == pytest.approx(1.3)
    assert F.bbox_aspect((10, 10, 10, 10)) == 0.0
    assert math.isinf(F.bbox_aspect((0, 5, 10, 5)))
    standing = F.bbox_aspect(S.bbox_of(S.standing()))
    lying = F.bbox_aspect(S.bbox_of(S.lying()))
    assert standing < 1.0
    assert lying > 1.3
    # Sitting on the floor with legs out also makes a wide box: the detector must not rely on it alone.
    assert F.bbox_aspect(S.bbox_of(S.sitting_floor())) > 1.3


def test_hip_height_is_image_y_of_hip_midpoint():
    k = S.standing(floor=600, h=300)
    assert F.hip_height(k) == pytest.approx(600 - 0.52 * 300)
    # Lying puts the hips near the floor line: larger image y.
    assert F.hip_height(S.lying(floor=600, h=300)) > F.hip_height(k) + 0.4 * 300


def test_hip_height_none_when_hips_hidden():
    conf = np.ones(17)
    conf[[F.L_HIP, F.R_HIP]] = 0.2
    assert F.hip_height(S.standing(), conf, min_conf=0.5) is None


def test_wrist_above_shoulder_lying_resting_vs_raised():
    body = S.H
    resting = S.lying()
    raised = S.lying(raised=1.0)
    assert F.wrist_rise(resting, body) < 0.05
    assert F.wrist_rise(raised, body) > 0.25
    assert not F.wrist_above_shoulder(resting, body, margin=0.15)
    assert F.wrist_above_shoulder(raised, body, margin=0.15)


def test_wrist_above_shoulder_standing_arm_up():
    k = S.standing()
    assert not F.wrist_above_shoulder(k, S.H, margin=0.1)
    k[F.R_WRIST] = (k[F.R_SHOULDER][0], k[F.R_SHOULDER][1] - 0.3 * S.H)
    assert F.wrist_above_shoulder(k, S.H, margin=0.1)


def test_wrist_above_shoulder_ignores_invisible_wrist():
    k = S.lying(raised=1.0)
    conf = np.ones(17)
    conf[F.L_WRIST] = 0.1  # the raised wrist is not trusted
    assert not F.wrist_above_shoulder(k, S.H, margin=0.15, kp_conf=conf, min_conf=0.5)


def test_compute_features_bundle():
    f = F.compute_features(S.obs(3, S.lying()))
    assert f.torso_angle == pytest.approx(90.0, abs=1.0)
    assert f.aspect > 1.3
    assert f.body_len == pytest.approx(f.bbox_w)
    assert set(f.limbs) == set(F.LIMBS)
    assert all(v is not None for v in f.limbs.values())


def test_box_geometry():
    a = (0, 0, 10, 10)
    assert F.iou(a, a) == pytest.approx(1.0)
    assert F.iou(a, (20, 20, 30, 30)) == 0.0
    assert F.iou(a, (5, 0, 15, 10)) == pytest.approx(50 / 150)
    assert F.box_gap(a, (5, 5, 15, 15)) == 0.0
    assert F.box_gap(a, (13, 14, 20, 20)) == pytest.approx(5.0)
    assert F.center_distance(a, (10, 0, 20, 10)) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Oscillation
# ---------------------------------------------------------------------------


def _series(hz: float, amp: float, fps: float, seconds: float, noise: float = 0.0, seed: int = 0):
    rng = np.random.default_rng(seed)
    t = np.arange(int(fps * seconds)) / fps
    x = (
        amp * np.sin(2 * np.pi * hz * t) + rng.normal(0, noise, len(t))
        if noise
        else amp * np.sin(2 * np.pi * hz * t)
    )
    return t, x


# 1.0 Hz itself sits on the band edge, where the peak bin can land just outside the band.
@pytest.mark.parametrize("hz", [1.25, 2.0, 3.0, 4.5])
def test_dominant_frequency_recovers_sine(hz):
    t, x = _series(hz, amp=10.0, fps=15.0, seconds=3.0, noise=0.5)
    est = F.dominant_frequency(t, x, 1.0, 5.0)
    assert est is not None
    assert est.freq_hz == pytest.approx(hz, abs=0.25)
    assert est.amplitude == pytest.approx(10.0, rel=0.35)
    assert est.peak_ratio > 0.6


def test_dominant_frequency_jittered_timestamps():
    rng = np.random.default_rng(1)
    t = np.cumsum(rng.uniform(1 / 20, 1 / 10, 60))
    x = 8.0 * np.sin(2 * np.pi * 3.0 * t)
    est = F.dominant_frequency(t, x, 1.0, 5.0)
    assert est is not None and est.freq_hz == pytest.approx(3.0, abs=0.3)


def test_dominant_frequency_noise_is_not_rhythmic():
    rng = np.random.default_rng(2)
    t = np.arange(45) / 15.0
    est = F.dominant_frequency(t, rng.normal(0, 1.0, 45), 1.0, 5.0)
    assert est is not None  # noise has some in-band peak, but it is weak and not dominant
    assert est.peak_ratio < 0.5
    assert est.amplitude < 1.0


def test_dominant_frequency_slow_drift_has_little_in_band_power():
    t, x = _series(0.3, amp=20.0, fps=15.0, seconds=3.0)
    est = F.dominant_frequency(t, x, 1.0, 5.0)
    assert est is None or est.amplitude < 5.0


def test_single_step_is_not_an_in_band_peak():
    # Raising a hand once: a step, not a rhythm. Its low-frequency lobe must not be reported.
    t = np.arange(45) / 15.0
    x = np.where(t < 1.5, 0.0, 100.0)
    est = F.dominant_frequency(t, x, 1.0, 5.0)
    assert est is None or est.amplitude < 10.0 or est.peak_ratio < 0.4


def test_dominant_frequency_never_reports_above_nyquist():
    # At 6 fps the Nyquist limit is 3 Hz, so a 1-5 Hz band can only report below 3 Hz.
    t, x = _series(2.0, amp=10.0, fps=6.0, seconds=4.0)
    est = F.dominant_frequency(t, x, 1.0, 5.0)
    assert est is not None
    assert est.freq_hz < 3.0
    assert est.freq_hz == pytest.approx(2.0, abs=0.3)
    # At 1.5 fps the 1-5 Hz band is not observable at all.
    t2 = np.arange(8) / 1.5
    assert F.dominant_frequency(t2, np.sin(t2), 1.0, 5.0) is None


def test_dominant_frequency_needs_samples():
    assert F.dominant_frequency(np.arange(5) / 15.0, np.zeros(5), 1.0, 5.0) is None
    assert F.dominant_frequency(np.zeros(10), np.arange(10.0), 1.0, 5.0) is None


def test_limb_oscillation_any_direction_and_missing_samples():
    fps, seconds = 15.0, 3.0
    t = np.arange(int(fps * seconds)) / fps
    d = 6.0 * np.sin(2 * np.pi * 3.0 * t)
    diagonal = np.stack([100 + d * 0.7, 200 + d * 0.7], axis=1)
    still = np.stack([np.full_like(t, 50.0), np.full_like(t, 60.0)], axis=1)
    diagonal[5] = np.nan  # keypoint dropped for one frame
    out = {o.limb: o for o in F.limb_oscillation(t, {"l_wrist": diagonal, "r_ankle": still}, 1.0, 5.0)}
    assert out["l_wrist"].freq_hz == pytest.approx(3.0, abs=0.25)
    assert out["l_wrist"].amplitude > 4.0
    assert "r_ankle" not in out or out["r_ankle"].amplitude < 1e-6


def test_limb_oscillation_skips_sparse_limbs():
    t = np.arange(45) / 15.0
    xy = np.full((45, 2), np.nan)
    xy[:5] = 1.0
    assert F.limb_oscillation(t, {"l_wrist": xy}, 1.0, 5.0) == []


def test_principal_axis_constant_input():
    assert np.all(F.principal_axis(np.ones((10, 2))) == 0)
