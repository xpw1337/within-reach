import math

import numpy as np
import pytest

from census.core import tiling
from census.core.tiling import TileSpec


def _equirect_with_marker(h: int, w: int, heading_deg: float, pitch_deg: float, radius_deg: float = 2.0):
    """Black equirectangular image with a white disc centered at (heading, pitch)."""
    cols = (np.arange(w) + 0.5) / w * 360.0 - 180.0  # py360convert coor2uv for u
    rows = 90.0 - (np.arange(h) + 0.5) / h * 180.0  # and for v (up positive)
    u, v = np.meshgrid(cols, rows)
    target = tiling.heading_pitch_to_direction(heading_deg, pitch_deg)
    ur, vr = np.radians(u), np.radians(v)
    dirs = np.stack([np.cos(vr) * np.sin(ur), np.sin(vr), np.cos(vr) * np.cos(ur)], -1)
    ang = np.degrees(np.arccos(np.clip(dirs @ target, -1, 1)))
    img = np.zeros((h, w, 3), np.uint8)
    img[ang < radius_deg] = 255
    return img


def _centroid(tile_img):
    ys, xs = np.nonzero(tile_img[..., 0] > 127)
    assert len(xs) > 0, "marker not in tile"
    return xs.mean(), ys.mean()


def test_default_specs():
    specs = tiling.tile_specs(8, 90, 512)
    assert len(specs) == 8
    assert [s.heading_deg for s in specs[:6]] == [0, 60, 120, 180 - 360, -120, -60]
    assert (specs[6].pitch_deg, specs[7].pitch_deg) == (90, -90)
    assert all(s.fov_deg == 90 and s.size_px == 512 for s in specs)
    assert [s.index for s in specs] == list(range(8))
    cube = tiling.tile_specs(6)
    assert [s.heading_deg for s in cube[:4]] == [0, 90, -180, -90]


@pytest.mark.parametrize("h,p", [(0, 0), (45, 10), (-120, -30), (179, 80), (10, -89)])
def test_direction_round_trip(h, p):
    d = tiling.heading_pitch_to_direction(h, p)
    assert np.linalg.norm(d) == pytest.approx(1)
    h2, p2 = tiling.direction_to_heading_pitch(d)
    assert p2 == pytest.approx(p, abs=1e-9)
    assert (h2 - h + 180) % 360 - 180 == pytest.approx(0, abs=1e-9)


def test_tile_center_and_edges():
    spec = TileSpec(0, heading_deg=30, pitch_deg=20, fov_deg=90, size_px=101)
    assert tiling.tile_pixel_to_heading_pitch(50, 50, spec) == pytest.approx((30, 20))
    flat = TileSpec(0, heading_deg=0, pitch_deg=0, fov_deg=90, size_px=101)
    # Right edge of a 90 degree tile looks 45 degrees right; top edge 45 degrees up.
    assert tiling.tile_pixel_to_heading_pitch(100, 50, flat) == pytest.approx((45, 0))
    assert tiling.tile_pixel_to_heading_pitch(50, 0, flat) == pytest.approx((0, 45))
    assert tiling.tile_pixel_to_heading_pitch(0, 50, flat) == pytest.approx((-45, 0))


def test_pixel_direction_inverse():
    spec = TileSpec(0, heading_deg=-70, pitch_deg=35, fov_deg=90, size_px=640)
    for px, py in [(0, 0), (639, 0), (320, 320), (100, 500), (639, 639)]:
        d = tiling.tile_pixel_to_direction(px, py, spec)
        back = tiling.direction_to_tile_pixel(d, spec)
        assert back == pytest.approx((px, py), abs=1e-6)
    assert tiling.direction_to_tile_pixel(tiling.heading_pitch_to_direction(110, -35), spec) is None


@pytest.mark.parametrize(
    "marker,spec",
    [
        ((50, 10), TileSpec(0, 45, 0, 90, 257)),
        ((-40, -15), TileSpec(1, -45, 0, 90, 257)),
        ((100, 50), TileSpec(2, 90, 40, 90, 257)),
        ((170, 0), TileSpec(3, -175, 0, 90, 257)),  # across the image seam
        ((20, 80), TileSpec(4, 0, 90, 90, 257)),  # ceiling tile
    ],
)
def test_matches_py360convert_e2p(marker, spec):
    """The pixel math agrees with what py360convert actually renders."""
    pano = _equirect_with_marker(720, 1440, *marker)
    (tile,) = tiling.tile_pano(pano, [spec])
    assert tile.image.shape == (257, 257, 3)
    px, py = _centroid(tile.image)
    expected = tiling.direction_to_tile_pixel(tiling.heading_pitch_to_direction(*marker), spec)
    assert (px, py) == pytest.approx(expected, abs=1.5)
    h, p = tiling.tile_pixel_to_heading_pitch(px, py, spec)
    assert p == pytest.approx(marker[1], abs=0.6)
    assert (h - marker[0] + 180) % 360 - 180 == pytest.approx(
        0, abs=0.6 / max(0.05, math.cos(math.radians(p)))
    )


def test_pixel_to_world_ray_known_example():
    """Sweep at (1, 1.5, 3); tile facing heading 90 (to the right of the image center).

    With no rotation the panorama frame is the model frame, so the tile center looks along +x.
    With the sweep rotated +90 degrees about y (quaternion (0, sin45, 0, cos45)), panorama +x maps to
    model -z, so the same pixel looks along -z.
    """
    spec = TileSpec(0, heading_deg=90, pitch_deg=0, fov_deg=90, size_px=101)
    ray = tiling.pixel_ray(50, 50, spec, origin=(1.0, 1.5, 3.0))
    assert ray.origin == (1.0, 1.5, 3.0)
    assert ray.direction == pytest.approx((1.0, 0.0, 0.0), abs=1e-12)

    s = math.sqrt(0.5)
    rotated = tiling.pixel_ray(50, 50, spec, origin=(1.0, 1.5, 3.0), rotation=(0.0, s, 0.0, s))
    assert rotated.direction == pytest.approx((0.0, 0.0, -1.0), abs=1e-12)

    # Top-center pixel of the same tile looks 45 degrees up.
    up = tiling.pixel_ray(50, 0, spec, origin=(0, 0, 0))
    assert up.direction == pytest.approx((math.sqrt(0.5), math.sqrt(0.5), 0.0), abs=1e-12)


def test_world_heading_pitch_inverts_rays():
    rot = (0.1, 0.3, -0.2, 0.92)
    origin = (2.0, 1.4, -5.0)
    target = (6.0, 2.4, -1.0)
    h, p = tiling.world_heading_pitch(target, origin, rot)
    ray = tiling.heading_pitch_ray(h, p, origin, rot)
    to_target = np.subtract(target, origin)
    assert ray.direction == pytest.approx(tuple(to_target / np.linalg.norm(to_target)), abs=1e-9)


def test_bbox_helpers():
    spec = TileSpec(0, 0, 0, 90, 201)
    assert tiling.bbox_heading_pitch([0.4, 0.4, 0.6, 0.6], spec) == pytest.approx((0, 0), abs=1e-9)
    img = np.arange(100 * 200 * 3, dtype=np.uint32).reshape(100, 200, 3).astype(np.uint8)
    c = tiling.crop(img, [0.25, 0.5, 0.5, 0.75], pad_frac=0.0)
    assert c.shape == (25, 50, 3)
    padded = tiling.crop(img, [0.0, 0.0, 0.1, 0.1], pad_frac=0.5)
    assert padded.shape == (15, 30, 3)  # clipped at the image border
    assert tiling.valid_bbox([0.1, 0.2, 0.3, 0.4]) and not tiling.valid_bbox([0.3, 0.2, 0.1, 0.4])
    assert not tiling.valid_bbox([0, 0, 1.2, 0.5])
    assert tiling.bbox_area_frac([0, 0, 0.5, 0.5]) == 0.25


def test_downscale_and_jpeg():
    img = np.zeros((1024, 512, 3), np.uint8)
    small = tiling.downscale(img, 256)
    assert small.shape == (256, 128, 3)
    assert tiling.downscale(small, 512) is small
    assert tiling.to_jpeg(small)[:2] == b"\xff\xd8"
