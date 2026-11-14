"""Equirectangular panorama -> perspective tiles, and tile pixels -> world-space rays (spec section 9.3).

Pure functions: no IO, no network, no environment reads.

Frames and units
----------------
Panorama frame (the frame of the equirectangular image, as py360convert uses it): ``+z`` looks at
the center column of the image, ``+x`` is to the right, ``+y`` is up.

- ``heading_deg``: horizontal angle in the panorama frame, 0 at the image center column, positive
  to the right, in [-180, 180). It equals py360convert's ``u_deg``.
- ``pitch_deg``: vertical angle, positive up, in [-90, 90]. It equals py360convert's ``v_deg``.

World frame: the scan's model space (meters, ``y`` up; docs/CONTRACTS.md section 1). A sweep's
``rotation`` (quaternion ``(x, y, z, w)``, from the dataset) turns panorama-frame directions into
world directions. ``None`` means the panorama frame is taken to be aligned with the model axes; how
the real dataset defines this rotation is an open question for data inspection (data/DESIGN.md).

Bounding boxes from the first pass are normalized ``[x_min, y_min, x_max, y_max]`` fractions of the
tile width and height (0..1, origin top-left), independent of the tile resolution.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from shared.types import Ray

BBox = Sequence[float]  # [x_min, y_min, x_max, y_max], normalized 0..1


@dataclass(frozen=True)
class TileSpec:
    index: int
    heading_deg: float
    pitch_deg: float
    fov_deg: float = 90.0
    size_px: int = 1024


@dataclass
class Tile:
    spec: TileSpec
    image: np.ndarray  # H x W x C, same dtype as the panorama


def tile_specs(n_tiles: int = 8, fov_deg: float = 90.0, size_px: int = 1024) -> list[TileSpec]:
    """Default layout: ``n_tiles - 2`` tiles around the horizon (evenly spaced, starting at heading 0),
    one looking straight up (ceiling: smoke detectors, sprinklers) and one straight down (floor stands).

    With ``n_tiles=6`` this is the cube layout; with 8 the six horizontal tiles overlap by 30 degrees at
    90 degree FOV, so equipment on a tile edge is fully inside a neighbor tile.
    """
    if n_tiles < 3:
        raise ValueError("need at least 3 tiles (one horizontal, up, down)")
    n_h = n_tiles - 2
    specs = [TileSpec(i, _wrap_deg(i * 360.0 / n_h), 0.0, fov_deg, size_px) for i in range(n_h)]
    specs.append(TileSpec(n_h, 0.0, 90.0, fov_deg, size_px))
    specs.append(TileSpec(n_h + 1, 0.0, -90.0, fov_deg, size_px))
    return specs


def _wrap_deg(a: float) -> float:
    return (a + 180.0) % 360.0 - 180.0


def tile_pano(equirect: np.ndarray, specs: Sequence[TileSpec]) -> list[Tile]:
    """Render perspective tiles from an equirectangular image (H x W or H x W x C)."""
    import py360convert

    return [
        Tile(
            spec,
            py360convert.e2p(
                equirect,
                fov_deg=spec.fov_deg,
                u_deg=spec.heading_deg,
                v_deg=spec.pitch_deg,
                out_hw=(spec.size_px, spec.size_px),
            ),
        )
        for spec in specs
    ]


def render_tile(
    equirect: np.ndarray,
    heading_deg: float,
    pitch_deg: float,
    fov_deg: float = 90.0,
    size_px: int = 1024,
    index: int = -1,
) -> Tile:
    """One tile facing an arbitrary direction (used by the second-view check)."""
    return tile_pano(equirect, [TileSpec(index, _wrap_deg(heading_deg), pitch_deg, fov_deg, size_px)])[0]


# ---------------------------------------------------------------------------
# Directions
# ---------------------------------------------------------------------------


def heading_pitch_to_direction(heading_deg: float, pitch_deg: float) -> np.ndarray:
    """Unit vector in the panorama frame."""
    u, v = math.radians(heading_deg), math.radians(pitch_deg)
    return np.array([math.cos(v) * math.sin(u), math.sin(v), math.cos(v) * math.cos(u)])


def direction_to_heading_pitch(d: Sequence[float]) -> tuple[float, float]:
    x, y, z = (float(c) for c in d)
    heading = math.degrees(math.atan2(x, z))
    pitch = math.degrees(math.atan2(y, math.hypot(x, z)))
    return _wrap_deg(heading), pitch


def _camera_to_pano(spec: TileSpec, c: np.ndarray) -> np.ndarray:
    """Rotate a camera-frame vector (x right, y up, z forward) into the panorama frame:
    pitch about x (positive tilts forward toward up), then heading about y (positive turns right)."""
    p, h = math.radians(spec.pitch_deg), math.radians(spec.heading_deg)
    x, y, z = c
    y, z = y * math.cos(p) + z * math.sin(p), -y * math.sin(p) + z * math.cos(p)
    x, z = x * math.cos(h) + z * math.sin(h), -x * math.sin(h) + z * math.cos(h)
    return np.array([x, y, z])


def _pano_to_camera(spec: TileSpec, d: np.ndarray) -> np.ndarray:
    p, h = math.radians(spec.pitch_deg), math.radians(spec.heading_deg)
    x, y, z = d
    x, z = x * math.cos(h) - z * math.sin(h), x * math.sin(h) + z * math.cos(h)
    y, z = y * math.cos(p) - z * math.sin(p), y * math.sin(p) + z * math.cos(p)
    return np.array([x, y, z])


def tile_pixel_to_direction(
    px: float, py: float, spec: TileSpec, size_hw: tuple[int, int] | None = None
) -> np.ndarray:
    """Unit direction in the panorama frame for a tile pixel (column ``px``, row ``py``).

    Matches py360convert's perspective grid: pixel centers span ``[-tan(fov/2), tan(fov/2)]`` with
    column 0 and column ``w-1`` exactly on the edges.
    """
    h, w = size_hw or (spec.size_px, spec.size_px)
    t = math.tan(math.radians(spec.fov_deg) / 2)
    xc = (-1.0 + 2.0 * px / (w - 1)) * t
    yc = (1.0 - 2.0 * py / (h - 1)) * t
    d = _camera_to_pano(spec, np.array([xc, yc, 1.0]))
    return d / np.linalg.norm(d)


def direction_to_tile_pixel(
    d: Sequence[float], spec: TileSpec, size_hw: tuple[int, int] | None = None
) -> tuple[float, float] | None:
    """Tile pixel where a panorama-frame direction lands, or None if it is behind the tile or outside it."""
    h, w = size_hw or (spec.size_px, spec.size_px)
    c = _pano_to_camera(spec, np.asarray(d, dtype=float))
    if c[2] <= 1e-9:
        return None
    t = math.tan(math.radians(spec.fov_deg) / 2)
    xc, yc = c[0] / c[2] / t, c[1] / c[2] / t
    if abs(xc) > 1 or abs(yc) > 1:
        return None
    return (xc + 1.0) * (w - 1) / 2.0, (1.0 - yc) * (h - 1) / 2.0


def tile_pixel_to_heading_pitch(
    px: float, py: float, spec: TileSpec, size_hw: tuple[int, int] | None = None
) -> tuple[float, float]:
    return direction_to_heading_pitch(tile_pixel_to_direction(px, py, spec, size_hw))


def bbox_center_px(bbox: BBox, size_hw: tuple[int, int]) -> tuple[float, float]:
    h, w = size_hw
    x0, y0, x1, y1 = bbox
    return (x0 + x1) / 2 * (w - 1), (y0 + y1) / 2 * (h - 1)


def bbox_heading_pitch(
    bbox: BBox, spec: TileSpec, size_hw: tuple[int, int] | None = None
) -> tuple[float, float]:
    """Heading and pitch (panorama frame) of a normalized bbox center. Stored on ``detections``."""
    hw = size_hw or (spec.size_px, spec.size_px)
    return tile_pixel_to_heading_pitch(*bbox_center_px(bbox, hw), spec, hw)


# ---------------------------------------------------------------------------
# World rays
# ---------------------------------------------------------------------------


def _quat_matrix(q: Sequence[float]) -> np.ndarray:
    x, y, z, w = (float(c) for c in q)
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0:
        raise ValueError("zero quaternion")
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def pano_to_world(d: Sequence[float], rotation: Sequence[float] | None) -> np.ndarray:
    v = np.asarray(d, dtype=float)
    return v if rotation is None else _quat_matrix(rotation) @ v


def world_to_pano(d: Sequence[float], rotation: Sequence[float] | None) -> np.ndarray:
    v = np.asarray(d, dtype=float)
    return v if rotation is None else _quat_matrix(rotation).T @ v


def heading_pitch_ray(
    heading_deg: float, pitch_deg: float, origin: Sequence[float], rotation: Sequence[float] | None = None
) -> Ray:
    d = pano_to_world(heading_pitch_to_direction(heading_deg, pitch_deg), rotation)
    d = d / np.linalg.norm(d)
    return Ray(origin=tuple(float(c) for c in origin), direction=tuple(float(c) for c in d))


def pixel_ray(
    px: float,
    py: float,
    spec: TileSpec,
    origin: Sequence[float],
    rotation: Sequence[float] | None = None,
    size_hw: tuple[int, int] | None = None,
) -> Ray:
    """World-space viewing ray through a tile pixel, starting at the sweep position."""
    return heading_pitch_ray(*tile_pixel_to_heading_pitch(px, py, spec, size_hw), origin, rotation)


def bbox_ray(
    bbox: BBox,
    spec: TileSpec,
    origin: Sequence[float],
    rotation: Sequence[float] | None = None,
    size_hw: tuple[int, int] | None = None,
) -> Ray:
    return heading_pitch_ray(*bbox_heading_pitch(bbox, spec, size_hw), origin, rotation)


def world_heading_pitch(
    target: Sequence[float], origin: Sequence[float], rotation: Sequence[float] | None = None
) -> tuple[float, float]:
    """Panorama heading and pitch at ``origin`` that look at the world point ``target``."""
    d = np.asarray(target, dtype=float) - np.asarray(origin, dtype=float)
    return direction_to_heading_pitch(world_to_pano(d, rotation))


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def crop(image: np.ndarray, bbox: BBox, pad_frac: float = 0.15) -> np.ndarray:
    """Crop a normalized bbox from a tile with padding for context (only the equipment region)."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = bbox
    pw, ph = (x1 - x0) * pad_frac, (y1 - y0) * pad_frac
    # Round before floor/ceil so float noise (0.15000000000000002 * 100) does not add a pixel.
    c0 = max(0, math.floor(round((x0 - pw) * w, 6)))
    r0 = max(0, math.floor(round((y0 - ph) * h, 6)))
    c1 = min(w, math.ceil(round((x1 + pw) * w, 6)))
    r1 = min(h, math.ceil(round((y1 + ph) * h, 6)))
    if c1 <= c0 or r1 <= r0:
        raise ValueError(f"empty crop for bbox {list(bbox)}")
    return image[r0:r1, c0:c1]


def valid_bbox(bbox: BBox) -> bool:
    if len(bbox) != 4:
        return False
    x0, y0, x1, y1 = bbox
    return 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0


def bbox_area_frac(bbox: BBox) -> float:
    x0, y0, x1, y1 = bbox
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def downscale(image: np.ndarray, max_px: int) -> np.ndarray:
    """Shrink so the longer side is at most ``max_px`` (no-op when already small)."""
    h, w = image.shape[:2]
    if max(h, w) <= max_px:
        return image
    from PIL import Image

    s = max_px / max(h, w)
    img = Image.fromarray(image)
    return np.asarray(img.resize((max(1, round(w * s)), max(1, round(h * s))), Image.Resampling.LANCZOS))


def to_jpeg(image: np.ndarray, quality: int = 85) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(image)).convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def load_image(path: str) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"))
