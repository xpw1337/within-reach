"""Typed settings for every Python package in the repo.

Every environment variable in ``.env.example`` is a field here, with the spec defaults (spec
section 14). ``get_settings()`` is the only way code reads configuration: no other module reads
``os.environ`` (vision/ is the exception by design and keeps its own config).

Values come from, in order of precedence: real environment variables, then the repo-root ``.env``
file, then the defaults below. Empty values (``ANTHROPIC_API_KEY=``) count as unset.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM ---
    anthropic_api_key: str | None = None
    claude_model_reasoning: str = "claude-sonnet-5-5"
    claude_model_fast: str = "claude-haiku-5-5"
    use_bedrock: bool = True
    aws_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    # Optional AWS auth alternatives (not in the spec list; documented in .env.example).
    aws_session_token: str | None = None
    aws_bearer_token_bedrock: str | None = None
    # Effort per tier for complete_json. A cost/latency choice, not a guideline.
    llm_effort_fast: str = "low"
    llm_effort_reasoning: str = "medium"

    # --- Voice ---
    tts_provider: str = "polly"
    polly_voice: str = "Joanna"

    # --- Supabase ---
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None

    # --- Dashboard (Next.js); read by the dashboard, listed here so nothing is silently unknown ---
    next_public_supabase_url: str | None = None
    next_public_supabase_anon_key: str | None = None
    next_public_agent_url: str = "http://localhost:8000"
    next_public_matterport_sdk_key: str | None = None

    # --- Mobile (Expo) ---
    expo_public_supabase_url: str | None = None
    expo_public_supabase_anon_key: str | None = None
    expo_public_dashboard_url: str | None = None
    expo_public_agent_url: str | None = None

    # --- Twilio ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    dispatch_sim_number: str | None = None  # a teammate's phone, never a real emergency number
    public_base_url: str | None = None

    # --- Datasets ---
    matterport_sdk_key: str | None = None
    costar_data_path: str | None = None  # unset means the fallback building is used
    vexcel_api_key: str | None = None

    # --- Tracing ---
    langsmith_api_key: str | None = None
    langsmith_tracing: bool = True

    # --- Census ---
    census_budget_usd: float = 150.0  # set with the team before the overnight run
    detect_min_conf: float = 0.35
    # Upper edge of the borderline band that triggers a second-view check (census/DESIGN.md).
    detect_borderline_high: float = 0.6
    walk_speed_mps: float = 1.4
    # Red-zone thresholds: unverified defaults (spec sections 9.4 and 20). Sources in thresholds.py.
    aed_roundtrip_target_s: float = 180.0
    ext_max_travel_m: float = 22.9
    exit_max_travel_m: float = 61.0
    demo_event_delay_ms: int = 0
    # Scanner tiling and bulk work
    tiles_per_pano: int = 8
    tile_fov_deg: float = 90.0
    tile_size_px: int = 1024
    first_pass_max_px: int = 768  # first pass runs on downscaled tiles (spec section 9.3)
    scan_concurrency: int = 4
    cache_dir: Path = REPO_ROOT / ".cache"

    # --- Live ---
    camera_index: int = 0
    camera_id: str = "cam-lobby-1"
    agent_url: str = "http://localhost:8000"
    down_seconds: float = 5.0
    voice_check_seconds: float = 5.0
    responsive_hold_seconds: float = 1.5
    confirm_auto_proceed_seconds: float = 10.0
    found_down_escalate_seconds: float = 60.0
    fall_911_cancel_seconds: float = 60.0
    wave_size: int = 4
    accept_timeout_seconds: float = 20.0

    def require(self, *names: str) -> None:
        """Raise ``MissingSettingError`` naming every listed variable that is unset."""
        missing = [n.upper() for n in names if getattr(self, n.lower()) in (None, "")]
        if missing:
            raise MissingSettingError(missing)


class MissingSettingError(RuntimeError):
    """A required environment variable is not set. The message names it."""

    def __init__(self, names: list[str], hint: str | None = None) -> None:
        self.names = names
        msg = f"Missing environment variable{'s' if len(names) > 1 else ''}: {', '.join(names)}"
        if hint:
            msg += f". {hint}"
        else:
            msg += ". Set it in .env (see .env.example)."
        super().__init__(msg)


def _export_tracing_env(settings: Settings) -> None:
    """LangSmith reads its switches from the process environment; pass ours through.

    This writes (never reads) os.environ, and only fills variables that are not already set.
    """
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGSMITH_TRACING", "true" if settings.langsmith_tracing else "false")
    else:
        # No key: tracing would only log auth errors.
        os.environ.setdefault("LANGSMITH_TRACING", "false")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    _export_tracing_env(settings)
    return settings
