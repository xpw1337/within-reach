"""Verify one equipment crop on the reasoning tier (spec section 9.3 step 3). No database."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from census.core.tiling import to_jpeg
from census.vision.prompts import VERIFY_SCHEMA, VERIFY_SYSTEM, verify_user_text
from shared import llm

EXIT_TYPES = ("exit_sign", "exit")


@dataclass
class Verdict:
    confirmed: bool
    reason: str
    blocked_exit: bool
    person_in_crop: bool


def verify_crop(
    crop_image: np.ndarray,
    claimed_type: str,
    *,
    run_id: str | None = None,
    complete_json: Callable[..., dict] | None = None,
) -> Verdict:
    call = complete_json or llm.complete_json
    out = call(
        tier="reasoning",
        system=VERIFY_SYSTEM,
        user=[llm.image_part(to_jpeg(crop_image)), llm.text_part(verify_user_text(claimed_type))],
        schema=VERIFY_SCHEMA,
        run_id=run_id,
        max_tokens=1024,
    )
    return Verdict(
        confirmed=bool(out["confirmed"]),
        reason=str(out.get("reason", "")).strip()[:300],
        blocked_exit=bool(out.get("blocked_exit")) and claimed_type in EXIT_TYPES,
        person_in_crop=bool(out.get("person_in_crop")),
    )
