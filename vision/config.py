"""Configuration for vision/, read from the environment.

vision/ imports no other repo package (docs/ARCHITECTURE.md section 3), so it reads its own env
here instead of using shared/config.py. A ``.env`` at the repo root is loaded if python-dotenv is
installed; real environment variables always win.

Two kinds of numbers live in ``DetectorConfig``:

* Spec constants (CLAUDE.md section 3 and 9.9): DOWN_SECONDS, RESPONSIVE_HOLD_SECONDS, the 1.3 box
  aspect ratio, the 40% hip drop within 2 s, and the 1 to 5 Hz seizure band.
* UNTUNED constants: placeholders that the spec does not give a number for. They are marked
  UNTUNED below and stay that way until the six tuning clips in demo/clips/ exist and pass
  (subtask 5.4). Do not quote them anywhere as measured values.

Every field can be overridden with an env var (see ``env_name``) or ``--set name=value`` on the
main.py and replay.py command lines.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Fields whose env var is the spec's own name (.env.example). Everything else is VISION_<FIELD>.
_SPEC_ENV_NAMES = {
    "down_seconds": "DOWN_SECONDS",
    "witnessed_down_seconds": "WITNESSED_DOWN_SECONDS",
    "responsive_hold_seconds": "RESPONSIVE_HOLD_SECONDS",
}


@dataclass(frozen=True)
class DetectorConfig:
    # ---- Spec constants -------------------------------------------------------------------
    # Down pose held this long before person_down when the fall was NOT seen (slow lie-down or
    # already on the floor): longer, to avoid alerting on someone stretching on the floor.
    down_seconds: float = 3.0
    # A witnessed fall (hips dropped fast from standing) alerts after this short hold instead.
    witnessed_down_seconds: float = 0.8
    # Victim wrist above shoulder this long before responsive (spec section 3).
    responsive_hold_seconds: float = 1.5
    # "bbox w/h > 1.3" (spec 9.9).
    down_aspect_ratio: float = 1.3
    # "hip-y drop > 40% of body height within 2 s" (spec 9.9).
    witnessed_drop_fraction: float = 0.40
    witnessed_window_seconds: float = 2.0
    # "1 to 5 Hz limb oscillation" (spec 9.9).
    seizure_min_hz: float = 1.0
    seizure_max_hz: float = 5.0

    # ---- UNTUNED: placeholders until the demo/clips tuning set exists (5.4) -------------------
    # Keypoints below this confidence are treated as not visible. UNTUNED.
    keypoint_min_conf: float = 0.3
    # "Torso near horizontal" (spec gives no number): degrees from vertical. UNTUNED.
    torso_down_deg: float = 60.0
    # Torso this close to vertical means upright (standing, sitting, kneeling): never down. UNTUNED.
    torso_upright_deg: float = 35.0
    # Thighs this close to vertical (plus an upright torso) means standing, not sitting. UNTUNED.
    thigh_standing_deg: float = 30.0
    # Head-to-feet body line this far from vertical counts as lying (sitting on the floor with legs
    # out is about 60, lying about 90). UNTUNED.
    axis_down_deg: float = 72.0
    # The head has dropped this far below its standing height (fraction of standing height): lying,
    # not sitting on the floor (about 0.45) or bending over. UNTUNED.
    head_down_min_drop: float = 0.6
    # A box this narrow with the head at its top is a standing person (used when the hips are not
    # found, so the torso angle is unknown). UNTUNED.
    standing_max_aspect: float = 0.65
    # Hips must have dropped this far (fraction of standing height) for a down pose, when the
    # track was seen standing. Rejects bending over and leaning forward on a chair. UNTUNED.
    hip_down_min_drop: float = 0.35
    # Down-pose gaps shorter than this (keypoint flicker) do not reset DOWN_PENDING. UNTUNED.
    down_grace_seconds: float = 0.5
    # A wrist counts as above the shoulder only when higher by this many body lengths. UNTUNED.
    wrist_raise_margin: float = 0.15
    # Trailing window for the limb frequency estimate. UNTUNED.
    oscillation_window_seconds: float = 3.0
    # Minimum oscillation amplitude, in body lengths, to rule out keypoint jitter. UNTUNED.
    oscillation_min_amplitude: float = 0.03
    # Minimum share of power in the peak for the motion to count as rhythmic. UNTUNED.
    oscillation_min_peak_ratio: float = 0.4
    # Minimum samples in the window for a frequency estimate. UNTUNED.
    oscillation_min_samples: int = 12
    # A second track this close to the victim (box gap, in victim body lengths) is "near". UNTUNED.
    responder_near_fraction: float = 0.25
    # ...and must stay near this long before responder_arrived. UNTUNED.
    responder_hold_seconds: float = 2.0
    # The victim standing this long clears the incident on the vision side. UNTUNED.
    standup_clear_seconds: float = 3.0
    # The victim unseen this long clears the incident on the vision side. UNTUNED.
    victim_lost_clear_seconds: float = 60.0
    # ID-switch re-association: a new track takes over a lost one if their boxes overlap this much
    # (IoU) or their centers are within this many body lengths, and the loss was recent. UNTUNED.
    reassociate_min_iou: float = 0.3
    reassociate_max_center_fraction: float = 1.5
    reassociate_max_gap_seconds: float = 2.5
    # A down-pose track overlapping the victim this much is a duplicate, not a helper. UNTUNED.
    duplicate_min_iou: float = 0.6
    # Standing samples (seconds) averaged into the standing height reference. UNTUNED.
    standing_ref_seconds: float = 1.0
    # Forget tracks unseen this long (the victim's track is kept). UNTUNED.
    track_forget_seconds: float = 10.0

    @staticmethod
    def env_name(field_name: str) -> str:
        return _SPEC_ENV_NAMES.get(field_name, "VISION_" + field_name.upper())

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> DetectorConfig:
        env = os.environ if env is None else env
        values = {}
        for f in fields(cls):
            raw = env.get(cls.env_name(f.name))
            if raw is not None and raw.strip() != "":
                values[f.name] = _coerce(f.name, f.type, raw)
        return cls(**values)

    def with_overrides(self, pairs: list[str] | None) -> DetectorConfig:
        """Apply ``name=value`` overrides (CLI ``--set``)."""
        if not pairs:
            return self
        types = {f.name: f.type for f in fields(self)}
        values = {}
        for pair in pairs:
            name, sep, raw = pair.partition("=")
            name = name.strip()
            if not sep or name not in types:
                raise ValueError(f"unknown detector setting {pair!r}; expected one of {sorted(types)}")
            values[name] = _coerce(name, types[name], raw)
        return replace(self, **values)


def _coerce(name: str, type_name: object, raw: str) -> float | int:
    try:
        if type_name in (int, "int"):
            return int(raw)
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: expected a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Runtime settings for main.py and the event client."""

    camera_index: int = 0
    camera_id: str = "webcam-1"
    agent_url: str = "http://localhost:8000"
    # Pose model; downloaded by Ultralytics on first use into this git-ignored path.
    model_path: str = str(REPO_ROOT / ".cache" / "models" / "yolo11s-pose.pt")
    # Ultralytics tracker config (bytetrack.yaml ships with the package and is the lightest).
    tracker: str = "bytetrack.yaml"
    imgsz: int = 640
    # Snapshot sent with person_down: longest side in pixels and JPEG quality. UNTUNED.
    snapshot_max_side: int = 640
    snapshot_jpeg_quality: int = 70
    # POST /events retry policy: attempts and first backoff in seconds (doubles each time). UNTUNED.
    http_timeout_seconds: float = 2.0
    http_max_attempts: int = 4
    http_backoff_seconds: float = 0.25
    # Fire / smoke detection (vision/fire.py). Empty model path turns it off.
    fire_model_path: str = str(REPO_ROOT / ".cache" / "models" / "fire-world.pt")
    fire_conf: float = 0.25
    # Run the fire model on every Nth frame (it shares the GPU with the pose model).
    fire_every: int = 3
    # Annotated feed for the dashboard (vision/stream.py). Port 0 turns it off.
    stream_host: str = "127.0.0.1"
    stream_port: int = 8001


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(REPO_ROOT / ".env", override=False)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    d = Settings()

    def get(name: str, default: str) -> str:
        raw = env.get(name)
        return default if raw is None or raw.strip() == "" else raw.strip()

    return Settings(
        camera_index=int(get("CAMERA_INDEX", str(d.camera_index))),
        camera_id=get("CAMERA_ID", d.camera_id),
        agent_url=get("AGENT_URL", d.agent_url).rstrip("/"),
        model_path=get("VISION_MODEL", d.model_path),
        tracker=get("VISION_TRACKER", d.tracker),
        imgsz=int(get("VISION_IMGSZ", str(d.imgsz))),
        snapshot_max_side=int(get("VISION_SNAPSHOT_MAX_SIDE", str(d.snapshot_max_side))),
        snapshot_jpeg_quality=int(get("VISION_SNAPSHOT_JPEG_QUALITY", str(d.snapshot_jpeg_quality))),
        http_timeout_seconds=float(get("VISION_HTTP_TIMEOUT_SECONDS", str(d.http_timeout_seconds))),
        http_max_attempts=int(get("VISION_HTTP_MAX_ATTEMPTS", str(d.http_max_attempts))),
        http_backoff_seconds=float(get("VISION_HTTP_BACKOFF_SECONDS", str(d.http_backoff_seconds))),
        fire_model_path=get("VISION_FIRE_MODEL", d.fire_model_path),
        fire_conf=float(get("VISION_FIRE_CONF", str(d.fire_conf))),
        fire_every=max(1, int(get("VISION_FIRE_EVERY", str(d.fire_every)))),
        stream_host=get("VISION_STREAM_HOST", d.stream_host),
        stream_port=int(get("VISION_STREAM_PORT", str(d.stream_port))),
    )
