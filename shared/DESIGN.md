# shared/ design

Small Python package used by `data`, `census` and `agent`. It imports third-party libraries only. Keep it boring: no business logic.

## Files

| File | Purpose |
|---|---|
| `config.py` | `Settings` (pydantic-settings) with every variable in `.env.example`, typed, with the spec defaults. `get_settings()` is cached. No other module reads `os.environ`. |
| `db.py` | `get_db()` service-role Supabase client; `upload()` to Storage; small helpers `fetch_one`, `fetch_all`, `upsert` that raise on error instead of returning it. |
| `llm.py` | The only place that talks to the LLM provider. |
| `events.py` | `emit_agent_event`, `emit_incident_event`. |
| `thresholds.py` | Red-zone rules from spec §9.4, the single source for zones. |
| `types.py` | Dataclasses shared across packages: `BuildingRecord`, `TwinNode`, `PanoRef`, `VexcelInfo`, `Ray`, `Route`, `Placement`, `BuildingScore`, `CoverageByType`, `Flags`. |
| `geo.py` | `haversine_m`, geofence check. Used by census Outside and live responder selection. |

Signatures are fixed in `docs/CONTRACTS.md` §4.

## llm.py

- `tier="fast"` maps to `CLAUDE_MODEL_FAST`, `tier="reasoning"` to `CLAUDE_MODEL_REASONING`.
- `USE_BEDROCK=true` routes through Amazon Bedrock. Look up the current Bedrock model IDs for the configured models; do not guess them. If the Bedrock call fails at warm-up, fall back to the direct API when `ANTHROPIC_API_KEY` is set and log a warning once.
- `complete_json` forces schema-valid JSON (tool-use or structured output, whichever the current SDK supports), retries once on invalid output, and returns a dict.
- Cost metering: every call computes cost from the usage in the response and a price table in this file, then adds it to `runs.est_cost_usd` when `run_id` is given. The price table must be filled from the provider's current pricing page and carries a comment with the date checked.
- `get_chat_model` returns a LangChain chat model for Deep Agents, with a callback that meters cost the same way.
- A `batch_complete_json(requests)` helper for the Message Batches API is optional; add it only if the overnight run needs it (spec §6).
- LangSmith tracing is switched on by env (`LANGSMITH_TRACING`), nothing to code beyond passing it through.

## events.py

- Inserts one row and returns. Failures are logged and swallowed: an event write must never break a census step or the live path.
- `emit_incident_event` must not block the live hot path: it is fire-and-forget (background task) when called from async code.

## thresholds.py

```python
def limit_seconds(asset_type) -> float
    # aed:          AED_ROUNDTRIP_TARGET_S / 2
    # extinguisher: EXT_MAX_TRAVEL_M / WALK_SPEED_MPS
    # exit:         EXIT_MAX_TRAVEL_M / WALK_SPEED_MPS
def zone(asset_type, time_s) -> "green" | "yellow" | "red" | "unknown"
    # None -> "unknown" (no asset visible in the scan); > limit -> red;
    # > YELLOW_FRACTION * limit -> yellow; else green
YELLOW_FRACTION = 2 / 3      # display choice only, not a guideline
```

Each default carries a comment naming its source and the word "unverified" until someone checks it (spec §20).

## Acceptance

- `python -c "from shared.config import get_settings; get_settings()"` works with only `.env.example` values filled for Supabase.
- Unit tests for `thresholds.zone` on the boundary values.
- `llm.warm_up()` succeeds on both provider paths, or fails with a message that names the missing variable.
