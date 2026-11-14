"""Timing and wave settings for the live graph.

Values come from the environment through ``shared.config`` (spec section 14). A copy travels inside
each incident's state so the pure reducer never reads settings itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class LiveConfig:
    # spec section 14 (.env.example)
    down_seconds: float = 5
    voice_check_seconds: float = 5
    confirm_auto_proceed_seconds: float = 10
    found_down_escalate_seconds: float = 60
    fall_911_cancel_seconds: float = 60
    wave_size: int = 4
    accept_timeout_seconds: float = 20
    # spec section 9.10: "3 waves max"
    max_waves: int = 3
    # spec section 3: the CARDIAC script repeats every 20 s. The CPR coaching loop reuses the same
    # interval because the spec gives no separate one.
    announce_repeat_seconds: float = 20
    guide_repeat_seconds: float = 20
    # spec section 9.10: responders must have been seen in the last 10 minutes
    responder_seen_seconds: float = 600
    # Engineering choice, not a guideline: the scene check is advisory and must never hold anything
    # up, so the one LLM call on the live path is abandoned after this many seconds.
    verify_timeout_seconds: float = 8

    def as_state(self) -> dict[str, Any]:
        return asdict(self)


_ENV_FIELDS = (
    "down_seconds",
    "voice_check_seconds",
    "confirm_auto_proceed_seconds",
    "found_down_escalate_seconds",
    "fall_911_cancel_seconds",
    "wave_size",
    "accept_timeout_seconds",
)


def from_settings(settings: Any) -> LiveConfig:
    """Build a LiveConfig from a ``shared.config.Settings`` object.

    Only the fields that exist in the environment contract are read; the rest keep the defaults
    above, which are spec values.
    """
    values: dict[str, Any] = {}
    for name in _ENV_FIELDS:
        value = getattr(settings, name, None)
        if value is not None:
            values[name] = value
    return LiveConfig(**values)
