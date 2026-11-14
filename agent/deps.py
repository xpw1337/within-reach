"""Default dependencies built from ``shared.config`` settings, and FastAPI accessors.

Choices made from the environment:
- store: Supabase when ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` are set, else in-memory dev fixture
- telephony: Twilio when its credentials and ``PUBLIC_BASE_URL`` are set, else FakeTelephony (no calls)
- TTS: Polly when ``TTS_PROVIDER=polly`` and AWS credentials exist; macOS ``say`` otherwise on a Mac
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Any

from fastapi import Request

log = logging.getLogger(__name__)


def settings() -> Any:
    from shared.config import get_settings

    return get_settings()


def cache_dir() -> Path:
    return Path(settings().cache_dir)


def audio_dir() -> Path:
    return cache_dir() / "audio"


def supabase_configured() -> bool:
    s = settings()
    return bool(s.supabase_url and s.supabase_service_role_key)


def default_store() -> Any:
    from agent.live.store import MemoryStore, SupabaseStore

    if supabase_configured():
        return SupabaseStore()
    from agent.live.devseed import dev_rows

    return MemoryStore(**dev_rows(time.time()))


def default_upload() -> Any:
    if not supabase_configured():
        return None
    from shared.db import upload

    return upload


def default_tts() -> Any:
    from agent.io.tts import FakeTTS, MacSayTTS, PollyTTS

    s = settings()
    if s.tts_provider == "polly" and (s.aws_access_key_id or s.aws_session_token):
        return PollyTTS(voice=s.polly_voice, region=s.aws_region)
    if sys.platform == "darwin":
        log.warning("Polly not configured; rendering speaker audio with macOS say")
        return MacSayTTS()
    log.warning("no TTS available; speaker audio files will be placeholders")
    return FakeTTS()


def default_telephony() -> Any:
    from agent.io.telephony import FakeTelephony, TwilioTelephony

    s = settings()
    if s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number and s.public_base_url:
        return TwilioTelephony(account_sid=s.twilio_account_sid, auth_token=s.twilio_auth_token,
                               from_number=s.twilio_from_number, public_base_url=s.public_base_url,
                               dispatch_sim_number=s.dispatch_sim_number,
                               ring_timeout_s=int(s.accept_timeout_seconds))
    log.warning("Twilio not configured: calls are recorded by FakeTelephony, nothing rings")
    return FakeTelephony(dispatch_sim_number=s.dispatch_sim_number or "+15550001111")


def get_runtime(request: Request) -> Any:
    return request.app.state.runtime
