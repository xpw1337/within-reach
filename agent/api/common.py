"""Small helpers shared by the routers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException


def db_or_503() -> Any:
    """``shared.db`` when a database is configured, else 503."""
    try:
        from shared import db
        from shared.config import get_settings
    except ImportError as exc:
        raise HTTPException(503, "database not available") from exc
    s = get_settings()
    if db._override is None and not (s.supabase_url and s.supabase_service_role_key):
        raise HTTPException(503, "database not available")
    return db


async def in_thread(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    return await asyncio.to_thread(fn, *args, **kwargs)
