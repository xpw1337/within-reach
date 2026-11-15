"""FastAPI app. Run with one worker (state and timers are in-process):

    uv run uvicorn agent.main:app --host 0.0.0.0 --port 8000

``--host 0.0.0.0`` lets phones on the same Wi-Fi reach it; otherwise use a tunnel.

Routers: the live SOS path (``agent/sos``: camera events, phone and dashboard websockets, the
simulated 911 agent) and the census commands (``/census``, unchanged).
"""

from __future__ import annotations

import logging
import socket
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.api import census, handcheck
from agent.sos import api as sos_api
from agent.sos.hub import Hub

log = logging.getLogger(__name__)


def lan_addresses() -> list[str]:
    """This machine's LAN IPv4 addresses (for the startup hint only)."""
    found: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent: this only picks the outbound interface
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(a for a in found if not a.startswith("127."))


def create_app(hub: Any = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.sos is None:
            app.state.sos = Hub()
        for ip in lan_addresses():
            log.warning("phones on this Wi-Fi can connect to http://%s:8000", ip)
        yield
        await app.state.sos.aclose()

    app = FastAPI(title="Within Reach agent", lifespan=lifespan)
    app.state.sos = hub
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health() -> dict:
        h = app.state.sos
        return {"ok": True, "cameras": len(h.cameras) if h else 0,
                "phones": len(h.phone_sockets) if h else 0, "lan": lan_addresses()}

    @app.get("/config/thresholds")
    async def thresholds() -> dict:
        from shared.thresholds import thresholds_payload

        return thresholds_payload()

    for module in (sos_api, census, handcheck):
        app.include_router(module.router)
    return app


app = create_app()
