import asyncio
import logging

import pytest

from shared import db, events
from shared.config import MissingSettingError
from shared.fakes import FakeDBError, FakeSupabase


def test_get_db_names_missing_variables():
    with pytest.raises(MissingSettingError) as e:
        db.get_db()
    assert "SUPABASE_URL" in str(e.value)
    assert "SUPABASE_SERVICE_ROLE_KEY" in str(e.value)


def test_crud_helpers(fake_db):
    b = db.insert("buildings", {"costar_property_id": "X-1", "name": "A"})[0]
    assert b["id"] and b["census_status"] == "pending"
    assert db.fetch_one("buildings", costar_property_id="X-1")["name"] == "A"
    assert db.fetch_one("buildings", costar_property_id="nope") is None

    db.upsert("buildings", {"costar_property_id": "X-1", "name": "B"}, on_conflict="costar_property_id")
    rows = db.fetch_all("buildings")
    assert len(rows) == 1 and rows[0]["name"] == "B" and rows[0]["id"] == b["id"]

    with pytest.raises(FakeDBError):
        db.insert("buildings", {"costar_property_id": "X-1"})

    db.upsert(
        "twin_nodes",
        [{"building_id": b["id"], "sweep_id": s, "floor": 0, "x": 0, "y": 0, "z": 0} for s in ("s1", "s2")],
    )
    db.upsert("twin_nodes", {"building_id": b["id"], "sweep_id": "s1", "floor": 1, "x": 0, "y": 0, "z": 0})
    nodes = db.fetch_all("twin_nodes", building_id=b["id"], order="sweep_id")
    assert [n["floor"] for n in nodes] == [1, 0]
    assert len(db.fetch_all("twin_nodes", sweep_id=["s1", "s2"])) == 2

    db.update("buildings", {"census_status": "mapped"}, id=b["id"])
    assert db.fetch_one("buildings", id=b["id"])["census_status"] == "mapped"
    with pytest.raises(ValueError):
        db.update("buildings", {"name": "x"})

    assert len(db.delete("twin_nodes", sweep_id="s2")) == 1
    assert len(db.fetch_all("twin_nodes")) == 1


def test_fetch_all_pages_past_the_row_cap(fake_db, monkeypatch):
    calls = []
    query_cls = type(fake_db.table("runs"))
    real_range = query_cls.range

    def spy(self, start, end, **kw):
        calls.append((start, end))
        return real_range(self, start, end, **kw)

    monkeypatch.setattr(query_cls, "range", spy)
    fake_db.table("agent_events").insert([{"message": f"m{i}"} for i in range(2345)]).execute()
    rows = db.fetch_all("agent_events")
    assert len(rows) == 2345
    assert [r["id"] for r in rows] == list(range(1, 2346))  # ordered by primary key, no overlap
    assert calls == [(0, 999), (1000, 1999), (2000, 2999)]
    assert len(db.fetch_all("agent_events", limit=1500)) == 1500
    assert len(db.fetch_all("agent_events", page_size=100, message=["m1", "m2", "m3"])) == 3


def test_upload_returns_public_url(fake_db):
    url = db.upload("crops", "b1/d1.jpg", b"\xff\xd8jpeg", "image/jpeg")
    assert url.endswith("/storage/v1/object/public/crops/b1/d1.jpg")
    assert fake_db.storage_objects["crops"]["b1/d1.jpg"]["content_type"] == "image/jpeg"
    db.upload("crops", "b1/d1.jpg", b"again", "image/jpeg")  # overwrite allowed
    assert fake_db.storage_objects["crops"]["b1/d1.jpg"]["data"] == b"again"


def test_emit_agent_event_writes_row(fake_db):
    events.emit_agent_event(
        "run-1", "scanner", "decision", "Checking a second panorama.", "b1", {"reason": "x"}
    )
    (row,) = fake_db.rows("agent_events")
    assert row["agent"] == "scanner" and row["kind"] == "decision"
    assert row["message"] == "Checking a second panorama." and row["payload"] == {"reason": "x"}
    assert row["building_id"] == "b1" and row["run_id"] == "run-1" and row["id"] == 1


def test_event_failures_are_swallowed(fake_db, caplog):
    fake_db.fail("agent_events")
    with caplog.at_level(logging.WARNING):
        events.emit_agent_event("r", "planner", "todo", "Plan.", payload={"todos": []})
    assert "event write to agent_events failed" in caplog.text
    # No database configured at all: still no exception.
    db.set_db(None)
    events.emit_incident_event("i1", "system", "detected")


def test_unknown_kind_is_logged_but_written(fake_db, caplog):
    with caplog.at_level(logging.WARNING):
        events.emit_agent_event("r", "planner", "chitchat", "Hello.")
    assert "unknown agent_events.kind" in caplog.text
    assert len(fake_db.rows("agent_events")) == 1


def test_incident_event_sync_and_async(fake_db):
    events.emit_incident_event("inc-1", "vision", "detected", {"camera_id": "cam-lobby-1"})
    assert len(fake_db.rows("incident_events")) == 1

    async def hot_path():
        events.emit_incident_event("inc-1", "responder:abc", "dispatch_accepted")
        return "returned"

    assert asyncio.run(hot_path()) == "returned"
    events.flush_events()
    kinds = [r["kind"] for r in fake_db.rows("incident_events")]
    assert kinds == ["detected", "dispatch_accepted"]


def test_async_emit_does_not_block(monkeypatch):
    import threading

    gate = threading.Event()
    fake = FakeSupabase()
    db.set_db(fake)
    real_insert = db.insert

    def slow_insert(table, rows):
        gate.wait(2)
        return real_insert(table, rows)

    monkeypatch.setattr(db, "insert", slow_insert)

    async def hot_path():
        events.emit_incident_event("inc-2", "system", "speak", {"script_id": "voice_check"})
        # The insert is still blocked on the gate, yet we are already here.
        return len(fake.rows("incident_events"))

    assert asyncio.run(hot_path()) == 0
    gate.set()
    events.flush_events()
    assert len(fake.rows("incident_events")) == 1
