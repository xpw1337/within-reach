"""Clocks and named timers that wake the graph with a ``timeout`` signal.

A timer is started by a node, which also records ``timers[name] = token`` in the incident state.
When it fires, ``signals.deliver`` resumes the graph with ``{kind: timeout, name, token}``. The
reducer ignores a timeout whose token no longer matches (cancelled or superseded), so cancelling is
an optimization, never a correctness requirement.

``RealClock`` uses asyncio tasks. ``FakeClock`` runs due callbacks in order when a test calls
``advance``, so every graph test is deterministic.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

Callback = Callable[[], Awaitable[Any]]


class Clock(Protocol):
    def now(self) -> float: ...
    def call_later(self, delay: float, callback: Callback) -> Any: ...
    def cancel(self, handle: Any) -> None: ...
    async def sleep(self, delay: float) -> None: ...


class RealClock:
    def now(self) -> float:
        return time.time()

    def call_later(self, delay: float, callback: Callback) -> asyncio.Task:
        async def run() -> None:
            await asyncio.sleep(max(0.0, delay))
            await callback()

        return asyncio.create_task(run())

    def cancel(self, handle: asyncio.Task) -> None:
        handle.cancel()

    async def sleep(self, delay: float) -> None:
        await asyncio.sleep(delay)


class FakeClock:
    """Manual time. ``advance`` fires due callbacks one at a time, awaiting each, then lets
    background tasks settle through ``settle`` (set by the runtime)."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.t = float(start)
        self._heap: list[tuple[float, int, Any]] = []
        self._seq = itertools.count()
        self._cancelled: set[int] = set()
        self.settle: Callable[[], Awaitable[None]] | None = None

    def now(self) -> float:
        return self.t

    def call_later(self, delay: float, callback: Callback) -> int:
        seq = next(self._seq)
        heapq.heappush(self._heap, (self.t + max(0.0, delay), seq, callback))
        return seq

    def cancel(self, handle: int) -> None:
        self._cancelled.add(handle)

    async def sleep(self, delay: float) -> None:
        fut = asyncio.get_running_loop().create_future()

        async def wake() -> None:
            if not fut.done():
                fut.set_result(None)

        self.call_later(delay, wake)
        await fut

    async def _settle(self) -> None:
        for _ in range(3):
            await asyncio.sleep(0)
        if self.settle is not None:
            await self.settle()

    async def advance(self, seconds: float) -> None:
        target = self.t + seconds
        await self._settle()
        while self._heap and self._heap[0][0] <= target:
            when, seq, callback = heapq.heappop(self._heap)
            if seq in self._cancelled:
                self._cancelled.discard(seq)
                continue
            self.t = max(self.t, when)
            await callback()
            await self._settle()
        self.t = target
        await self._settle()

    def pending(self) -> int:
        return sum(1 for _, seq, _ in self._heap if seq not in self._cancelled)


class TimerRegistry:
    """Named timers per incident. ``deliver`` is ``signals.deliver``."""

    def __init__(self, clock: Clock, deliver: Callable[[str, dict], Awaitable[Any]]) -> None:
        self.clock = clock
        self.deliver = deliver
        self._handles: dict[tuple[str, str], tuple[str, Any, dict]] = {}

    def start(self, incident_id: str, name: str, delay: float) -> tuple[str, float]:
        """Start (or restart) a timer. Returns ``(token, fires_at)``."""
        self.cancel(incident_id, name)
        token = uuid.uuid4().hex[:12]
        state = {"fired": False}

        async def fire() -> None:
            current = self._handles.get((incident_id, name))
            if current and current[0] == token:
                del self._handles[(incident_id, name)]
            state["fired"] = True
            await self.deliver(incident_id, {"kind": "timeout", "source": "timer", "name": name, "token": token})

        handle = self.clock.call_later(delay, fire)
        self._handles[(incident_id, name)] = (token, handle, state)
        return token, self.clock.now() + delay

    def cancel(self, incident_id: str, name: str) -> None:
        entry = self._handles.pop((incident_id, name), None)
        if entry and not entry[2]["fired"]:
            with contextlib.suppress(Exception):
                self.clock.cancel(entry[1])

    def cancel_incident(self, incident_id: str) -> None:
        for inc, name in [k for k in self._handles if k[0] == incident_id]:
            self.cancel(inc, name)

    def cancel_all(self) -> None:
        for inc, name in list(self._handles):
            self.cancel(inc, name)

    def active(self, incident_id: str) -> list[str]:
        return sorted(name for inc, name in self._handles if inc == incident_id)
