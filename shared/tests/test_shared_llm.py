import logging

import pytest

from shared import llm
from shared.config import MissingSettingError
from shared.fakes import FakeAnthropic, FakeUsage, fake_json_message, isolate_settings

SCHEMA = {
    "type": "object",
    "properties": {
        "confirmed": {"type": "boolean"},
        "reason": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["confirmed", "reason", "confidence"],
    "additionalProperties": False,
}
GOOD = {"confirmed": True, "reason": "red AED cabinet", "confidence": 0.9}


def _anthropic(monkeypatch):
    isolate_settings(monkeypatch, USE_BEDROCK="false", ANTHROPIC_API_KEY="test-key")


def _bedrock(monkeypatch, **extra):
    isolate_settings(
        monkeypatch, USE_BEDROCK="true", AWS_ACCESS_KEY_ID="AKIATEST", AWS_SECRET_ACCESS_KEY="secret", **extra
    )


# ---------------------------------------------------------------- provider config


def test_missing_key_named_on_anthropic_path(monkeypatch):
    isolate_settings(monkeypatch, USE_BEDROCK="false")
    with pytest.raises(MissingSettingError) as e:
        llm.warm_up()
    assert "ANTHROPIC_API_KEY" in str(e.value)


def test_missing_aws_vars_named_on_bedrock_path(monkeypatch):
    isolate_settings(monkeypatch, USE_BEDROCK="true")
    with pytest.raises(MissingSettingError) as e:
        llm.warm_up()
    msg = str(e.value)
    assert "AWS_ACCESS_KEY_ID" in msg and "AWS_SECRET_ACCESS_KEY" in msg


def test_only_the_missing_aws_var_is_named(monkeypatch):
    isolate_settings(monkeypatch, USE_BEDROCK="true", AWS_ACCESS_KEY_ID="AKIATEST")
    with pytest.raises(MissingSettingError) as e:
        llm.provider()
    assert "AWS_SECRET_ACCESS_KEY" in str(e.value) and "AWS_ACCESS_KEY_ID" not in str(e.value)


def test_missing_aws_falls_back_to_api_key(monkeypatch, caplog):
    isolate_settings(monkeypatch, USE_BEDROCK="true", ANTHROPIC_API_KEY="test-key")
    with caplog.at_level(logging.WARNING):
        assert llm.provider() == "anthropic"
        assert llm.provider() == "anthropic"
    assert caplog.text.count("Falling back from Bedrock") == 1


def test_bedrock_model_ids():
    # Checked against the Bedrock docs (see llm.BEDROCK_MODEL_IDS).
    assert llm.bedrock_model_id("claude-sonnet-5-5") == "anthropic.claude-sonnet-5-5"
    assert llm.bedrock_model_id("claude-haiku-5-5") == "anthropic.claude-haiku-5-5"
    assert llm.bedrock_model_id("anthropic.claude-haiku-5-5") == "anthropic.claude-haiku-5-5"


def test_real_clients_construct_without_network(monkeypatch):
    _bedrock(monkeypatch)
    import anthropic

    assert isinstance(llm._client("bedrock"), anthropic.AnthropicBedrockMantle)
    llm.reset()
    _anthropic(monkeypatch)
    assert isinstance(llm._client("anthropic"), anthropic.Anthropic)


# ---------------------------------------------------------------- complete_json


def test_complete_json_anthropic_request_shape(monkeypatch):
    _anthropic(monkeypatch)
    fake = FakeAnthropic([fake_json_message(GOOD)])
    llm.set_client(fake)
    out = llm.complete_json(
        tier="fast", system="sys", user=[llm.text_part("look")], schema=SCHEMA, max_tokens=500
    )
    assert out == GOOD
    (call,) = fake.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["max_tokens"] == 500
    assert call["messages"] == [{"role": "user", "content": [{"type": "text", "text": "look"}]}]
    assert call["system"][0]["text"] == "sys"
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    # Numeric constraints are not supported by the API: the SDK transform moves them out.
    assert "minimum" not in fmt["schema"]["properties"]["confidence"]
    assert call["output_config"]["effort"] == "low"


def test_complete_json_bedrock_uses_prefixed_model(monkeypatch):
    _bedrock(monkeypatch)
    fake = FakeAnthropic([fake_json_message(GOOD)])
    llm.set_client(fake, "bedrock")
    llm.complete_json(tier="reasoning", system="s", user=[llm.text_part("x")], schema=SCHEMA)
    assert fake.calls[0]["model"] == "anthropic.claude-sonnet-5-5"
    assert fake.calls[0]["output_config"]["effort"] == "medium"


def test_complete_json_retries_once_then_succeeds(monkeypatch):
    _anthropic(monkeypatch)
    fake = FakeAnthropic([fake_json_message("not json"), fake_json_message(GOOD)])
    llm.set_client(fake)
    assert llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA) == GOOD
    assert len(fake.calls) == 2


def test_complete_json_validates_in_code(monkeypatch):
    _anthropic(monkeypatch)
    bad = {"confirmed": True, "reason": "x", "confidence": 1.7}  # violates maximum
    fake = FakeAnthropic([fake_json_message(bad), fake_json_message(bad)])
    llm.set_client(fake)
    with pytest.raises(llm.LLMOutputError) as e:
        llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA)
    assert "maximum" in str(e.value)
    assert len(fake.calls) == 2


def test_complete_json_doubles_tokens_after_max_tokens_stop(monkeypatch):
    _anthropic(monkeypatch)
    fake = FakeAnthropic(
        [fake_json_message('{"confirmed": tr', stop_reason="max_tokens"), fake_json_message(GOOD)]
    )
    llm.set_client(fake)
    llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA, max_tokens=300)
    assert [c["max_tokens"] for c in fake.calls] == [300, 600]


def test_complete_json_refusal_raises_after_retry(monkeypatch):
    _anthropic(monkeypatch)
    fake = FakeAnthropic([fake_json_message("", stop_reason="refusal")] * 2)
    llm.set_client(fake)
    with pytest.raises(llm.LLMOutputError, match="refusal"):
        llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA)


def test_provider_errors_become_llm_error(monkeypatch):
    import anthropic

    _anthropic(monkeypatch)
    llm.set_client(
        FakeAnthropic(
            error=anthropic.APIConnectionError(request=__import__("httpx2").Request("POST", "https://x"))
        )
    )
    with pytest.raises(llm.LLMError):
        llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA)


def test_image_part():
    p = llm.image_part(b"\x89PNG", "image/png")
    assert p["type"] == "image" and p["source"]["media_type"] == "image/png"
    assert p["source"]["data"] == "iVBORw=="


# ---------------------------------------------------------------- cost metering


def test_price_math():
    # Sonnet 5.5: $2 in, $10 out, $0.10 cache read, $2.50 5m write per MTok.
    usd = llm.estimate_cost_usd(
        "claude-sonnet-5-5",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_read_tokens=1_000_000,
        cache_write_5m_tokens=1_000_000,
    )
    assert usd == pytest.approx(2.0 + 1.0 + 0.10 + 2.50)
    # Haiku 5.5 switches price tier above 100,000 prompt tokens.
    small = llm.estimate_cost_usd("claude-haiku-5-5", input_tokens=100_000, output_tokens=0)
    big = llm.estimate_cost_usd("claude-haiku-5-5", input_tokens=100_001, output_tokens=0)
    assert small == pytest.approx(0.01)
    assert big == pytest.approx(100_001 * 0.50 / 1e6)
    assert llm.estimate_cost_usd(
        "claude-haiku-5-5", input_tokens=1000, output_tokens=0, bedrock=True
    ) == pytest.approx(1.1 * llm.estimate_cost_usd("claude-haiku-5-5", input_tokens=1000, output_tokens=0))


def test_cost_added_to_run_with_rpc(monkeypatch, fake_db):
    _anthropic(monkeypatch)
    run = fake_db.table("runs").insert({"buildings_target": 1}).execute().data[0]
    usage = FakeUsage(input_tokens=2000, output_tokens=400)
    llm.set_client(FakeAnthropic([fake_json_message(GOOD, usage=usage)]))
    llm.complete_json(tier="fast", system="s", user=[], schema=SCHEMA, run_id=run["id"])
    expected = (2000 * 0.10 + 400 * 0.50) / 1e6
    assert fake_db.rows("runs")[0]["est_cost_usd"] == pytest.approx(expected)
    assert llm.session_cost_usd(run["id"]) == pytest.approx(expected)


def test_cost_falls_back_without_rpc(monkeypatch, fake_db):
    _anthropic(monkeypatch)
    fake_db.rpcs.clear()
    run = fake_db.table("runs").insert({"buildings_target": 1}).execute().data[0]
    llm.record_cost(run["id"], 0.25)
    llm.record_cost(run["id"], 0.5)
    assert fake_db.rows("runs")[0]["est_cost_usd"] == pytest.approx(0.75)


def test_cost_write_failure_never_raises(monkeypatch, fake_db):
    fake_db.fail("rpc:add_run_cost")
    fake_db.fail("runs")
    llm.record_cost("r1", 0.1)  # logged, not raised
    assert llm.session_cost_usd("r1") == pytest.approx(0.1)


# ---------------------------------------------------------------- warm-up


def test_warm_up_pings_each_tier(monkeypatch):
    _anthropic(monkeypatch)
    fake = FakeAnthropic([fake_json_message("OK"), fake_json_message("OK")])
    llm.set_client(fake)
    llm.warm_up()
    assert [c["model"] for c in fake.calls] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_warm_up_bedrock_failure_falls_back(monkeypatch, caplog):
    _bedrock(monkeypatch, ANTHROPIC_API_KEY="test-key")
    llm.set_client(FakeAnthropic(error=RuntimeError("AccessDeniedException")), "bedrock")
    direct = FakeAnthropic([fake_json_message("OK"), fake_json_message("OK")])
    llm.set_client(direct, "anthropic")
    with caplog.at_level(logging.WARNING):
        llm.warm_up()
    assert "Falling back from Bedrock" in caplog.text
    assert llm.provider() == "anthropic"
    assert len(direct.calls) == 2


def test_warm_up_bedrock_failure_without_key_raises(monkeypatch):
    _bedrock(monkeypatch)
    llm.set_client(FakeAnthropic(error=RuntimeError("AccessDeniedException")), "bedrock")
    with pytest.raises(llm.LLMError, match="AccessDenied"):
        llm.warm_up()


# ---------------------------------------------------------------- LangChain


def test_get_chat_model_both_paths(monkeypatch):
    from langchain_anthropic import ChatAnthropic
    from langchain_aws import ChatAnthropicMantle

    _anthropic(monkeypatch)
    m = llm.get_chat_model("reasoning", run_id="r1")
    assert isinstance(m, ChatAnthropic) and m.model == "claude-sonnet-5-5"
    assert m.callbacks and type(m.callbacks[0]).__name__ == "CostMeteringCallback"

    llm.reset()
    _bedrock(monkeypatch)
    m = llm.get_chat_model("fast")
    assert isinstance(m, ChatAnthropicMantle) and m.model == "anthropic.claude-haiku-5-5"
    assert m.region_name == "us-east-1"


def test_chat_model_callback_meters(monkeypatch, fake_db):
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, LLMResult

    _anthropic(monkeypatch)
    run = fake_db.table("runs").insert({"buildings_target": 1}).execute().data[0]
    cb = llm.get_chat_model("reasoning", run_id=run["id"]).callbacks[0]
    msg = AIMessage(
        content="hi",
        usage_metadata={
            "input_tokens": 1500,
            "output_tokens": 100,
            "total_tokens": 1600,
            "input_token_details": {"cache_read": 1000, "cache_creation": 0},
        },
    )
    cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))
    expected = (500 * 2.0 + 1000 * 0.10 + 100 * 10.0) / 1e6
    assert fake_db.rows("runs")[0]["est_cost_usd"] == pytest.approx(expected)


def test_schema_errors_subset():
    s = {
        "type": "object",
        "properties": {"items": {"type": "array", "maxItems": 2, "items": {"type": "integer"}}},
        "required": ["items"],
        "additionalProperties": False,
    }
    assert llm.schema_errors({"items": [1, 2]}, s) == []
    assert llm.schema_errors({"items": [1, 2, 3]}, s)
    assert llm.schema_errors({"items": [1, True]}, s)  # bool is not an integer
    assert llm.schema_errors({"items": [], "x": 1}, s)
    assert llm.schema_errors({}, s)
    assert (
        llm.schema_errors(
            {"a": None},
            {"type": "object", "properties": {"a": {"anyOf": [{"type": "null"}, {"type": "string"}]}}},
        )
        == []
    )
