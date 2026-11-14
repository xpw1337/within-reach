"""First-pass equipment detection on one tile (spec section 9.3 step 2).

Images in, typed results out. No database. Runs on the fast tier with a strict JSON schema on a
downscaled tile. An open-vocabulary detector can replace this behind the same signature.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from census.core.tiling import downscale, to_jpeg
from census.vision.prompts import DETECT_TYPES, FIRST_PASS_SCHEMA, FIRST_PASS_SYSTEM
from shared import llm
from shared.config import get_settings


@dataclass
class Candidate:
    type: str
    bbox: list[float]  # normalized [x_min, y_min, x_max, y_max]
    confidence: float


def _clean_bbox(b: list[float]) -> list[float] | None:
    if len(b) != 4:
        return None
    x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in b)
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def detect_first_pass(
    tile_image: np.ndarray,
    *,
    run_id: str | None = None,
    max_px: int | None = None,
    complete_json: Callable[..., dict] | None = None,
) -> list[Candidate]:
    """Equipment candidates in one tile. Invalid boxes and unknown types are dropped."""
    max_px = max_px or get_settings().first_pass_max_px
    image = downscale(tile_image, max_px)
    call = complete_json or llm.complete_json
    out = call(
        tier="fast",
        system=FIRST_PASS_SYSTEM,
        user=[llm.image_part(to_jpeg(image)), llm.text_part("List the equipment in this image.")],
        schema=FIRST_PASS_SCHEMA,
        run_id=run_id,
        max_tokens=1024,
    )
    found: list[Candidate] = []
    for item in out.get("items", []):
        t = item.get("type")
        bbox = _clean_bbox(item.get("bbox") or [])
        if t not in DETECT_TYPES or bbox is None:
            continue
        conf = min(1.0, max(0.0, float(item.get("confidence", 0.0))))
        found.append(Candidate(t, bbox, conf))
    return found
