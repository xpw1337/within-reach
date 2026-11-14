"""TwilioTelephony on both paths (plain Twilio, Photon number over SIP) with a fake Twilio client.
FIXTURE VALUES only: 555 numbers and made-up credentials, nothing is dialed."""

from types import SimpleNamespace

import pytest

from agent.io.telephony import (
    DestinationNotAllowedError,
    EmergencyNumberError,
    PhotonSip,
    TelephonyError,
    TwilioTelephony,
)

SIM = "+15550001111"
PHOTON = "+15550003333"
CALLABLE = {"id": "r1", "phone": "+1 (555) 010-0001", "callable": True, "consent_calls": True}


class FakeCalls:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.updated: list[tuple[str, dict]] = []

    def create(self, **kw):
        self.created.append(kw)
        return SimpleNamespace(sid=f"CAtest{len(self.created):04d}")


class FakeClient:
    """Mimics ``twilio.rest.Client``: ``client.calls.create(...)`` and ``client.calls(sid).update(...)``."""

    def __init__(self) -> None:
        self._calls = FakeCalls()

    @property
    def calls(self):
        fake = self._calls

        class Calls:
            def __call__(self, sid):
                return SimpleNamespace(update=lambda **kw: fake.updated.append((sid, kw)))

            create = staticmethod(fake.create)

        return Calls()


def sip(**kw) -> PhotonSip:
    args = {"server": "sip.example.test:5061", "username": "wr-out", "password": "pw-test", "number": PHOTON}
    args.update(kw)
    return PhotonSip(**args)


def telephony(client, **kw) -> TwilioTelephony:
    args = {"account_sid": "ACtest", "auth_token": "token", "from_number": "+15550004444",
            "public_base_url": "https://agent.example.test/", "dispatch_sim_number": SIM, "client": client}
    args.update(kw)
    return TwilioTelephony(**args)


async def test_plain_twilio_call_uses_the_twilio_number():
    client = FakeClient()
    t = telephony(client)
    sid = await t.call_responder({"id": "d1"}, CALLABLE)
    assert sid == "CAtest0001"
    kw = client._calls.created[0]
    assert kw["to"] == "+15550100001" and kw["from_"] == "+15550004444"
    assert kw["url"] == "https://agent.example.test/twilio/voice/d1" and kw["method"] == "POST"
    assert "sip_auth_username" not in kw


async def test_photon_sip_call_goes_through_the_photon_number():
    client = FakeClient()
    t = telephony(client, from_number=None, sip=sip())
    await t.call_responder({"id": "d1"}, CALLABLE)
    await t.call_briefing("inc-1")
    responder_call, briefing_call = client._calls.created
    assert responder_call["to"] == "sip:+15550100001@sip.example.test:5061;transport=tls;secure=true"
    assert responder_call["from_"] == PHOTON
    assert responder_call["sip_auth_username"] == "wr-out" and responder_call["sip_auth_password"] == "pw-test"
    assert responder_call["url"] == "https://agent.example.test/twilio/voice/d1"  # our TwiML still runs
    assert briefing_call["to"] == f"sip:{SIM}@sip.example.test:5061;transport=tls;secure=true"
    assert briefing_call["url"] == "https://agent.example.test/twilio/briefing/inc-1"
    await t.hangup("CAtest0001")
    assert client._calls.updated == [("CAtest0001", {"status": "completed"})]


@pytest.mark.parametrize("use_sip", [False, True])
@pytest.mark.parametrize("number", ["911", "+1 911", "(911) 555-0100", "112", "+44 999"])
async def test_both_paths_refuse_emergency_numbers(use_sip, number):
    client = FakeClient()
    t = telephony(client, sip=sip() if use_sip else None)
    with pytest.raises(EmergencyNumberError):
        await t.call_responder({"id": "d1"}, dict(CALLABLE, phone=number))
    assert client._calls.created == []


@pytest.mark.parametrize("use_sip", [False, True])
async def test_both_paths_keep_the_allowlist(use_sip):
    client = FakeClient()
    t = telephony(client, sip=sip() if use_sip else None)
    with pytest.raises(DestinationNotAllowedError):
        await t.call_responder({"id": "d1"}, dict(CALLABLE, consent_calls=False))
    with pytest.raises(DestinationNotAllowedError):
        await t.call_responder({"id": "d1"}, dict(CALLABLE, phone="5550100001"))  # not E.164
    assert client._calls.created == []
    with pytest.raises(EmergencyNumberError):
        telephony(client, sip=sip() if use_sip else None, dispatch_sim_number="911")


@pytest.mark.parametrize("bad", [
    {"server": "sip.example.test:5061;transport=udp"},
    {"server": "user@sip.example.test"},
    {"server": ""},
    {"number": "911"},
    {"number": "5550003333"},
])
def test_photon_sip_settings_are_validated(bad):
    with pytest.raises(TelephonyError):
        sip(**bad)


def test_password_is_not_in_repr():
    assert "pw-test" not in repr(sip())


def test_twilio_without_a_from_number_needs_sip():
    with pytest.raises(TelephonyError):
        telephony(FakeClient(), from_number=None)
