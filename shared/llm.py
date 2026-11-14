"""The only module that talks to the LLM provider (docs/ARCHITECTURE.md decision D2).

Two provider paths, chosen by ``USE_BEDROCK``:

- ``USE_BEDROCK=true``: Claude in Amazon Bedrock through the Messages API on the ``bedrock-mantle``
  endpoint (``anthropic.AnthropicBedrockMantle``). Model IDs there carry an ``anthropic.`` prefix.
- ``USE_BEDROCK=false``: the Anthropic API (``anthropic.Anthropic``).

If Bedrock credentials are missing, or the Bedrock call fails at warm-up, and ``ANTHROPIC_API_KEY``
is set, calls fall back to the Anthropic API and a warning is logged once.

``complete_json`` forces schema-valid JSON with structured outputs (``output_config.format`` with a
JSON schema; the installed SDK supports it on both clients), validates the result again in code,
retries once on invalid output, and returns a dict. Every call is metered from the response usage
and the price table below, and the cost is added to ``runs.est_cost_usd`` when ``run_id`` is given.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import anthropic

from shared import db
from shared.config import MissingSettingError, Settings, get_settings

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

log = logging.getLogger(__name__)

Tier = Literal["fast", "reasoning"]
Provider = Literal["anthropic", "bedrock"]
# One Anthropic Messages API content block: {"type": "text", ...} or {"type": "image", ...}.
ContentPart = dict[str, Any]

# ---------------------------------------------------------------------------
# Model IDs
# ---------------------------------------------------------------------------

# Bedrock (bedrock-mantle) model IDs. Checked 2026-11-14 against
# https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock ("Supported models").
BEDROCK_MODEL_IDS: dict[str, str] = {
    "claude-sonnet-5-5": "anthropic.claude-sonnet-5-5",
    "claude-haiku-5-5": "anthropic.claude-haiku-5-5",
}


def bedrock_model_id(model: str) -> str:
    """Bedrock model ID for a first-party model ID (documented rule: an ``anthropic.`` prefix)."""
    if model.startswith("anthropic."):
        return model
    return BEDROCK_MODEL_IDS.get(model, f"anthropic.{model}")


def model_for(tier: Tier, settings: Settings | None = None) -> str:
    """The configured first-party model ID for a tier."""
    s = settings or get_settings()
    if tier == "fast":
        return s.claude_model_fast
    if tier == "reasoning":
        return s.claude_model_reasoning
    raise ValueError(f"unknown tier {tier!r}")


# ---------------------------------------------------------------------------
# Prices and cost metering
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Price:
    """USD per million tokens."""

    input: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    output: float


# Anthropic API list prices, USD per million tokens.
# Source: https://platform.claude.com/docs/en/about-claude/pricing ("Model pricing"), checked 2026-11-14.
# Each entry is a list of (max prompt tokens or None, Price); the first tier that fits applies.
# Claude Haiku 5.5 is priced by prompt length (over 100,000 prompt tokens pays the higher row).
PRICES_CHECKED = "2026-11-14"
PRICES: dict[str, list[tuple[int | None, Price]]] = {
    "claude-sonnet-5-5": [(None, Price(2.00, 2.50, 4.00, 0.10, 10.00))],
    "claude-haiku-5-5": [
        (100_000, Price(0.10, 0.125, 0.20, 0.01, 0.50)),
        (None, Price(0.50, 0.625, 1.00, 0.05, 2.50)),
    ],
}
# Bedrock is billed by AWS. The AWS pricing page did not show per-token figures for these models
# when checked (2026-11-14), so Bedrock calls are metered at the Anthropic list price times the
# documented 10 percent regional-endpoint premium (platform.claude.com claude-in-amazon-bedrock,
# "Regions"). This errs high for the budget guard; the real bill may be lower on the global endpoint.
BEDROCK_PRICE_MULTIPLIER = 1.10

_warned_models: set[str] = set()


def _price_for(model: str, prompt_tokens: int) -> Price:
    key = model.removeprefix("anthropic.")
    tiers = PRICES.get(key)
    if tiers is None:
        # Unknown model: meter at the most expensive known model so the budget guard errs high.
        if key not in _warned_models:
            _warned_models.add(key)
            log.warning("no price for model %r; metering at the highest known price", key)
        return max((p for rows in PRICES.values() for _, p in rows), key=lambda p: p.output)
    for limit, price in tiers:
        if limit is None or prompt_tokens <= limit:
            return price
    return tiers[-1][1]


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    bedrock: bool = False,
) -> float:
    """Cost of one call. ``input_tokens`` is the uncached input only (as the API reports it)."""
    prompt = input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens
    p = _price_for(model, prompt)
    usd = (
        input_tokens * p.input
        + cache_read_tokens * p.cache_read
        + cache_write_5m_tokens * p.cache_write_5m
        + cache_write_1h_tokens * p.cache_write_1h
        + output_tokens * p.output
    ) / 1_000_000
    return usd * (BEDROCK_PRICE_MULTIPLIER if bedrock else 1.0)


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def cost_from_usage(model: str, usage: Any, *, bedrock: bool = False) -> float:
    """Cost from an Anthropic ``Usage`` object (or a dict with the same fields)."""
    cache_creation = _get(usage, "cache_creation")
    w5 = _get(cache_creation, "ephemeral_5m_input_tokens") or 0
    w1 = _get(cache_creation, "ephemeral_1h_input_tokens") or 0
    if not (w5 or w1):
        w5 = _get(usage, "cache_creation_input_tokens") or 0  # default TTL is 5 minutes
    return estimate_cost_usd(
        model,
        input_tokens=_get(usage, "input_tokens") or 0,
        output_tokens=_get(usage, "output_tokens") or 0,
        cache_read_tokens=_get(usage, "cache_read_input_tokens") or 0,
        cache_write_5m_tokens=w5,
        cache_write_1h_tokens=w1,
        bedrock=bedrock,
    )


_cost_lock = threading.Lock()
_session_cost: dict[str | None, float] = {}
_rpc_available = True


def session_cost_usd(run_id: str | None = None) -> float:
    """Cost metered by this process for ``run_id`` (None: calls without a run)."""
    with _cost_lock:
        return _session_cost.get(run_id, 0.0)


def record_cost(run_id: str | None, usd: float) -> None:
    """Add ``usd`` to this process's tally and, with a run, to ``runs.est_cost_usd``.

    Uses the atomic ``add_run_cost`` database function when it exists, otherwise a read-modify-write
    under a process lock. Failures are logged, never raised: metering must not break a call.
    """
    global _rpc_available
    with _cost_lock:
        _session_cost[run_id] = _session_cost.get(run_id, 0.0) + usd
    if not run_id or usd <= 0:
        return
    if _rpc_available:
        try:
            db.rpc("add_run_cost", {"p_run_id": run_id, "p_delta": usd})
            return
        except Exception as exc:  # noqa: BLE001
            _rpc_available = False
            log.warning("add_run_cost rpc unavailable (%s); using read-modify-write", exc)
    try:
        with _cost_lock:
            row = db.fetch_one("runs", columns="id,est_cost_usd", id=run_id)
            if row is None:
                log.warning("cost for unknown run %s not recorded", run_id)
                return
            db.update("runs", {"est_cost_usd": (row.get("est_cost_usd") or 0.0) + usd}, id=run_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("could not add cost to run %s: %s", run_id, exc)


# ---------------------------------------------------------------------------
# Provider selection and clients
# ---------------------------------------------------------------------------

_client_lock = threading.Lock()
_clients: dict[str, Any] = {}
_client_overrides: dict[str, Any] = {}
_fallback_reason: str | None = None


class LLMError(RuntimeError):
    """The provider call failed."""


class LLMOutputError(LLMError):
    """The model did not return schema-valid JSON after one retry."""


def set_client(client: Any | None, provider: Provider | None = None) -> None:
    """Inject a client exposing ``messages.create(**kwargs)`` (tests). ``None`` clears overrides."""
    if client is None:
        _client_overrides.clear()
        return
    for p in [provider] if provider else ["anthropic", "bedrock"]:
        _client_overrides[p] = client


def reset() -> None:
    """Forget cached clients, the fallback decision and the session cost tally (tests)."""
    global _fallback_reason, _rpc_available
    with _client_lock:
        _clients.clear()
    _client_overrides.clear()
    _fallback_reason = None
    _rpc_available = True
    with _cost_lock:
        _session_cost.clear()


def _check_config(provider: Provider, s: Settings) -> None:
    if provider == "anthropic":
        if not s.anthropic_api_key:
            raise MissingSettingError(
                ["ANTHROPIC_API_KEY"],
                hint="The Anthropic API path needs it. Or set USE_BEDROCK=true with AWS_ACCESS_KEY_ID "
                "and AWS_SECRET_ACCESS_KEY.",
            )
        return
    missing = []
    if not s.aws_region:
        missing.append("AWS_REGION")
    if not s.aws_bearer_token_bedrock:
        if not s.aws_access_key_id:
            missing.append("AWS_ACCESS_KEY_ID")
        if not s.aws_secret_access_key:
            missing.append("AWS_SECRET_ACCESS_KEY")
    if missing:
        raise MissingSettingError(
            missing,
            hint="USE_BEDROCK=true needs AWS credentials (or AWS_BEARER_TOKEN_BEDROCK). Or set "
            "USE_BEDROCK=false with ANTHROPIC_API_KEY.",
        )


def _activate_fallback(reason: str) -> None:
    global _fallback_reason
    if _fallback_reason is None:
        _fallback_reason = reason
        log.warning("Falling back from Bedrock to the Anthropic API: %s", reason)


def provider() -> Provider:
    """The provider calls go to right now. Raises ``MissingSettingError`` naming what is missing."""
    s = get_settings()
    if _fallback_reason is not None:
        return "anthropic"
    if not s.use_bedrock:
        if "anthropic" not in _client_overrides:
            _check_config("anthropic", s)
        return "anthropic"
    if "bedrock" in _client_overrides:
        return "bedrock"
    try:
        _check_config("bedrock", s)
    except MissingSettingError as exc:
        if s.anthropic_api_key:
            _activate_fallback(str(exc))
            return "anthropic"
        raise
    return "bedrock"


def _client(p: Provider) -> Any:
    if p in _client_overrides:
        return _client_overrides[p]
    with _client_lock:
        if p not in _clients:
            s = get_settings()
            _check_config(p, s)
            if p == "anthropic":
                _clients[p] = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=120.0)
            else:
                kwargs: dict[str, Any] = {"aws_region": s.aws_region, "timeout": 120.0}
                if s.aws_access_key_id and s.aws_secret_access_key:
                    kwargs.update(aws_access_key=s.aws_access_key_id, aws_secret_key=s.aws_secret_access_key)
                    if s.aws_session_token:
                        kwargs["aws_session_token"] = s.aws_session_token
                else:
                    kwargs["api_key"] = s.aws_bearer_token_bedrock
                _clients[p] = anthropic.AnthropicBedrockMantle(**kwargs)
        return _clients[p]


def _model_id(p: Provider, model: str) -> str:
    return bedrock_model_id(model) if p == "bedrock" else model


# ---------------------------------------------------------------------------
# JSON schema checking (a small subset of JSON Schema; enough for our strict schemas)
# ---------------------------------------------------------------------------

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def schema_errors(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Errors for ``value`` against ``schema``: type, enum, const, properties, required,
    additionalProperties, items, minItems, maxItems, minimum, maximum, minLength, maxLength, anyOf."""
    errs: list[str] = []
    if "anyOf" in schema:
        if all(schema_errors(value, sub, path) for sub in schema["anyOf"]):
            errs.append(f"{path}: matches no anyOf branch")
        return errs
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = False
        for name in types:
            py = _TYPES.get(name, ())
            if isinstance(value, bool) and name in ("integer", "number"):
                continue
            if isinstance(value, py):
                ok = True
        if not ok:
            return [f"{path}: expected {t}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in {schema['enum']}")
    if "const" in schema and value != schema["const"]:
        errs.append(f"{path}: expected {schema['const']!r}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errs.append(f"{path}: unexpected {key!r}")
        for key, sub in props.items():
            if key in value:
                errs.extend(schema_errors(value[key], sub, f"{path}.{key}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errs.extend(schema_errors(item, schema["items"], f"{path}[{i}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errs.append(f"{path}: longer than {schema['maxLength']}")
    return errs


# ---------------------------------------------------------------------------
# Calls
# ---------------------------------------------------------------------------


def text_part(text: str) -> ContentPart:
    return {"type": "text", "text": text}


def image_part(data: bytes, media_type: str = "image/jpeg") -> ContentPart:
    import base64

    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode(),
        },
    }


def _meter(response: Any, model: str, p: Provider, run_id: str | None) -> float:
    usd = cost_from_usage(model, _get(response, "usage"), bedrock=(p == "bedrock"))
    record_cost(run_id, usd)
    return usd


def _first_text(response: Any) -> str | None:
    for block in _get(response, "content") or []:
        if _get(block, "type") == "text":
            return _get(block, "text")
    return None


def complete_json(
    *,
    tier: Tier,
    system: str,
    user: list[ContentPart],
    schema: dict[str, Any],
    run_id: str | None = None,
    max_tokens: int = 1024,
    effort: str | None = None,
) -> dict[str, Any]:
    """One Claude call that must return JSON matching ``schema`` (an object schema).

    ``max_tokens`` covers thinking plus the answer; on a ``max_tokens`` stop the retry doubles it.
    ``effort`` defaults per tier (``LLM_EFFORT_FAST`` / ``LLM_EFFORT_REASONING``).
    Raises ``LLMOutputError`` when two attempts both fail validation, ``LLMError`` on provider errors,
    ``MissingSettingError`` when credentials are missing.
    """
    s = get_settings()
    p = provider()
    model = model_for(tier, s)
    effort = effort or (s.llm_effort_fast if tier == "fast" else s.llm_effort_reasoning)
    api_schema = anthropic.transform_schema(schema)
    tokens = max_tokens
    last_problem = ""
    for attempt in (1, 2):
        params: dict[str, Any] = {
            "model": _model_id(p, model),
            "max_tokens": tokens,
            # Stable system prompt with a cache breakpoint; repeated scanner prompts read it back.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": user}],
            "output_config": {"format": {"type": "json_schema", "schema": api_schema}, "effort": effort},
        }
        try:
            response = _client(p).messages.create(**params)
        except MissingSettingError:
            raise
        except anthropic.AnthropicError as exc:
            raise LLMError(f"{p} call to {model} failed: {exc}") from exc
        _meter(response, model, p, run_id)
        stop = _get(response, "stop_reason")
        text = _first_text(response)
        if stop == "refusal":
            last_problem = "the model declined (stop_reason=refusal)"
        elif text is None:
            last_problem = f"no text block (stop_reason={stop})"
        else:
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                last_problem = f"invalid JSON ({exc}; stop_reason={stop})"
            else:
                errors = schema_errors(data, schema)
                if not errors:
                    return data
                last_problem = "; ".join(errors[:5])
        if stop == "max_tokens":
            tokens *= 2
        if attempt == 1:
            log.info("complete_json retry (%s): %s", model, last_problem)
    raise LLMOutputError(f"{model} did not return valid JSON after a retry: {last_problem}")


async def acomplete_json(**kwargs: Any) -> dict[str, Any]:
    """``complete_json`` for async callers (runs in a worker thread)."""
    return await asyncio.to_thread(complete_json, **kwargs)


# ---------------------------------------------------------------------------
# LangChain (Deep Agents)
# ---------------------------------------------------------------------------


def _metering_callback(model: str, run_id: str | None, bedrock: bool) -> Any:
    from langchain_core.callbacks import BaseCallbackHandler

    class CostMeteringCallback(BaseCallbackHandler):
        """Adds the cost of every chat model call to the run, like ``complete_json`` does."""

        def __init__(self) -> None:
            self.model, self.run_id, self.bedrock = model, run_id, bedrock

        def on_llm_end(self, response: Any, **kwargs: Any) -> None:
            try:
                for gens in response.generations:
                    for gen in gens:
                        um = getattr(getattr(gen, "message", None), "usage_metadata", None)
                        if not um:
                            continue
                        details = um.get("input_token_details") or {}
                        read = details.get("cache_read") or 0
                        w5 = details.get("ephemeral_5m_input_tokens") or 0
                        w1 = details.get("ephemeral_1h_input_tokens") or 0
                        if not (w5 or w1):
                            w5 = details.get("cache_creation") or 0
                        # LangChain's input_tokens includes cached tokens; the API's does not.
                        uncached = max(0, (um.get("input_tokens") or 0) - read - w5 - w1)
                        usd = estimate_cost_usd(
                            self.model,
                            input_tokens=uncached,
                            output_tokens=um.get("output_tokens") or 0,
                            cache_read_tokens=read,
                            cache_write_5m_tokens=w5,
                            cache_write_1h_tokens=w1,
                            bedrock=self.bedrock,
                        )
                        record_cost(self.run_id, usd)
            except Exception as exc:  # noqa: BLE001 - metering must not break the agent
                log.warning("cost metering failed: %s", exc)

    return CostMeteringCallback()


def get_chat_model(
    tier: Tier, *, run_id: str | None = None, max_tokens: int = 8192, **kwargs: Any
) -> BaseChatModel:
    """A LangChain chat model for the tier on the active provider, metered like ``complete_json``."""
    s = get_settings()
    p = provider()
    model = model_for(tier, s)
    cb = _metering_callback(model, run_id, bedrock=(p == "bedrock"))
    if p == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, api_key=s.anthropic_api_key, max_tokens=max_tokens, callbacks=[cb], **kwargs
        )
    from langchain_aws import ChatAnthropicMantle

    params: dict[str, Any] = {
        "model": bedrock_model_id(model),
        "region_name": s.aws_region,
        "max_tokens": max_tokens,
        "callbacks": [cb],
    }
    if s.aws_access_key_id and s.aws_secret_access_key:
        params.update(aws_access_key_id=s.aws_access_key_id, aws_secret_access_key=s.aws_secret_access_key)
        if s.aws_session_token:
            params["aws_session_token"] = s.aws_session_token
    elif s.aws_bearer_token_bedrock:
        params["bedrock_api_key"] = s.aws_bearer_token_bedrock
    params.update(kwargs)
    return ChatAnthropicMantle(**params)


# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------


def _ping(p: Provider, tier: Tier) -> None:
    model = model_for(tier)
    response = _client(p).messages.create(
        model=_model_id(p, model),
        max_tokens=64,
        messages=[{"role": "user", "content": "Reply with the word OK."}],
        output_config={"effort": "low"},
    )
    _meter(response, model, p, None)


def warm_up(tiers: tuple[Tier, ...] = ("fast", "reasoning")) -> None:
    """Open connections and confirm model access with one tiny call per tier.

    Raises ``MissingSettingError`` naming the missing variable(s), or ``LLMError`` if the provider
    rejects the call. A Bedrock failure falls back to the Anthropic API when ``ANTHROPIC_API_KEY`` is set.
    """
    s = get_settings()
    p = provider()
    for tier in tiers:
        try:
            _ping(p, tier)
        except MissingSettingError:
            raise
        except Exception as exc:
            if p == "bedrock" and s.anthropic_api_key:
                _activate_fallback(f"Bedrock warm-up failed for {model_for(tier)}: {exc}")
                p = "anthropic"
                try:
                    _ping(p, tier)
                except MissingSettingError:
                    raise
                except Exception as exc2:
                    raise LLMError(
                        f"warm-up failed on the Anthropic API for {model_for(tier)}: {exc2}"
                    ) from exc2
            else:
                raise LLMError(f"warm-up failed on {p} for {model_for(tier)}: {exc}") from exc
    log.info("LLM warm-up ok on %s (%s)", p, ", ".join(model_for(t) for t in tiers))
