"""Prompts and strict JSON schemas for census perception (spec section 9.3).

Privacy (spec sections 9.3 and 16): prompts ask for equipment only. Nothing here asks the model to
describe, locate or identify people. The verify step reports when a person fills the crop so the
crop is discarded instead of stored.
"""

from __future__ import annotations

DETECT_TYPES: tuple[str, ...] = (
    "aed",
    "extinguisher",
    "exit_sign",
    "sprinkler",
    "smoke_detector",
    "first_aid",
    "naloxone",
)

TYPE_NAMES = {
    "aed": "AED (automated external defibrillator), its wall cabinet or its sign",
    "extinguisher": "portable fire extinguisher, or its wall cabinet",
    "exit_sign": "illuminated EXIT sign",
    "sprinkler": "fire sprinkler head",
    "smoke_detector": "smoke or heat detector",
    "first_aid": "first aid kit or first aid station",
    "naloxone": "naloxone (Narcan) kit or box",
}

FIRST_PASS_SYSTEM = (
    "You inspect one perspective image cut from a 360 degree panorama of a building interior. "
    "Find life-safety equipment of these types only:\n"
    + "\n".join(f"- {t}: {d}" for t, d in TYPE_NAMES.items())
    + "\n\nFor each item return its type, a tight bounding box as fractions of the image width and "
    "height [x_min, y_min, x_max, y_max] with 0,0 at the top-left corner, and your confidence from 0 "
    "to 1. Report each physical item once. Equipment only: ignore people entirely and never describe "
    "them. If no listed equipment is visible, return an empty list. Do not guess from context: an item "
    "must be visible in the image."
)

FIRST_PASS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": list(DETECT_TYPES)},
                    "bbox": {"type": "array", "items": {"type": "number"}},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["type", "bbox", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

VERIFY_SYSTEM = (
    "You check one cropped image from a building interior scan. A first-pass detector claims it shows "
    "a specific piece of life-safety equipment. Decide whether the crop really shows that equipment. "
    "Be strict: a red box, a sign for something else, or an ambiguous shape is not a match. "
    "Give a short reason (one sentence, equipment only). "
    "Set blocked_exit to true only when the claimed item is an exit sign or exit door and the exit "
    "looks obstructed (furniture, boxes, locked gate or chain in front of it); otherwise false. "
    "Set person_in_crop to true if a person takes up a large part of the crop; never describe the person."
)

VERIFY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
        "reason": {"type": "string"},
        "blocked_exit": {"type": "boolean"},
        "person_in_crop": {"type": "boolean"},
    },
    "required": ["confirmed", "reason", "blocked_exit", "person_in_crop"],
    "additionalProperties": False,
}


def verify_user_text(claimed_type: str) -> str:
    return f"Claimed equipment: {claimed_type} ({TYPE_NAMES.get(claimed_type, claimed_type)}). Is it really there?"
