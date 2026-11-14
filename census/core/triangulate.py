"""Closest point between two viewing rays (spec section 9.3, double-check step).

Pure function. A match seen from two panoramas is pinned at the midpoint of the shortest segment
between the two rays. ``None`` tells the caller to pin at the viewing sweep instead: rays nearly
parallel, the closest points behind either camera, too far away, or the rays miss each other by
more than the tolerance.
"""

from __future__ import annotations

import math

import numpy as np

from shared.types import Ray

MAX_GAP_M = 0.75  # rays that miss each other by more than this are not the same object
MIN_ANGLE_DEG = 3.0  # below this the depth is unreliable
MAX_RANGE_M = 40.0  # equipment farther than this from either sweep is not trusted


def closest_points(ray_a: Ray, ray_b: Ray) -> tuple[np.ndarray, np.ndarray, float, float] | None:
    """Closest points on the two infinite lines and their parameters ``(pa, pb, ta, tb)``.

    ``pa = origin_a + ta * dir_a``. Returns None for parallel lines.
    """
    oa, ob = np.asarray(ray_a.origin, float), np.asarray(ray_b.origin, float)
    da, db = np.asarray(ray_a.direction, float), np.asarray(ray_b.direction, float)
    da, db = da / np.linalg.norm(da), db / np.linalg.norm(db)
    w0 = oa - ob
    b = float(da @ db)
    d, e = float(da @ w0), float(db @ w0)
    denom = 1.0 - b * b  # a = c = 1 for unit vectors
    if denom < 1e-12:
        return None
    ta = (b * e - d) / denom
    tb = (e - b * d) / denom
    return oa + ta * da, ob + tb * db, ta, tb


def ray_angle_deg(ray_a: Ray, ray_b: Ray) -> float:
    da, db = np.asarray(ray_a.direction, float), np.asarray(ray_b.direction, float)
    c = float(da @ db) / (np.linalg.norm(da) * np.linalg.norm(db))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def triangulate(
    ray_a: Ray,
    ray_b: Ray,
    *,
    max_gap_m: float = MAX_GAP_M,
    min_angle_deg: float = MIN_ANGLE_DEG,
    max_range_m: float = MAX_RANGE_M,
) -> tuple[float, float, float] | None:
    """The 3D point both rays look at (midpoint of their closest approach), or None."""
    angle = ray_angle_deg(ray_a, ray_b)
    if angle < min_angle_deg or angle > 180.0 - min_angle_deg:
        return None
    cp = closest_points(ray_a, ray_b)
    if cp is None:
        return None
    pa, pb, ta, tb = cp
    if ta <= 0 or tb <= 0:  # behind a camera
        return None
    if ta > max_range_m or tb > max_range_m:
        return None
    if float(np.linalg.norm(pa - pb)) > max_gap_m:
        return None
    mid = (pa + pb) / 2
    return float(mid[0]), float(mid[1]), float(mid[2])
