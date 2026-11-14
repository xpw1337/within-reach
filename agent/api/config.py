"""GET /health and GET /config/thresholds."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict:
    return {"ok": True, "warmed": dict(request.app.state.warmed)}


@router.get("/config/thresholds")
async def thresholds() -> dict:
    try:
        from shared.thresholds import thresholds_payload
    except ImportError as exc:
        raise HTTPException(503, "thresholds not available") from exc
    return thresholds_payload()
