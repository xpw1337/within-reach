import math

import numpy as np
import pytest

from census.core import tiling
from census.core.triangulate import closest_points, ray_angle_deg, triangulate
from shared.types import Ray


def _ray_to(origin, target):
    d = np.subtract(target, origin)
    d = d / np.linalg.norm(d)
    return Ray(tuple(map(float, origin)), tuple(map(float, d)))


def test_two_views_of_one_point():
    target = (4.0, 1.6, 2.0)
    a = _ray_to((0, 1.5, 0), target)
    b = _ray_to((6, 1.5, -3), target)
    assert triangulate(a, b) == pytest.approx(target, abs=1e-9)


def test_closest_points_of_skew_lines():
    a = Ray((0, 0, 0), (1, 0, 0))
    b = Ray((0, 1, 5), (0, 0, -1))
    pa, pb, ta, tb = closest_points(a, b)
    assert pa == pytest.approx((0, 0, 0)) and pb == pytest.approx((0, 1, 0))
    assert (ta, tb) == pytest.approx((0, 5))
    # They miss by 1 m: rejected with the default tolerance, accepted with a looser one.
    a2 = Ray((-3, 0, 0), (1, 0, 0))
    assert triangulate(a2, b) is None
    assert triangulate(a2, b, max_gap_m=1.5) == pytest.approx((0, 0.5, 0))


def test_parallel_and_nearly_parallel_rejected():
    a = Ray((0, 0, 0), (1, 0, 0))
    assert closest_points(a, Ray((0, 1, 0), (1, 0, 0))) is None
    assert triangulate(a, Ray((0, 1, 0), (1, 0, 0))) is None
    tiny = (math.cos(math.radians(1)), math.sin(math.radians(1)), 0)
    assert ray_angle_deg(a, Ray((0, 0.5, 0), tiny)) == pytest.approx(1)
    assert triangulate(a, Ray((0, -0.5, 0), tiny)) is None


def test_behind_camera_and_out_of_range_rejected():
    target = (0.0, 1.5, 5.0)
    a = _ray_to((0, 1.5, 0), target)
    b = _ray_to((5, 1.5, 5), target)
    assert triangulate(a, b) == pytest.approx(target)
    flipped = Ray(b.origin, tuple(-c for c in b.direction))
    assert triangulate(a, flipped) is None
    far = (0.0, 1.5, 100.0)
    assert triangulate(_ray_to((0, 1.5, 0), far), _ray_to((10, 1.5, 0), far)) is None


def test_end_to_end_from_tile_pixels():
    """Two sweeps see the same AED; rays built from tile pixels meet at its position."""
    aed = np.array([3.0, 1.2, 4.0])
    sweeps = {
        "s1": ((0.0, 1.5, 0.0), None),
        "s2": ((6.0, 1.5, 1.0), (0.0, math.sin(0.4), 0.0, math.cos(0.4))),
    }
    rays = []
    for origin, rot in sweeps.values():
        h, p = tiling.world_heading_pitch(aed, origin, rot)
        spec = tiling.TileSpec(0, round(h / 60) * 60.0, 0.0, 90.0, 1025)  # nearest horizontal tile
        px, py = tiling.direction_to_tile_pixel(tiling.heading_pitch_to_direction(h, p), spec)
        rays.append(tiling.pixel_ray(px, py, spec, origin, rot))
    assert triangulate(*rays) == pytest.approx(tuple(aed), abs=1e-6)
