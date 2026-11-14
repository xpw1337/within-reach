"""Speaker output: pre-rendered audio files per camera (docs/ARCHITECTURE.md decision D8).

``LocalSpeaker`` plays ``.cache/audio/{camera_id}/{script_id}.mp3`` through the laptop output with
the platform's own player, so no Python audio dependency is needed:

- macOS: ``afplay`` (ships with the OS; verified)
- Windows: PowerShell with ``System.Windows.Media.MediaPlayer`` (ships with Windows; not verified here)
- Linux: the first of ``ffplay``, ``mpg123``, ``paplay`` found on PATH (not verified here)

A new ``play`` interrupts the current one. ``play`` returns as soon as the first player process has
started, so the hot path never waits for audio to finish.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import sys
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

AUDIO_EXTS = ("mp3", "wav", "aiff", "m4a")

_WINDOWS_PLAYER = (
    "Add-Type -AssemblyName presentationCore; "
    "$p = New-Object System.Windows.Media.MediaPlayer; "
    "$p.Open([uri]$args[0]); $p.Play(); "
    "while (-not $p.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds 50 }; "
    "Start-Sleep -Milliseconds ([int]$p.NaturalDuration.TimeSpan.TotalMilliseconds + 100); $p.Close()"
)


class Speaker(Protocol):
    async def play(self, script_ids: list[str], camera_id: str) -> None: ...
    async def stop(self) -> None: ...
    def available(self, camera_id: str) -> list[str]: ...


def audio_path(audio_dir: Path, camera_id: str, script_id: str) -> Path | None:
    for ext in AUDIO_EXTS:
        p = audio_dir / camera_id / f"{script_id}.{ext}"
        if p.exists():
            return p
    return None


def player_command(path: Path) -> list[str] | None:
    if sys.platform == "darwin":
        return ["afplay", str(path)]
    if sys.platform.startswith("win"):
        return ["powershell", "-NoProfile", "-Command", _WINDOWS_PLAYER, str(path.resolve())]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    if shutil.which("mpg123"):
        return ["mpg123", "-q", str(path)]
    if shutil.which("paplay"):
        return ["paplay", str(path)]
    return None


class LocalSpeaker:
    def __init__(self, audio_dir: Path) -> None:
        self.audio_dir = Path(audio_dir)
        self._task: asyncio.Task | None = None
        self._proc: asyncio.subprocess.Process | None = None

    def available(self, camera_id: str) -> list[str]:
        d = self.audio_dir / camera_id
        if not d.is_dir():
            return []
        return sorted({p.stem for p in d.iterdir() if p.suffix.lstrip(".") in AUDIO_EXTS})

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._kill()

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()

    async def play(self, script_ids: list[str], camera_id: str) -> None:
        await self.stop()
        paths = [p for p in (audio_path(self.audio_dir, camera_id, s) for s in script_ids) if p]
        missing = [s for s in script_ids if not audio_path(self.audio_dir, camera_id, s)]
        if missing:
            log.warning("no audio for %s on %s", missing, camera_id)
        if not paths:
            return
        started = asyncio.Event()
        self._task = asyncio.create_task(self._run(paths, started))
        # Return once the first player is running (or the task ended early).
        waiter = asyncio.create_task(started.wait())
        await asyncio.wait({waiter, self._task}, return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()

    async def _run(self, paths: list[Path], started: asyncio.Event) -> None:
        try:
            for path in paths:
                cmd = player_command(path)
                if cmd is None:
                    log.error("no audio player found on this system")
                    return
                self._proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
                )
                started.set()
                await self._proc.wait()
        finally:
            started.set()


class FakeSpeaker:
    """Records what would have been played. ``scripts=None`` means every script is available."""

    def __init__(self, scripts: list[str] | None = None) -> None:
        self.plays: list[tuple[list[str], str]] = []
        self.stops = 0
        self._scripts = scripts

    def available(self, camera_id: str) -> list[str]:
        from agent.live.playbooks import SCRIPT_IDS

        return list(SCRIPT_IDS if self._scripts is None else self._scripts)

    async def play(self, script_ids: list[str], camera_id: str) -> None:
        self.plays.append((list(script_ids), camera_id))

    async def stop(self) -> None:
        self.stops += 1

    def played(self) -> list[str]:
        """Flat list of script ids, in order."""
        return [s for seq, _ in self.plays for s in seq]
