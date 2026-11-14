"""Synthetic COCO-17 skeletons and keypoint sequences for tests.

No images and no real people: poses are hand-placed stick figures in pixel space, proportioned
as fractions of a standing height ``H`` (image y grows downward, ``floor`` is the image y of the
floor under the person). A ``Clip`` strings poses into timed frames so the detector can be driven
with a fake clock.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

from vision.features import (
    L_ANKLE,
    L_EAR,
    L_ELBOW,
    L_EYE,
    L_HIP,
    L_KNEE,
    L_SHOULDER,
    L_WRIST,
    NOSE,
    R_ANKLE,
    R_EAR,
    R_ELBOW,
    R_EYE,
    R_HIP,
    R_KNEE,
    R_SHOULDER,
    R_WRIST,
    TrackObs,
)

H = 300.0  # standing height in pixels
FLOOR = 600.0


def _pose(points: dict[int, tuple[float, float]]) -> np.ndarray:
    k = np.zeros((17, 2), dtype=float)
    for idx, xy in points.items():
        k[idx] = xy
    return k


def standing(x0: float = 300.0, floor: float = FLOOR, h: float = H) -> np.ndarray:
    """Upright, facing the camera, arms down."""

    def p(dx: float, up: float) -> tuple[float, float]:
        return (x0 + dx * h, floor - up * h)

    return _pose(
        {
            NOSE: p(0, 0.93),
            L_EYE: p(-0.02, 0.95),
            R_EYE: p(0.02, 0.95),
            L_EAR: p(-0.04, 0.94),
            R_EAR: p(0.04, 0.94),
            L_SHOULDER: p(-0.11, 0.82),
            R_SHOULDER: p(0.11, 0.82),
            L_ELBOW: p(-0.13, 0.63),
            R_ELBOW: p(0.13, 0.63),
            L_WRIST: p(-0.14, 0.47),
            R_WRIST: p(0.14, 0.47),
            L_HIP: p(-0.06, 0.52),
            R_HIP: p(0.06, 0.52),
            L_KNEE: p(-0.06, 0.28),
            R_KNEE: p(0.06, 0.28),
            L_ANKLE: p(-0.06, 0.04),
            R_ANKLE: p(0.06, 0.04),
        }
    )


def lying(x_feet: float = 300.0, floor: float = FLOOR, h: float = H, raised: float = 0.0) -> np.ndarray:
    """On the side, body axis horizontal, head to the right, arms resting along the body.

    ``raised`` in [0, 1] lifts the left arm straight up (0 = resting, 1 = fully raised).
    """

    def p(s: float, up: float) -> tuple[float, float]:
        return (x_feet + s * h, floor - up * h)

    pts = {
        NOSE: p(0.93, 0.06),
        L_EYE: p(0.95, 0.07),
        R_EYE: p(0.95, 0.05),
        L_EAR: p(0.94, 0.08),
        R_EAR: p(0.94, 0.04),
        L_SHOULDER: p(0.82, 0.07),
        R_SHOULDER: p(0.82, 0.03),
        L_ELBOW: p(0.63, 0.08),
        R_ELBOW: p(0.63, 0.03),
        L_WRIST: p(0.50, 0.08),
        R_WRIST: p(0.50, 0.03),
        L_HIP: p(0.52, 0.07),
        R_HIP: p(0.52, 0.03),
        L_KNEE: p(0.28, 0.06),
        R_KNEE: p(0.28, 0.03),
        L_ANKLE: p(0.04, 0.05),
        R_ANKLE: p(0.04, 0.03),
    }
    if raised > 0:
        sx, sy = pts[L_SHOULDER]
        rest_e, rest_w = np.array(pts[L_ELBOW]), np.array(pts[L_WRIST])
        up_e = np.array((sx, sy - 0.17 * h))
        up_w = np.array((sx, sy - 0.33 * h))
        pts[L_ELBOW] = tuple(rest_e + (up_e - rest_e) * raised)
        pts[L_WRIST] = tuple(rest_w + (up_w - rest_w) * raised)
    return _pose(pts)


def sitting_chair(x0: float = 300.0, floor: float = FLOOR, h: float = H) -> np.ndarray:
    """On a chair seen from the side: torso upright, thighs horizontal, hands on the thighs."""

    def p(dx: float, up: float) -> tuple[float, float]:
        return (x0 + dx * h, floor - up * h)

    return _pose(
        {
            NOSE: p(0.03, 0.66),
            L_EYE: p(0.04, 0.68),
            R_EYE: p(0.04, 0.68),
            L_EAR: p(0.0, 0.67),
            R_EAR: p(0.0, 0.67),
            L_SHOULDER: p(0.0, 0.56),
            R_SHOULDER: p(0.0, 0.55),
            L_ELBOW: p(0.04, 0.40),
            R_ELBOW: p(0.04, 0.39),
            L_WRIST: p(0.15, 0.30),
            R_WRIST: p(0.15, 0.29),
            L_HIP: p(0.0, 0.26),
            R_HIP: p(0.0, 0.25),
            L_KNEE: p(0.22, 0.27),
            R_KNEE: p(0.22, 0.26),
            L_ANKLE: p(0.22, 0.04),
            R_ANKLE: p(0.22, 0.03),
        }
    )


def sitting_floor(x0: float = 300.0, floor: float = FLOOR, h: float = H) -> np.ndarray:
    """On the floor, legs stretched out, torso nearly upright: a wide box that must not count."""

    def p(dx: float, up: float) -> tuple[float, float]:
        return (x0 + dx * h, floor - up * h)

    return _pose(
        {
            NOSE: p(-0.03, 0.42),
            L_EYE: p(-0.02, 0.44),
            R_EYE: p(-0.02, 0.44),
            L_EAR: p(-0.06, 0.43),
            R_EAR: p(-0.06, 0.43),
            L_SHOULDER: p(-0.05, 0.33),
            R_SHOULDER: p(-0.05, 0.32),
            L_ELBOW: p(-0.02, 0.18),
            R_ELBOW: p(-0.02, 0.17),
            L_WRIST: p(0.05, 0.06),
            R_WRIST: p(0.05, 0.05),
            L_HIP: p(0.0, 0.05),
            R_HIP: p(0.0, 0.04),
            L_KNEE: p(0.28, 0.08),
            R_KNEE: p(0.28, 0.07),
            L_ANKLE: p(0.56, 0.04),
            R_ANKLE: p(0.56, 0.03),
        }
    )


def bending(x0: float = 300.0, floor: float = FLOOR, h: float = H) -> np.ndarray:
    """Standing but bent forward at the hips (picking something up): torso horizontal, hips high."""

    def p(dx: float, up: float) -> tuple[float, float]:
        return (x0 + dx * h, floor - up * h)

    return _pose(
        {
            NOSE: p(0.42, 0.50),
            L_EYE: p(0.43, 0.52),
            R_EYE: p(0.43, 0.52),
            L_EAR: p(0.40, 0.53),
            R_EAR: p(0.40, 0.53),
            L_SHOULDER: p(0.30, 0.53),
            R_SHOULDER: p(0.30, 0.52),
            L_ELBOW: p(0.32, 0.36),
            R_ELBOW: p(0.32, 0.35),
            L_WRIST: p(0.34, 0.20),
            R_WRIST: p(0.34, 0.19),
            L_HIP: p(0.0, 0.53),
            R_HIP: p(0.0, 0.52),
            L_KNEE: p(0.0, 0.28),
            R_KNEE: p(0.0, 0.28),
            L_ANKLE: p(0.0, 0.04),
            R_ANKLE: p(0.0, 0.04),
        }
    )


def bbox_of(kpts: np.ndarray, h: float = H) -> tuple[float, float, float, float]:
    """Person box around the keypoints, padded for the head top and the feet."""
    x1, y1 = kpts.min(axis=0)
    x2, y2 = kpts.max(axis=0)
    return (float(x1 - 0.05 * h), float(y1 - 0.07 * h), float(x2 + 0.05 * h), float(y2 + 0.03 * h))


def obs(track_id: int, kpts: np.ndarray, h: float = H, conf: np.ndarray | None = None) -> TrackObs:
    return TrackObs(track_id=track_id, bbox=bbox_of(kpts, h), keypoints=kpts.copy(), kp_conf=conf)


def lerp(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    return a + (b - a) * float(np.clip(u, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Timed sequences
# ---------------------------------------------------------------------------

TrackFn = Callable[[float, float], TrackObs | None]  # (local time u, segment length) -> observation


def hold(track_id: int, kpts: np.ndarray) -> TrackFn:
    return lambda u, dur: obs(track_id, kpts)


def move(track_id: int, a: np.ndarray, b: np.ndarray) -> TrackFn:
    return lambda u, dur: obs(track_id, lerp(a, b, u / dur if dur > 0 else 1.0))


def shake(
    track_id: int,
    kpts: np.ndarray,
    hz: float,
    amp: float,
    limbs: tuple[int, ...] = (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE),
) -> TrackFn:
    """Rhythmic vertical motion of the given keypoints, ``amp`` pixels at ``hz``."""

    def fn(u: float, dur: float) -> TrackObs:
        k = kpts.copy()
        d = amp * math.sin(2 * math.pi * hz * u)
        for i in limbs:
            k[i, 1] += d
        return obs(track_id, k)

    return fn


def raise_arm(track_id: int, x_feet: float = 300.0, rise_s: float = 0.3) -> TrackFn:
    """Lying, lifting the left arm straight up over ``rise_s`` and holding it."""
    return lambda u, dur: obs(track_id, lying(x_feet, raised=min(1.0, u / rise_s)))


def flail(track_id: int, x_feet: float = 300.0, hz: float = 2.0) -> TrackFn:
    """Lying, arm swinging between resting and raised, never held."""
    return lambda u, dur: obs(track_id, lying(x_feet, raised=0.5 - 0.5 * math.cos(2 * math.pi * hz * u)))


class Clip:
    """Frames of (t, [TrackObs]) at a fixed frame rate, built from consecutive segments."""

    def __init__(self, fps: float = 15.0, noise_px: float = 0.0, seed: int = 0):
        self.fps = fps
        self.noise_px = noise_px
        self.rng = np.random.default_rng(seed)
        self.frames: list[tuple[float, list[TrackObs]]] = []
        self.t = 0.0
        self._n = 0

    def add(self, seconds: float, *tracks: TrackFn) -> Clip:
        start = self.t
        n = round(seconds * self.fps)
        for i in range(n):
            u = i / self.fps
            frame: list[TrackObs] = []
            for fn in tracks:
                o = fn(u, seconds)
                if o is None:
                    continue
                if self.noise_px > 0:
                    o.keypoints = o.keypoints + self.rng.normal(0.0, self.noise_px, o.keypoints.shape)
                frame.append(o)
            self.frames.append((self._n / self.fps, frame))
            self._n += 1
        self.t = start + n / self.fps
        return self
