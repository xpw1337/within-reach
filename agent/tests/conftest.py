import pytest


@pytest.fixture(autouse=True)
def _no_real_messages(monkeypatch):
    """No test may phone or text a real person, whatever is in .env."""
    monkeypatch.setenv("SOS_CALLS", "off")
    monkeypatch.setenv("SOS_TEXTS", "off")
    monkeypatch.setenv("SOS_OFFLINE", "1")
