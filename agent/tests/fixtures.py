"""Test fixture rows. FIXTURE VALUES, not measurements: they exist only so tests can run offline."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from agent.io.speaker import FakeSpeaker
from agent.io.telephony import FakeTelephony
from agent.io.verify import FakeVerifier
from agent.live.config import LiveConfig
from agent.live.signals import LiveRuntime
from agent.live.store import MemoryStore
from agent.live.timers import FakeClock

T0 = 1_800_000_000.0
BUILDING = {"id": "b-test", "name": "Test Gym", "address": "1 Test St", "lat": 29.76, "lng": -95.37,
            "geofence_m": 60, "ems_door": {"desc": "north doors"}, "monitoring_callback": "+15550002222"}
CAMERA = {"id": "cam-test", "building_id": "b-test", "sweep_id": "s1", "floor": 0, "landmark": "east elevators"}
ROUTES = [{"camera_id": "cam-test", "target": "aed", "distance_m": 14.0, "directions": "left of the elevators",
           "path": ["s1", "s2"], "audio_url": None}]


def responder(i, role="public", cpr=False, callable_=False, **kw):
    r = {"id": f"r{i}", "name": f"R{i}", "phone": f"+1555010{i:04d}", "role": role, "cpr_trained": cpr,
         "callable": callable_, "consent_calls": callable_, "consent_location": True, "on_duty": True,
         "building_id": "b-test", "last_lat": 29.76, "last_lng": -95.37, "last_seen_at": T0 - 30}
    r.update(kw)
    return r


def default_responders(n=10):
    out = [responder(0, "staff", cpr=True, callable_=True)]
    out += [responder(i, "public", callable_=(i == 1)) for i in range(1, n)]
    return out


@asynccontextmanager
async def runtime(tmp_path: Path, *, responders=None, verifier=None, speaker=None, telephony=None,
                  routes=None, cfg=None, messenger=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    clock = FakeClock(T0)
    store = MemoryStore(cameras=[CAMERA], routes=ROUTES if routes is None else routes, buildings=[BUILDING],
                        responders=default_responders() if responders is None else responders)
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "cp.sqlite")) as saver:
        rt = LiveRuntime(cfg=cfg or LiveConfig(), store=store, speaker=speaker or FakeSpeaker(),
                         telephony=telephony or FakeTelephony(),
                         verifier=verifier or FakeVerifier(sleep=clock.sleep), clock=clock,
                         checkpointer=saver, messenger=messenger)
        yield rt
        await rt.settle()
