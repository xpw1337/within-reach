import pytest

from shared import db, llm
from shared.config import get_settings
from shared.fakes import FakeSupabase, isolate_settings


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    isolate_settings(monkeypatch)
    llm.reset()
    db.set_db(None)
    yield
    db.set_db(None)
    llm.reset()
    get_settings.cache_clear()


@pytest.fixture
def fake_db():
    fake = FakeSupabase()
    db.set_db(fake)
    return fake
