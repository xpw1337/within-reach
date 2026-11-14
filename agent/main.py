"""FastAPI app factory. Run with one worker: ``uv run uvicorn agent.main:app --port 8000``.

Lifespan: settings, checkpointer (SQLite at ``.cache/checkpoints.sqlite``), runtime with the timer
registry and the compiled graph, then warm-up (camera context, speaker audio, LLM ping) without
blocking startup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.api import census, config, dispatches, events, handcheck, incidents, simulate, twilio

log = logging.getLogger(__name__)


async def warm_up(app: FastAPI) -> None:
    """Fill the camera cache, make sure audio exists, ping the LLM. Never raises."""
    from agent import deps
    from agent.io.tts import render_camera_audio

    rt = app.state.runtime
    warmed = app.state.warmed
    camera_id = app.state.camera_id
    try:
        camera, _, _ = await rt.camera_context(camera_id, refresh=True)
        warmed["db"] = bool(camera.get("building_id") or camera.get("landmark"))
    except Exception as exc:  # noqa: BLE001
        log.warning("warm-up: camera context failed: %s", exc)
    try:
        if "voice_check" not in rt.speaker.available(camera_id):
            await render_camera_audio(camera_id, store=rt.store, tts=deps.default_tts(),
                                      audio_dir=deps.audio_dir(), upload=deps.default_upload())
        warmed["tts"] = "voice_check" in rt.speaker.available(camera_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("warm-up: audio render failed: %s", exc)

    async def ping_llm() -> None:
        try:
            from shared import llm

            await asyncio.wait_for(asyncio.to_thread(llm.warm_up, ("reasoning",)), timeout=30)
            warmed["llm"] = True
        except Exception as exc:  # noqa: BLE001 - the live path does not need the LLM
            log.warning("warm-up: LLM unavailable: %s", exc)

    rt.spawn(ping_llm())


def create_app(runtime: Any = None, *, camera_id: str | None = None, warm: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            if app.state.runtime is None:
                from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

                from agent import deps
                from agent.io.speaker import LocalSpeaker
                from agent.io.verify import SceneVerifier
                from agent.live.config import from_settings
                from agent.live.signals import LiveRuntime
                from agent.live.timers import RealClock

                s = deps.settings()
                cfg = from_settings(s)
                deps.cache_dir().mkdir(parents=True, exist_ok=True)
                saver = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(deps.cache_dir() / "checkpoints.sqlite")))
                app.state.runtime = LiveRuntime(
                    cfg=cfg, store=deps.default_store(), speaker=LocalSpeaker(deps.audio_dir()),
                    telephony=deps.default_telephony(), verifier=SceneVerifier(cfg.verify_timeout_seconds),
                    clock=RealClock(), checkpointer=saver)
                app.state.camera_id = camera_id or s.camera_id
            if warm:
                await warm_up(app)
            yield
            rt = app.state.runtime
            rt.timers.cancel_all()
            with contextlib.suppress(Exception):
                await rt.speaker.stop()
            with contextlib.suppress(Exception):
                await rt.store.flush()

    app = FastAPI(title="Within Reach agent", lifespan=lifespan)
    app.state.runtime = runtime
    app.state.camera_id = camera_id or "cam-lobby-1"
    app.state.warmed = {"llm": False, "tts": False, "db": False}
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    for module in (config, census, handcheck, events, incidents, dispatches, twilio, simulate):
        app.include_router(module.router)
    return app


app = create_app()
