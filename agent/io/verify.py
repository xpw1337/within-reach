"""The one LLM call on the live path: a scene check on the person-down snapshot.

Runs in the background after the voice check has already started. Its answer is advice: the
reducer filters it through the modifier allowlist and lets it only add modifiers, add hazards or
mark the scene unsafe (spec section 3). A hard timeout means a slow or unreachable model never
holds anything up.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from agent.live.state import MODIFIER_ALLOWLIST

SYSTEM = (
    "You check a single security-camera frame in which a person has been detected down on the "
    "floor. Answer only about what is visible. Do not identify the person. Report: is_emergency "
    "(a person appears to be down and may need help), scene_safe (false only if you see a clear "
    "danger to people who would approach, such as fire, smoke, a weapon, traffic or live "
    "electricity), hazards (short names of dangers you see, empty if none), and modifiers chosen "
    "only from this list when clearly visible: breathing (the person is visibly breathing), "
    "seizure (rhythmic shaking), overdose (drug paraphernalia next to the person), notify_police "
    "(violence or a weapon)."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_emergency": {"type": "boolean"},
        "scene_safe": {"type": "boolean"},
        "hazards": {"type": "array", "items": {"type": "string"}},
        "modifiers": {"type": "array", "items": {"type": "string", "enum": list(MODIFIER_ALLOWLIST)}},
    },
    "required": ["is_emergency", "scene_safe", "hazards", "modifiers"],
    "additionalProperties": False,
}


class VerifyError(RuntimeError):
    pass


CompleteJson = Callable[..., dict[str, Any]]


def _default_complete_json() -> CompleteJson:
    from shared.llm import complete_json

    return complete_json


def build_user_parts(frame_jpeg: bytes, landmark: str | None) -> list[dict[str, Any]]:
    from shared.llm import image_part, text_part

    where = f" The camera is by {landmark}." if landmark else ""
    return [image_part(frame_jpeg, "image/jpeg"), text_part("Check this frame." + where)]


class SceneVerifier:
    def __init__(self, timeout_s: float, complete_json: CompleteJson | None = None) -> None:
        self.timeout_s = float(timeout_s)
        self._complete_json = complete_json

    async def verify(self, frame_jpeg: bytes | None, landmark: str | None = None) -> dict[str, Any]:
        if not frame_jpeg:
            raise VerifyError("no frame")
        fn = self._complete_json or _default_complete_json()
        try:
            user = build_user_parts(frame_jpeg, landmark)
            return await asyncio.wait_for(
                asyncio.to_thread(fn, tier="reasoning", system=SYSTEM, user=user, schema=SCHEMA, max_tokens=1024),
                timeout=self.timeout_s,
            )
        except TimeoutError as exc:
            raise VerifyError(f"timed out after {self.timeout_s:g} s") from exc
        except VerifyError:
            raise
        except Exception as exc:
            raise VerifyError(f"{type(exc).__name__}: {exc}") from exc


class FakeVerifier:
    """Returns a canned result (or raises) after an optional delay on the given sleep function."""

    def __init__(self, result: Any = None, error: str | None = None, delay_s: float = 0.0, sleep=None) -> None:
        self.result = result if result is not None or error else {
            "is_emergency": True, "scene_safe": True, "hazards": [], "modifiers": []}
        self.error = error
        self.delay_s = delay_s
        self.sleep = sleep or asyncio.sleep
        self.calls = 0

    async def verify(self, frame_jpeg: bytes | None, landmark: str | None = None) -> Any:
        self.calls += 1
        if self.delay_s:
            await self.sleep(self.delay_s)
        if self.error:
            raise VerifyError(self.error)
        return self.result
