# Within Reach: codebase architecture

This document turns the build spec (`CLAUDE.md`) into a concrete codebase design. The spec says *what* to build. This says *where each piece lives, who owns it, and how the pieces talk*. Implementers read, in order:

1. `CLAUDE.md` (the spec, source of truth for behavior)
2. this file (module boundaries and decisions)
3. `docs/CONTRACTS.md` (every interface that crosses a module boundary)
4. `docs/LANES.md` (subtasks for the five implementing agents)
5. the `DESIGN.md` in the folder you own

If this document and the spec disagree, the spec wins. Raise it, do not silently pick one.

## 1. System shape

Two systems share one database and one building map.

```
                     +------------------- CENSUS (offline, agentic) -------------------+
 dataset --data/-->  | census/agent: Deep Agent planner + 5 subagents                  |
                     |   tools (census/tools)  -> thin wrappers: DB io + agent_events  |
                     |   core  (census/core)   -> pure Python: tiling, graph, scoring  |
                     +----------------------------------+------------------------------+
                                                        | service-role writes
                                                        v
   dashboard/ (Next.js)  <--- read + Realtime ---   Supabase   --- read + Realtime --->  mobile/ (Expo)
        |                                    (Postgres, Storage)                            |
        | HTTP commands                                 ^                                   | HTTP accept/decline
        v                                               | service-role writes               v
                     +----------------------------------+------------------------------+
 vision/ --POST----> | agent/: FastAPI + deterministic LangGraph live graph            |
 /events             |   speaker (pre-rendered audio), Twilio, timers, checkpointer    |
                     +-----------------------------------------------------------------+
```

Three rules define the whole integration model:

1. **Supabase is the read bus.** Dashboard and mobile read tables and subscribe to Realtime with the anon key. They never compute census results themselves.
2. **FastAPI is the command bus.** Anything that changes workflow state (start a run, confirm an incident, accept a dispatch) is an HTTP call to `agent/`. Only Python holds the service-role key.
3. **Vision is an HTTP client only.** `vision/` posts events to `agent/` and imports nothing else from the repo, so it can run unchanged on a Raspberry Pi.

One documented exception to rule 2: the mobile app upserts its own `responders` row (profile, consents, `last_lat/lng`, `last_seen_at`) straight to Supabase. No workflow depends on that write happening synchronously.

## 2. Repo layout

```
within-reach/                 (this repo root)
  CLAUDE.md                   build spec
  README.md
  .env.example  .gitignore  pyproject.toml
  docs/
    ARCHITECTURE.md           this file
    CONTRACTS.md              cross-module interfaces
    LANES.md                  subtasks for the five implementing agents
  shared/                     Python: config, db, llm, thresholds, event emitters  (addition to spec §5)
  data/                       Python: dataset adapters + loader; data/README.md describes the real dataset
  census/                     Python: core math, tools, Deep Agent, run orchestration
  vision/                     Python: live person-down detection (standalone)
  agent/                      Python: FastAPI app, live LangGraph graph, Twilio, speaker
  dashboard/                  Next.js + Tailwind
  mobile/                     Expo responder app
  supabase/                   migrations + seed
  demo/                       fallback building, backup recordings, Peri materials
```

Every code folder has a `DESIGN.md`: the file-level plan, function signatures and acceptance checks for that folder. (`data/README.md` is reserved for the dataset description required by spec §9.1, which is why the briefs are named `DESIGN.md`.)

## 3. Python package structure

One Python project at the repo root (`pyproject.toml`, Python 3.11+, managed with `uv`). Packages are the top-level folders. Allowed imports only go *down* this list:

```
agent   -> census, data, shared
census  -> data, shared
data    -> shared
shared  -> (third-party only)
vision  -> (third-party only; own config via env)
```

No cycles, no upward imports. `census` must never import `agent`. `vision` must never import any repo package.

### Layering inside census/ (the important one)

```
census/core/     pure functions. Inputs and outputs are plain dataclasses / dicts / numpy.
                 No database, no network, no LLM, no env reads. Fully unit-testable offline.
census/vision/   LLM-backed perception (first pass, verify). Takes images in, returns typed results.
                 Calls shared.llm only. No database.
census/tools/    Thin wrappers: load rows -> call core or vision -> write rows -> emit agent_events.
                 These are the functions handed to the Deep Agent as tools.
census/agent/    Deep Agent wiring: planner prompt, 5 subagent definitions, tool lists.
census/run.py    Run lifecycle: create runs row, budget guard, worker pool, start/stop.
```

This layering is how spec rule 3 ("heavy math lives in plain Python tools, not in the LLM") is enforced structurally: the LLM can only *choose* which tool to call; every number comes out of `census/core`.

### Layering inside agent/

```
agent/main.py        FastAPI app factory, lifespan (warm-up, checkpointer, timer registry)
agent/api/           routers: census.py, handcheck.py, events.py, incidents.py, dispatches.py,
                     twilio.py, simulate.py, config.py
agent/live/          the deterministic graph: state.py, graph.py, nodes/*.py, playbooks.py,
                     timers.py, responders.py
agent/io/            side-effect adapters: speaker.py, tts.py (Polly), telephony.py (Twilio),
                     verify.py (the only LLM call on the live path)
```

`agent/live/` never calls an LLM. The single LLM call (scene verification) lives in `agent/io/verify.py`, runs in a parallel branch, and can only add modifiers or mark the scene unsafe. The path `POST /events -> ingest -> local_first_response -> speaker` contains no network call except the database write, and plays a file that already exists on disk.

## 4. Data ownership

Each table has exactly one writer module. Everyone else reads.

| Table | Writer | Readers |
|---|---|---|
| `buildings`, `twin_nodes`, `panos` | `data/load.py` (census Records/Outside update `occupancy_est`, `vexcel`, `ems_door`, `census_status`, `priority_score`) | all |
| `detections` | `census/tools/scanner.py`; `human_label` by `agent/api/handcheck.py` | dashboard `/handcheck` |
| `assets` | `census/tools/scanner.py` (`detected`), `census/tools/fixer.py` (`proposed`), seed (`manual`) | dashboard, live routes |
| `coverage`, `building_scores` | `census/tools/mapper.py`, `fixer.py` (scenario `proposed`) | dashboard |
| `fixes`, `documents` | `census/tools/fixer.py` | dashboard |
| `runs`, `agent_events` | `census/run.py`, `shared/events.py` | dashboard console |
| `cameras`, `camera_routes` | `census/tools/routes.py` (precompute step) + seed | `agent/live` |
| `responders` | mobile (own row), seed | `agent/live/responders.py`, dashboard |
| `incidents`, `incident_events`, `dispatches` | `agent/live` only | dashboard `/live`, mobile |

Binary objects live in Supabase Storage (buckets in `docs/CONTRACTS.md` §5). Raw panoramas and perspective tiles are a local disk cache (`.cache/`), never uploaded: only equipment crops are kept (spec §9.3 privacy rule).

## 5. Key decisions

| # | Decision | Why |
|---|---|---|
| D1 | Added a `shared/` Python package | `census`, `agent` and `data` all need the same settings, Supabase client, LLM client and thresholds. Without it each lane reinvents them and they drift. This is the one addition to the spec §5 layout. |
| D2 | All LLM calls go through `shared/llm.py` | One place for the Bedrock vs direct API switch, model IDs from env, JSON-schema output handling, and cost metering into `runs.est_cost_usd` (budget guard, spec §9.2). |
| D3 | Thresholds live in `shared/thresholds.py`, served to the UI by `GET /config/thresholds` | Red-zone rules (spec §9.4) must be identical in the Mapper, the Fixer and the heatmap. The dashboard fetches them instead of hardcoding. |
| D4 | `coverage.time_s` is always **one-way walking seconds** | One unit in the table. AED round trip is `2 * time_s`; extinguisher and exit distance is `time_s * WALK_SPEED_MPS`. Conversion happens in `shared/thresholds.py` only. |
| D5 | Dataset access behind a `DatasetAdapter` protocol with a `FallbackAdapter` | The real dataset shape is unknown until inspected (spec §9.1). Everything downstream codes against the protocol and against `demo/fallback/`, so agents 2 to 5 are not blocked on the real dataset. |
| D6 | Live graph checkpointer is SQLite on local disk; timers are in-process asyncio tasks; one uvicorn worker | The live path must run on one laptop on venue Wi-Fi (spec §15). No distributed state. |
| D7 | Live signals are idempotent and state is the source of truth | Confirm taps, vision events, Twilio digits and timer timeouts can race. Each resume carries a typed signal; nodes ignore signals that no longer apply. See `agent/DESIGN.md` for the interrupt strategy and its fallback. |
| D8 | Speaker audio is pre-rendered per camera at seed time into files on local disk (and mirrored to Storage) | Meets "event to voice-check audio < 1 s" with no TTS or LLM on the hot path. |
| D9 | The Deep Agent decides order and exceptions; bulk tiling and first-pass detection run in a worker pool | Spec §9.2. The planner should not make ten thousand tool calls. It dispatches batches, watches results and handles anomalies. |
| D10 | Dashboard and mobile use the anon key with permissive demo policies (`0002_demo_policies.sql`) | Spec §6 "demo auth bypass". Not production security; stated in the README. |
| D11 | 2D SVG heatmap is the primary building view; the Matterport embed is an enhancement behind a feature check | Spec §6: the SVG "always works". No screen may depend on the SDK loading. |

Items that need a human decision before or during the build are listed in `docs/LANES.md` under "Open questions".

## 6. End-to-end flows

### Census: one building

```
data.load            -> buildings, twin_nodes, panos
Records              -> occupancy_est, priority_score            (scan order)
Scanner  tile_pano   -> tiles in .cache/
         first pass  -> detections(status=candidate, verified_by=first_pass)
         verify      -> detections(confirmed|rejected, verified_by=claude), flags blocked_exit
         second view -> triangulate, verified_by=second_pano      (borderline only)
         pin_asset   -> assets(source=detected)
Mapper   build_graph -> networkx graph from twin_nodes
         walking map -> coverage(scenario=current), building_scores
Outside  vexcel      -> buildings.vexcel, buildings.ems_door
Fixer    place_one   -> fixes, assets(source=proposed), coverage(scenario=proposed)
         documents   -> documents(owner_letter, emergency_card, registry_list)
Rank                 -> building_scores.rank across the run
routes (demo bldg)   -> camera_routes + pre-rendered audio
```

Every step emits `agent_events` rows; the console on every dashboard page is a Realtime subscription to that table.

### Live: one incident

```
vision  person_down  -> POST /events
agent   ingest       -> incidents row, status=detected
        local_first_response -> play voice-check file, set first_instruction_at   (< 1 s, no LLM)
        parallel     -> verify (LLM, snapshot) | request_confirm (dashboard) | voice_check timer
        classify     -> false_alarm | unsafe scene | FALL | CARDIAC (+ modifiers)
        gate         -> witnessed: auto after 10 s; found_down: human confirm, 60 s -> 911 briefing only
        fan-out      -> announce loop | dispatch_responders (waves) | brief_911 | notify_police | alert_staff | fall_911_timer
        guide        -> CPR coaching loop, switches on milestones (cpr_started, aed_arrived)
        handoff      -> Utstein-style card from incidents timestamps
```

Dashboard `/live` and the mobile app render entirely from `incidents`, `incident_events` and `dispatches` via Realtime, and send commands through the API in `docs/CONTRACTS.md` §2.

## 7. Testing strategy

- `census/core`: unit tests on the fallback building and on tiny synthetic graphs (known shortest paths, known best placement). No network.
- `agent/live`: graph tests with fake speaker, fake telephony and a fake clock, one test per branch of the spec §3 decision tree, plus race tests (confirm vs timeout).
- `vision`: recorded clips in `demo/clips/` replayed through the detector: fall triggers, sitting does not, raised hand registers responsive.
- Integration: `POST /simulate/cardiac` end to end against a local Supabase with the fallback building seeded.
- Never in tests: real Twilio calls, real 911, real spend. Telephony and LLM are behind interfaces with fakes.

## 8. Non-negotiables carried into the code structure

- Never call real 911: `agent/io/telephony.py` refuses any destination that is not `DISPATCH_SIM_NUMBER` or a seeded `callable` responder, and rejects `911` explicitly.
- No face crops: `census/vision` returns equipment bounding boxes only; the crop writer in `census/tools/scanner.py` is the only code that writes to the `crops` bucket.
- "Visible in the scan": user-facing strings for missing equipment come from one constants module per frontend (`dashboard/lib/copy.ts`, document templates in `census/core/docs.py`), so the wording cannot drift.
- Only real numbers: the UI renders numbers from `runs`, `building_scores`, `fixes` and hand-check counts. No hardcoded statistics in components.
- Owner letters are drafts: there is no send path in the codebase.
