"""io/messaging.py: the allowlist and PhotonMessenger's request sequence against a mock transport.
FIXTURE VALUES only (555 numbers, made-up ids); no request leaves the process."""

import json

import httpx
import pytest

from agent.io.messaging import FakeMessenger, MessagingError, PhotonMessenger
from agent.io.telephony import DestinationNotAllowedError, EmergencyNumberError

PRJ = "pho_prj_0" + "a" * 25
AGENT = "pho_usr_0" + "b" * 25
HUMAN = "pho_usr_0" + "c" * 25
SPACE = "pho_spc_0" + "d" * 25
MSG = "pho_msg_0" + "e" * 25
SIM = "+15550001111"
PEER = "+15550100001"
LINE = "+15550009999"
CALLABLE = {"id": "r1", "phone": PEER, "callable": True, "consent_calls": True}


class Photon:
    """A tiny fake of the Photon endpoints we call; records every request."""

    def __init__(self, *, assigned=True, send_status=202, send_code=None):
        self.requests: list[httpx.Request] = []
        self.assigned = assigned
        self.send_status = send_status
        self.send_code = send_code

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        assert path.startswith(f"/v1/projects/{PRJ}/")
        tail = path.removeprefix(f"/v1/projects/{PRJ}")
        if request.method == "GET" and tail == "/platforms/imessage/assignments":
            rows = [{"handle": "+15550100099", "assignedPhoneNumber": "+15550008888", "releasedAt": "2026-01-01T00:00:00Z"}]
            if self.assigned:
                rows.append({"handle": PEER, "assignedPhoneNumber": LINE})
            return httpx.Response(200, json={"assignments": rows})
        if request.method == "POST" and tail == "/users":
            body = json.loads(request.content)
            return httpx.Response(200, json={"id": AGENT if body["handle"] == LINE else HUMAN,
                                             "handle": body["handle"], "platform": body["platform"]})
        if request.method == "POST" and tail == "/spaces":
            return httpx.Response(200, json={"id": SPACE, "kind": "direct", "platform": "imessage"})
        if request.method == "POST" and tail == "/messages":
            if self.send_status >= 400:
                return httpx.Response(self.send_status, json={"code": self.send_code, "status": self.send_status,
                                                              "detail": f"peer {PEER} has not messaged"})
            return httpx.Response(202, json={"id": MSG, "status": "dispatched"})
        return httpx.Response(404, json={"code": "NOT_FOUND"})


def messenger(fake: Photon, **kw) -> PhotonMessenger:
    return PhotonMessenger(api_key="pho_sk_test", project_id=PRJ, dispatch_sim_number=SIM,
                           transport=httpx.MockTransport(fake), **kw)


def calls(fake: Photon) -> list[tuple[str, str]]:
    return [(r.method, r.url.path.removeprefix(f"/v1/projects/{PRJ}")) for r in fake.requests]


async def test_first_send_looks_up_the_chat_then_sends():
    fake = Photon()
    m = messenger(fake)
    assert await m.text_responder(CALLABLE, "hello", key="within-reach-alert-d1") == MSG
    assert calls(fake) == [("GET", "/platforms/imessage/assignments"), ("POST", "/users"), ("POST", "/users"),
                           ("POST", "/spaces"), ("POST", "/messages")]
    users = [json.loads(r.content) for r in fake.requests[1:3]]
    assert users == [{"handle": LINE, "platform": "imessage"}, {"handle": PEER, "platform": "imessage"}]
    space = fake.requests[3]
    assert json.loads(space.content) == {"participantIds": [AGENT, HUMAN], "platform": "imessage"}
    assert space.headers["Idempotency-Key"]
    send = fake.requests[4]
    assert send.headers["Authorization"] == "Bearer pho_sk_test"
    assert send.headers["Idempotency-Key"] == "within-reach-alert-d1"
    assert json.loads(send.content) == {"spaceId": SPACE, "senderId": AGENT,
                                        "content": {"type": "text", "format": "plain", "text": "hello"}}
    # cached: the next text to the same phone is one request
    await m.text_responder(CALLABLE, "again", key="within-reach-role-d1")
    assert calls(fake)[-1] == ("POST", "/messages") and len(fake.requests) == 6
    await m.aclose()


async def test_chat_from_an_inbound_webhook_skips_the_lookup():
    fake = Photon()
    m = messenger(fake)
    m.remember("+1 555 000 1111", SPACE, AGENT)
    await m.text_dispatch("briefing", key="within-reach-briefing-i1")
    assert calls(fake) == [("POST", "/messages")]
    await m.aclose()


async def test_photon_errors_are_reported_without_the_problem_detail():
    fake = Photon(send_status=403, send_code="SHARED_LINE_INBOUND_REQUIRED")
    m = messenger(fake)
    with pytest.raises(MessagingError) as err:
        await m.text_responder(CALLABLE, "hello", key="k1")
    assert "403" in str(err.value) and "SHARED_LINE_INBOUND_REQUIRED" in str(err.value)
    assert PEER not in str(err.value)
    with pytest.raises(MessagingError, match="no active shared iMessage line"):
        await messenger(Photon(assigned=False)).text_responder(CALLABLE, "hello", key="k2")
    await m.aclose()


async def test_network_failure_and_timeout_raise_messaging_error():
    def boom(request):
        raise httpx.ConnectTimeout("slow", request=request)

    m = PhotonMessenger(api_key="k", project_id=PRJ, dispatch_sim_number=SIM, transport=httpx.MockTransport(boom))
    with pytest.raises(MessagingError, match="ConnectTimeout"):
        await m.text_dispatch("x", key="k")
    await m.aclose()


@pytest.mark.parametrize("number", ["911", "+1 911", "(911) 555-0100", "112", "+44 999", "000"])
async def test_emergency_numbers_raise_before_any_request(number):
    fake = Photon()
    m = messenger(fake)
    with pytest.raises(EmergencyNumberError):
        await m.text_responder(dict(CALLABLE, phone=number), "hello", key="k")
    assert fake.requests == []
    with pytest.raises(EmergencyNumberError):
        await FakeMessenger().text_responder(dict(CALLABLE, phone=number), "hello", key="k")
    with pytest.raises(EmergencyNumberError):
        FakeMessenger(dispatch_sim_number=number)
    with pytest.raises(EmergencyNumberError):
        PhotonMessenger(api_key="k", project_id=PRJ, dispatch_sim_number=number)
    await m.aclose()


async def test_same_allowlist_as_calls():
    fake = Photon()
    m = messenger(fake)
    for bad in (dict(CALLABLE, callable=False), dict(CALLABLE, consent_calls=False), dict(CALLABLE, phone=None),
                dict(CALLABLE, phone="5550100001")):
        with pytest.raises(DestinationNotAllowedError):
            await m.text_responder(bad, "hello", key="k")
    with pytest.raises(DestinationNotAllowedError):
        await PhotonMessenger(api_key="k", project_id=PRJ, dispatch_sim_number=None,
                              transport=httpx.MockTransport(fake)).text_dispatch("x", key="k")
    assert fake.requests == []
    with pytest.raises(MessagingError):
        PhotonMessenger(api_key="k", project_id="not-a-project", dispatch_sim_number=SIM)
    await m.aclose()
