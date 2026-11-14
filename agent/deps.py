"""Default dependencies built from ``shared.config`` settings, and FastAPI accessors.

Choices made from the environment:
- store: Supabase when ``SUPABASE_URL`` and ``SUPABASE_SERVICE_ROLE_KEY`` are set, else in-memory dev fixture
- telephony: Twilio when its credentials and ``PUBLIC_BASE_URL`` are set, else FakeTelephony (no calls);
  through the Photon number over SIP when every ``PHOTON_SIP_*`` setting and ``PHOTON_NUMBER`` are set
- messaging: Photon iMessage when ``PHOTON_API_KEY`` and ``PHOTON_PROJECT_ID`` are set, else none
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

    if settings().supabase_url:  # the dev fixture is used only when SUPABASE_URL is unset
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


def photon_sip() -> Any:
    """``PhotonSip`` when all four PHOTON_SIP_* / PHOTON_NUMBER settings are set, else None."""
    from agent.io.telephony import PhotonSip

    s = settings()
    values = (s.photon_sip_server, s.photon_sip_username, s.photon_sip_password, s.photon_number)
    if all(values):
        return PhotonSip(server=s.photon_sip_server, username=s.photon_sip_username,
                         password=s.photon_sip_password, number=s.photon_number)
    if any(values):
        log.warning("Photon SIP needs PHOTON_SIP_SERVER, PHOTON_SIP_USERNAME, PHOTON_SIP_PASSWORD and "
                    "PHOTON_NUMBER; calls use the Twilio number")
    return None


def default_telephony() -> Any:
    from agent.io.telephony import FakeTelephony, TwilioTelephony

    s = settings()
    sip = photon_sip()
    if s.twilio_account_sid and s.twilio_auth_token and s.public_base_url and (sip or s.twilio_from_number):
        log.info("calls go out through %s", "the Photon number over SIP" if sip else "the Twilio number")
        return TwilioTelephony(account_sid=s.twilio_account_sid, auth_token=s.twilio_auth_token,
                               from_number=s.twilio_from_number, public_base_url=s.public_base_url,
                               dispatch_sim_number=s.dispatch_sim_number,
                               ring_timeout_s=int(s.accept_timeout_seconds), sip=sip)
    log.warning("Twilio not configured: calls are recorded by FakeTelephony, nothing rings")
    return FakeTelephony(dispatch_sim_number=s.dispatch_sim_number or "+15550001111")


def default_messenger() -> Any:
    """``PhotonMessenger`` when PHOTON_API_KEY and PHOTON_PROJECT_ID are set, else None (no texts)."""
    s = settings()
    if not (s.photon_api_key and s.photon_project_id):
        log.info("Photon not configured: no iMessage alerts")
        return None
    from agent.io.messaging import PhotonMessenger

    return PhotonMessenger(api_key=s.photon_api_key, project_id=s.photon_project_id,
                           dispatch_sim_number=s.dispatch_sim_number)


def get_runtime(request: Request) -> Any:
    return request.app.state.runtime
