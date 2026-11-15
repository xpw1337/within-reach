"""Pre-render every speaker script for a camera (docs/CONTRACTS.md section 6).

``render_camera_audio(camera_id)`` reads the camera and its routes, renders each script whose
wording exists and whose placeholders are mapped, writes ``.cache/audio/{camera_id}/{script_id}.mp3``,
mirrors it to the ``audio`` bucket when a database is configured, and fills
``camera_routes.audio_url`` (``aed`` -> ``cardiac_main``, ``naloxone`` -> ``mod_overdose``).

Providers:
- ``PollyTTS``: Amazon Polly, ``POLLY_VOICE``, mp3. Not verified: no AWS credentials yet.
- ``MacSayTTS``: macOS ``say`` for local runs without AWS (writes .aiff, which LocalSpeaker plays).
- ``FakeTTS``: tests.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from agent.live.playbooks import renderable_scripts
from agent.live.store import enrich_routes

log = logging.getLogger(__name__)

ROUTE_SCRIPT = {"aed": "cardiac_main", "naloxone": "mod_overdose"}
CONTENT_TYPES = {"mp3": "audio/mpeg", "aiff": "audio/aiff", "wav": "audio/wav"}


class TTS(Protocol):
    ext: str

    def synthesize(self, text: str) -> bytes: ...


class PollyTTS:
    ext = "mp3"

    def __init__(self, voice: str, region: str, engine: str = "neural") -> None:
        import boto3

        self.client = boto3.client("polly", region_name=region)
        self.voice = voice
        self.engine = engine

    def synthesize(self, text: str) -> bytes:
        try:
            resp = self.client.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=self.voice,
                                                 Engine=self.engine)
        except Exception as exc:
            if self.engine == "standard":
                raise
            log.warning("Polly %s engine failed (%s); using standard", self.engine, exc)
            self.engine = "standard"
            resp = self.client.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=self.voice,
                                                 Engine="standard")
        return resp["AudioStream"].read()


class MacSayTTS:
    """macOS ``say``. It writes AIFF, which the ``audio`` bucket refuses (MP3 only, migration 0003),
    so the file is converted to MP3 with ffmpeg when it is installed; without ffmpeg it stays AIFF
    (the laptop speaker plays it, only the upload is skipped)."""

    def __init__(self) -> None:
        self.ffmpeg = shutil.which("ffmpeg")
        self.ext = "mp3" if self.ffmpeg else "aiff"

    def synthesize(self, text: str) -> bytes:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.aiff"
            subprocess.run(["say", "-o", str(out), text], check=True, capture_output=True)
            if not self.ffmpeg:
                return out.read_bytes()
            mp3 = Path(d) / "out.mp3"
            subprocess.run(
                [self.ffmpeg, "-loglevel", "error", "-y", "-i", str(out), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3)],
                check=True,
                capture_output=True,
            )
            return mp3.read_bytes()


class FakeTTS:
    ext = "mp3"

    def __init__(self) -> None:
        self.texts: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.texts.append(text)
        return b"FAKE-AUDIO " + text.encode()


async def render_camera_audio(
    camera_id: str,
    *,
    store: Any = None,
    tts: TTS | None = None,
    audio_dir: Path | None = None,
    upload: Any = None,
) -> dict[str, str]:
    """Render every available script for ``camera_id``. Returns ``{script_id: local path}``.

    With no arguments it uses the app defaults (``agent.deps``)."""
    if store is None or tts is None or audio_dir is None:
        from agent import deps

        store = store or deps.default_store()
        tts = tts or deps.default_tts()
        audio_dir = audio_dir or deps.audio_dir()
        if upload is None:
            upload = deps.default_upload()
    camera = await store.get_camera(camera_id)
    if not camera:
        raise LookupError(f"unknown camera {camera_id!r}")
    routes = await store.get_camera_routes(camera_id)
    await enrich_routes(store, camera, routes)
    texts = renderable_scripts(camera, routes)
    out_dir = Path(audio_dir) / camera_id
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}
    urls: dict[str, str] = {}
    for script_id, text in texts.items():
        data = await asyncio.to_thread(tts.synthesize, text)
        for old in out_dir.glob(f"{script_id}.*"):
            old.unlink()
        path = out_dir / f"{script_id}.{tts.ext}"
        path.write_bytes(data)
        paths[script_id] = str(path)
        if upload is not None:
            try:
                urls[script_id] = await asyncio.to_thread(
                    upload, "audio", f"{camera_id}/{script_id}.{tts.ext}", data,
                    CONTENT_TYPES.get(tts.ext, "application/octet-stream"))
            except Exception as exc:  # noqa: BLE001 - local playback does not need the mirror
                log.warning("audio upload failed for %s: %s", script_id, exc)
    for target, script_id in ROUTE_SCRIPT.items():
        if target in routes and script_id in urls:
            await store.set_route_audio_url(camera_id, target, urls[script_id])
    skipped = sorted(set(texts) ^ set(paths))
    if skipped:
        log.warning("not rendered for %s: %s", camera_id, skipped)
    return paths
