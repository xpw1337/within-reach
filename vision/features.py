"""Pure pose features on COCO-17 keypoints.

Coordinates are image pixels with y growing downward (OpenCV and Ultralytics convention).
Nothing here holds state, reads env or touches a camera: every threshold is a parameter, so the
detector (detector.py) owns the rules and these functions stay unit-testable on synthetic poses.

Features (spec section 9.9):
- torso angle from vertical (0 = upright, 90 = horizontal)
- bounding-box aspect ratio (width / height)
- hip height (image y of the hip midpoint)
- wrist above shoulder
- limb oscillation frequency (windowed FFT on wrist / ankle tracks)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# COCO 17-keypoint layout used by Ultralytics pose models.
NOSE = 0
L_EYE, R_EYE = 1, 2
L_EAR, R_EAR = 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16
NUM_KEYPOINTS = 17

# Limbs whose motion is checked for rhythmic movement (spec: "wrist or ankle keypoints").
LIMBS: dict[str, int] = {
    "l_wrist": L_WRIST,
    "r_wrist": R_WRIST,
    "l_ankle": L_ANKLE,
    "r_ankle": R_ANKLE,
}
WRISTS = ("l_wrist", "r_wrist")

# Bones drawn by the skeleton-only debug overlay.
SKELETON: tuple[tuple[int, int], ...] = (
    (L_SHOULDER, R_SHOULDER),
    (L_SHOULDER, L_ELBOW),
    (L_ELBOW, L_WRIST),
    (R_SHOULDER, R_ELBOW),
    (R_ELBOW, R_WRIST),
    (L_SHOULDER, L_HIP),
    (R_SHOULDER, R_HIP),
    (L_HIP, R_HIP),
    (L_HIP, L_KNEE),
    (L_KNEE, L_ANKLE),
    (R_HIP, R_KNEE),
    (R_KNEE, R_ANKLE),
)

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels


@dataclass
class TrackObs:
    """One tracked person in one frame, as produced by tracker.py."""

    track_id: int
    bbox: BBox
    keypoints: np.ndarray  # (17, 2) pixel x, y
    kp_conf: np.ndarray | None = None  # (17,) per-keypoint confidence; None means all trusted


@dataclass
class PoseFeatures:
    """Per-frame features of one track. ``None`` means the keypoints needed were not visible."""

    torso_angle: float | None  # degrees from vertical
    thigh_angle: float | None  # degrees from vertical, mean of the visible thighs
    aspect: float  # bbox width / height
    hip_y: float | None  # image y of the hip midpoint
    bbox_w: float
    bbox_h: float
    body_len: float  # max(bbox_w, bbox_h): body length whether standing or lying
    center: tuple[float, float]
    wrist_rise: float | None  # (higher shoulder y - higher wrist y) / body_len; > 0 means above
    limbs: dict[str, tuple[float, float] | None]  # wrist and ankle positions for oscillation
    legs_visible: bool = True  # at least one knee or ankle seen (False: the body is cut off)
    head_y: float | None = None  # image y of the visible head and shoulder points (mean)
    axis_angle: float | None = None  # head-to-lowest-visible-body-point line, degrees from vertical
    top_y: float = 0.0  # top edge of the box


# ---------------------------------------------------------------------------
# Keypoint helpers
# ---------------------------------------------------------------------------


def _visible(kp_conf: np.ndarray | None, idx: int, min_conf: float) -> bool:
    return kp_conf is None or float(kp_conf[idx]) >= min_conf


def _point(kpts: np.ndarray, kp_conf: np.ndarray | None, idx: int, min_conf: float) -> np.ndarray | None:
    if not _visible(kp_conf, idx, min_conf):
        return None
    p = np.asarray(kpts[idx], dtype=float)
    if not np.all(np.isfinite(p)):
        return None
    return p


def _midpoint(
    kpts: np.ndarray, kp_conf: np.ndarray | None, a: int, b: int, min_conf: float
) -> np.ndarray | None:
    """Mean of the visible points among ``a`` and ``b``; ``None`` if neither is visible."""
    pts = [
        p for p in (_point(kpts, kp_conf, a, min_conf), _point(kpts, kp_conf, b, min_conf)) if p is not None
    ]
    if not pts:
        return None
    return np.mean(pts, axis=0)


def angle_from_vertical(top: np.ndarray, bottom: np.ndarray) -> float | None:
    """Angle in degrees between the segment and the image vertical: 0 upright, 90 horizontal."""
    dx = float(bottom[0] - top[0])
    dy = float(bottom[1] - top[1])
    if dx == 0.0 and dy == 0.0:
        return None
    return math.degrees(math.atan2(abs(dx), abs(dy)))


# ---------------------------------------------------------------------------
# Single-frame features
# ---------------------------------------------------------------------------


def torso_angle(kpts: np.ndarray, kp_conf: np.ndarray | None = None, min_conf: float = 0.5) -> float | None:
    """Angle of the shoulder-midpoint to hip-midpoint line from vertical, in degrees."""
    shoulders = _midpoint(kpts, kp_conf, L_SHOULDER, R_SHOULDER, min_conf)
    hips = _midpoint(kpts, kp_conf, L_HIP, R_HIP, min_conf)
    if shoulders is None or hips is None:
        return None
    return angle_from_vertical(shoulders, hips)


def thigh_angle(kpts: np.ndarray, kp_conf: np.ndarray | None = None, min_conf: float = 0.5) -> float | None:
    """Mean angle of the visible hip-to-knee segments from vertical, in degrees.

    Near 0 when standing, near 90 when sitting on a chair (thighs horizontal).
    """
    angles = []
    for hip, knee in ((L_HIP, L_KNEE), (R_HIP, R_KNEE)):
        h = _point(kpts, kp_conf, hip, min_conf)
        k = _point(kpts, kp_conf, knee, min_conf)
        if h is not None and k is not None:
            a = angle_from_vertical(h, k)
            if a is not None:
                angles.append(a)
    if not angles:
        return None
    return float(np.mean(angles))


HEAD_POINTS = (NOSE, L_EYE, R_EYE, L_EAR, R_EAR, L_SHOULDER, R_SHOULDER)


def _mean_of(kpts: np.ndarray, kp_conf: np.ndarray | None, idxs: tuple[int, ...], min_conf: float) -> np.ndarray | None:
    pts = [p for i in idxs if (p := _point(kpts, kp_conf, i, min_conf)) is not None]
    return None if not pts else np.mean(np.asarray(pts, dtype=float), axis=0)


def head_height(kpts: np.ndarray, kp_conf: np.ndarray | None = None, min_conf: float = 0.5) -> float | None:
    """Image y of the head and shoulders (mean of the visible points). Webcams see these reliably."""
    p = _mean_of(kpts, kp_conf, HEAD_POINTS, min_conf)
    return None if p is None else float(p[1])


def body_axis_angle(kpts: np.ndarray, kp_conf: np.ndarray | None = None, min_conf: float = 0.5) -> float | None:
    """Angle from vertical of the line from the head to the lowest visible body part (ankles, else
    knees, else hips). Works when the hips are not found, which is common on a laptop webcam."""
    head = _mean_of(kpts, kp_conf, HEAD_POINTS, min_conf)
    if head is None:
        return None
    for group in ((L_ANKLE, R_ANKLE), (L_KNEE, R_KNEE), (L_HIP, R_HIP)):
        low = _mean_of(kpts, kp_conf, group, min_conf)
        if low is not None:
            return angle_from_vertical(head, low)
    return None


def bbox_aspect(bbox: BBox) -> float:
    """Width / height of the box. A degenerate box with no height is treated as infinitely wide."""
    x1, y1, x2, y2 = bbox
    w = max(0.0, float(x2) - float(x1))
    h = max(0.0, float(y2) - float(y1))
    if h == 0.0:
        return math.inf if w > 0 else 0.0
    return w / h


def hip_height(kpts: np.ndarray, kp_conf: np.ndarray | None = None, min_conf: float = 0.5) -> float | None:
    """Image y of the hip midpoint (pixels). Larger means lower in the frame, nearer the floor."""
    hips = _midpoint(kpts, kp_conf, L_HIP, R_HIP, min_conf)
    return None if hips is None else float(hips[1])


def wrist_rise(
    kpts: np.ndarray, body_len: float, kp_conf: np.ndarray | None = None, min_conf: float = 0.5
) -> float | None:
    """How far the highest visible wrist is above the highest visible shoulder, in body lengths.

    Positive means above. Measured against the higher of the two shoulders, which is the stricter
    choice when the person lies on their side. ``None`` if no wrist or no shoulder is visible.
    """
    shoulders = [p for i in (L_SHOULDER, R_SHOULDER) if (p := _point(kpts, kp_conf, i, min_conf)) is not None]
    wrists = [p for i in (L_WRIST, R_WRIST) if (p := _point(kpts, kp_conf, i, min_conf)) is not None]
    if not shoulders or not wrists or body_len <= 0:
        return None
    top_shoulder_y = min(float(p[1]) for p in shoulders)
    top_wrist_y = min(float(p[1]) for p in wrists)
    return (top_shoulder_y - top_wrist_y) / body_len


def wrist_above_shoulder(
    kpts: np.ndarray,
    body_len: float,
    margin: float,
    kp_conf: np.ndarray | None = None,
    min_conf: float = 0.5,
) -> bool:
    """True if a wrist is above the higher shoulder by at least ``margin`` body lengths."""
    rise = wrist_rise(kpts, body_len, kp_conf, min_conf)
    return rise is not None and rise >= margin


LEG_POINTS = (13, 14, 15, 16)  # COCO knees and ankles


def compute_features(obs: TrackObs, min_conf: float = 0.5) -> PoseFeatures:
    """All single-frame features of one tracked person."""
    x1, y1, x2, y2 = (float(v) for v in obs.bbox)
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    body_len = max(w, h)
    kpts = np.asarray(obs.keypoints, dtype=float)
    conf = None if obs.kp_conf is None else np.asarray(obs.kp_conf, dtype=float)
    limbs: dict[str, tuple[float, float] | None] = {}
    for name, idx in LIMBS.items():
        p = _point(kpts, conf, idx, min_conf)
        limbs[name] = None if p is None else (float(p[0]), float(p[1]))
    return PoseFeatures(
        torso_angle=torso_angle(kpts, conf, min_conf),
        thigh_angle=thigh_angle(kpts, conf, min_conf),
        aspect=bbox_aspect(obs.bbox),
        hip_y=hip_height(kpts, conf, min_conf),
        bbox_w=w,
        bbox_h=h,
        body_len=body_len,
        center=((x1 + x2) / 2.0, (y1 + y2) / 2.0),
        wrist_rise=wrist_rise(kpts, body_len, conf, min_conf),
        limbs=limbs,
        legs_visible=any(_visible(conf, i, min_conf) for i in LEG_POINTS),
        head_y=head_height(kpts, conf, min_conf),
        axis_angle=body_axis_angle(kpts, conf, min_conf),
        top_y=y1,
    )


# ---------------------------------------------------------------------------
# Box geometry (used for re-association and "second track near the victim")
# ---------------------------------------------------------------------------


def iou(a: BBox, b: BBox) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return 0.0 if union <= 0 else inter / union


def box_gap(a: BBox, b: BBox) -> float:
    """Shortest distance between two boxes in pixels; 0 if they touch or overlap."""
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return math.hypot(dx, dy)


def center_distance(a: BBox, b: BBox) -> float:
    return math.hypot((a[0] + a[2]) / 2 - (b[0] + b[2]) / 2, (a[1] + a[3]) / 2 - (b[1] + b[3]) / 2)


# ---------------------------------------------------------------------------
# Limb oscillation (possible_seizure)
# ---------------------------------------------------------------------------


@dataclass
class Oscillation:
    """Dominant rhythmic component of one limb track inside a frequency band."""

    limb: str
    freq_hz: float
    amplitude: float  # same units as the input (pixels, or body lengths if normalized)
    peak_ratio: float  # share of the signal's power in the peak (0..1): how rhythmic it is


def principal_axis(xy: np.ndarray) -> np.ndarray:
    """Project 2D points onto their direction of largest variance (1D signal, mean removed)."""
    centered = xy - xy.mean(axis=0)
    if not np.any(centered):
        return np.zeros(len(xy))
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    return centered @ vt[0]


def dominant_frequency(
    t: np.ndarray, x: np.ndarray, min_hz: float, max_hz: float, *, limb: str = ""
) -> Oscillation | None:
    """Strongest periodic component of ``x(t)`` between ``min_hz`` and ``max_hz``.

    The samples are resampled onto a uniform grid at their mean rate, linearly detrended,
    Hann-windowed and zero-padded before the FFT. Frequencies at or above the Nyquist limit of the
    actual frame rate are never reported. Returns ``None`` if there are too few samples, the band
    is not observable at this frame rate, or no spectral peak lies inside the band.
    """
    t = np.asarray(t, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(t)
    if n < 8:
        return None
    duration = float(t[-1] - t[0])
    if duration <= 0:
        return None
    fs = (n - 1) / duration
    grid = np.linspace(t[0], t[-1], n)
    xu = np.interp(grid, t, x)
    slope, intercept = np.polyfit(grid - grid[0], xu, 1)
    xu = xu - (slope * (grid - grid[0]) + intercept)
    window = np.hanning(n)
    n_fft = 1 << math.ceil(math.log2(n * 4))
    spec = np.fft.rfft(xu * window, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    power = np.abs(spec) ** 2
    nyquist = fs / 2.0
    band = (freqs >= min_hz) & (freqs <= max_hz) & (freqs < nyquist)
    if not np.any(band):
        return None
    # Only true spectral peaks count. Without this, a single slow movement (raising a hand) leaks
    # into the bottom of the band and its strongest in-band bin is just the falling edge of a
    # low-frequency lobe.
    interior = np.zeros_like(band)
    interior[1:-1] = (power[1:-1] >= power[:-2]) & (power[1:-1] >= power[2:]) & (power[1:-1] > 0)
    band_idx = np.flatnonzero(band & interior)
    if len(band_idx) == 0:
        return None
    k = int(band_idx[np.argmax(power[band_idx])])
    f_peak = float(freqs[k])
    # Power of the peak's main lobe versus everything above DC.
    lobe = np.abs(freqs - f_peak) <= 1.5 / duration
    above_dc = freqs > 0.5 / duration
    total = float(power[above_dc].sum())
    peak_ratio = 0.0 if total <= 0 else float(power[lobe & above_dc].sum()) / total
    amplitude = 2.0 * float(np.abs(spec[k])) / float(window.sum())
    return Oscillation(limb=limb, freq_hz=f_peak, amplitude=amplitude, peak_ratio=min(1.0, peak_ratio))


def limb_oscillation(
    t: np.ndarray,
    limb_xy: dict[str, np.ndarray],
    min_hz: float,
    max_hz: float,
    *,
    min_samples: int = 8,
) -> list[Oscillation]:
    """Dominant oscillation of each limb track.

    ``limb_xy`` maps a limb name to an (n, 2) array aligned with ``t``; rows with NaN (keypoint not
    visible in that frame) are dropped per limb. Each limb is reduced to its principal axis of
    motion before the frequency estimate, so the direction of the shaking does not matter.
    """
    t = np.asarray(t, dtype=float)
    out: list[Oscillation] = []
    for name, xy in limb_xy.items():
        xy = np.asarray(xy, dtype=float)
        ok = np.all(np.isfinite(xy), axis=1)
        if int(ok.sum()) < max(8, min_samples):
            continue
        signal = principal_axis(xy[ok])
        est = dominant_frequency(t[ok], signal, min_hz, max_hz, limb=name)
        if est is not None:
            out.append(est)
    return out
