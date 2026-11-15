# Work packages

The build is split into five workstreams with disjoint folders, so they can be built in parallel without touching each other's files. Each workstream has an ordered list of subtasks with a done check. Checkpoint times are in spec §10.

| Workstream | Name | Owns | Spec lane |
|---|---|---|---|
| 1 | Foundation, Data, Scanner | `shared/`, `supabase/`, `pyproject.toml`, `demo/fallback/`, `data/`, `census/vision/`, `census/core/tiling.py`, `census/core/triangulate.py`, `census/tools/scanner.py`, `census/tools/bulk.py` | A |
| 2 | Census brain | the rest of `census/` (`core/`, `tools/`, `agent/`, `run.py`, `cli.py`) | B |
| 3 | Dashboard | `dashboard/` | C |
| 4 | Live agent | `agent/` | D |
| 5 | Vision and Mobile | `vision/`, `mobile/`, `demo/clips/`, `demo/frames/` | D |

## Start order

**Workstream 1 does subtasks 1.1 to 1.3 first** (about an hour of work). Workstreams 2, 3 and 4 need them. Workstream 5 can start at the same time as workstream 1. To start all five at once, workstreams 2 to 4 begin with the subtasks marked "no dependency" and code against `docs/CONTRACTS.md` until 1.3 lands. Each workstream reads `docs/ARCHITECTURE.md`, `docs/CONTRACTS.md`, the ground rules, its section below and the `DESIGN.md` files in the folders it owns, does its subtasks in order, and commits after each one with its ID in the message (for example `1.3: fallback building and loader`).

## Ground rules

1. Touch only the folders you own. If you need something changed elsewhere, ask its owner; do not edit it yourself.
2. Code against `docs/CONTRACTS.md` and the fallback building, not against another workstream's unfinished code. If a contract is wrong or missing, stop and ask; a contract change must update `docs/CONTRACTS.md` in the same commit.
3. Ask the team lead before changing the schema, the triage logic (spec §3), the architecture or the demo script (spec rule 6).
4. Commit after each working subtask. Keep `main` runnable. Pull and rebase before each push.
5. No invented numbers anywhere, including placeholder UI text and docs. Use `--` until real data exists.
6. Look up current library APIs before coding against them (`deepagents`, LangGraph interrupts, Supabase clients, Bedrock model IDs, Expo SDK modules). Do not code from memory.
7. No em-dashes in code, comments, docs or commit messages.
8. Never place a real 911 call, never commit secrets or real phone numbers, never store face crops.
9. Report honestly: what works, what was verified and how, what was not.

---

## Workstream 1: Foundation, Data, Scanner

Read: `shared/DESIGN.md`, `supabase/DESIGN.md`, `demo/DESIGN.md`, `data/DESIGN.md`, the Scanner parts of `census/DESIGN.md`.

| ID | Subtask | Done when |
|---|---|---|
| 1.1 | Python project and `shared/`: `uv sync` works from the root `pyproject.toml`; implement `config`, `db`, `events`, `thresholds`, `types`, `geo`, and `llm` (both provider paths, cost metering). | `shared` unit tests pass; `llm.warm_up()` works or names the missing variable. |
| 1.2 | Supabase: apply `0001_init.sql`; write `0002_demo_policies.sql`, `0003_storage.sql`, `seed.sql`. | A fresh project can be built from the migrations; an `agent_events` insert arrives on a Realtime subscription with the anon key. |
| 1.3 | Fallback building and loader: hand-build `demo/fallback/building.json` to the `demo/DESIGN.md` requirements; `data/adapter.py`, `data/fallback.py`, `data/load.py --fallback`. **Unblocks workstreams 2, 3, 4: push and say so.** | Loader fills `buildings`, `twin_nodes`, `panos`, `assets`, `cameras`; running it twice makes no duplicates. |
| 1.4 | Inspect the real dataset and write `data/README.md` answering the six questions in `data/DESIGN.md`. Needs dataset access. | README has a real sample building. If the dataset forces a schema change, stop and ask. |
| 1.5 | Real adapter: `data/costar.py`, loader flags for city, types, limit, ids; lazy `fetch_pano` with the local cache. | 50 real buildings load cleanly twice. |
| 1.6 | Scanner core: `census/core/tiling.py`, `census/core/triangulate.py` with unit tests. | Tests pass offline, including pixel to world-ray on a known example. |
| 1.7 | Scanner perception and tools: `census/vision/` (first pass, verify), `census/tools/scanner.py` (all five tools, duplicate merging, crops to Storage), `census/tools/bulk.py`. | One real building ends with confirmed `assets` rows and crops; no full tiles or faces uploaded. |
| 1.8 | CP0 first test on 50 to 100 commercial scans (gyms and offices first). | A short report with real hit rates per type, seconds and dollars per building, and 30 detections queued for hand-check. |

## Workstream 2: Census brain

Read: `census/DESIGN.md`, `shared/DESIGN.md`. Works on the fallback building (its assets are seeded, so no Scanner needed) until workstream 1 delivers 1.7.

| ID | Subtask | Done when |
|---|---|---|
| 2.1 | Graph and maps (no dependency): `census/core/graph.py` with `build_graph`, `walking_time_map`, `shortest_route`, stairs-only detection. | Unit tests on synthetic graphs with known answers pass, including disconnected graphs. |
| 2.2 | Scoring and rank (no dependency): `core/scoring.py`, `core/occupancy.py`. | Tests pass; the occupancy factor table is marked unverified. |
| 2.3 | Placement (no dependency): `core/placement.py` greedy `place_one`. | On a test graph it finds the known best sweep and returns before/after stats. |
| 2.4 | Mapper and Records tools: `tools/mapper.py`, `tools/records.py` writing `coverage`, `building_scores`, `occupancy_est`, with `agent_events`. Needs 1.3. | The fallback building has current coverage and a score row. |
| 2.5 | Fixer and documents: `tools/fixer.py`, `core/docs.py` (owner letter with the number checker, deterministic emergency card and registry list). | Fallback building has a `fixes` row, a proposed asset, proposed coverage and three documents containing only measured numbers. |
| 2.6 | Outside and routes: `core/ems_door.py`, `tools/outside.py`, `core/directions.py`, `tools/routes.py`. | `buildings.ems_door` is set with a reason; `camera_routes` exists for `cam-lobby-1` with readable directions. **Tell workstream 4.** |
| 2.7 | Deep Agent: `census/agent/` planner with todo list and five subagents, decisions mirrored to `agent_events`. | `rerun_building(fallback)` produces a console stream that shows a plan, decisions and results. |
| 2.8 | Run lifecycle: `run.py` (start, stop, rerun, budget guard, ranked batches, resume after crash) and `cli.py` (run, rerun, rank, report). | A 20-building run stays inside a small budget, survives one forced error, and `report` prints real counts. |

## Workstream 3: Dashboard

Read: `dashboard/DESIGN.md`. Needs 1.2 and 1.3 for real rows; scaffolding can start at once.

| ID | Subtask | Done when |
|---|---|---|
| 3.1 | Scaffold (no dependency): Next.js + Tailwind + TypeScript, `lib/supabase.ts`, `lib/api.ts` (every endpoint in the contracts), `lib/thresholds.ts`, `lib/copy.ts`, `useRealtimeTable`. | App builds and runs; types generated from the schema. |
| 3.2 | Agent console in the layout: todo checklist, event rows, decision styling, collapse. | A hand-inserted `agent_events` row appears live on every page. |
| 3.3 | Building page, part 1: SVG floor heatmap, floor picker, equipment toggle, asset markers, flags, CoStar facts. | Fallback building renders with correct zone colors from `coverage`. |
| 3.4 | Building page, part 2: current/proposed toggle with the drop-AED animation, fix summary, documents tab with printable card, outside panel, rerun button. | Toggling scenarios animates and the before/after figures match the `fixes` row. |
| 3.5 | City map: Leaflet, city switch, gap toggle, ranked list, run progress, headline from real rows. | Works with one building and with thousands (clustered); shows `--` with no run. |
| 3.6 | Hand-check page. | Labeling 30 crops updates the precision count from the summary endpoint. |
| 3.7 | Live page: incident card, confirm bar with countdown, latency metrics, timeline, responders, EMS door, handoff card, milestone, simulate and reset buttons, route fly-through on the SVG plan. | Follows a simulated incident end to end from Realtime alone. |
| 3.8 | Matterport embed with asset markers and camera fly-through, hidden when the key or model is missing. | Page still works with the SDK blocked. |

## Workstream 4: Live agent

Read: `agent/DESIGN.md`, spec §3, §8, §9.8, §9.10. Needs 1.1 to 1.3; the pure logic in 4.1 needs nothing.

| ID | Subtask | Done when |
|---|---|---|
| 4.1 | Pure logic (no dependency): `live/state.py`, `apply_signal` reducer, `playbooks.py` (spec §3 text verbatim), `responders.py`, `briefing.py`, with unit tests. | Tests cover every branch of the spec §3 tree and the wave and role rules. |
| 4.2 | App skeleton: `main.py`, lifespan, all routers with correct request and response shapes, `/health`, `/config/thresholds`. | Every endpoint in the contracts answers with the right shape. |
| 4.3 | IO adapters: `io/speaker.py`, `io/tts.py` (`render_camera_audio`), `io/telephony.py` with the destination allowlist, `io/verify.py`, each with a fake. | Audio renders for `cam-lobby-1` (after 2.6, or from seeded routes); the 911-refusal test passes. |
| 4.4 | The graph: `live/graph.py`, nodes, `timers.py`, `signals.py`, SQLite checkpointer. Verify LangGraph interrupt semantics first; use the signal inbox fallback if needed. | The 12 tests in `agent/DESIGN.md` pass with fakes and a fake clock. |
| 4.5 | Simulate and reset; thin slice end to end. | `/simulate/cardiac` plays real audio in under 1 s from the event, the dashboard confirm resumes it, a `dispatches` row appears; `/reset` returns to a clean state. |
| 4.6 | Twilio: responder call with digit gather, 911 briefing to `DISPATCH_SIM_NUMBER` spoken twice, hangup on release, tunnel setup notes. Needs account credentials. | A real call to a teammate assigns a role on digit 1; the briefing includes the EMS door. |
| 4.7 | Census and hand-check routers wired to workstream 2's functions (after 2.8). | A run can be started, stopped and rerun from the dashboard. |
| 4.8 | Latency and resilience pass: warm-up, measure event to audio and collapse to first ring, check behavior with the LLM or Twilio unreachable. | Measured numbers recorded in the commit message; the script still plays with the network down. |

## Workstream 5: Vision and Mobile

Read: `vision/DESIGN.md`, `mobile/DESIGN.md`. Vision needs only the `POST /events` contract. Mobile needs 1.2.

| ID | Subtask | Done when |
|---|---|---|
| 5.1 | Vision features (no dependency): `features.py` and tests on synthetic keypoints. | Tests pass. |
| 5.2 | Tracker, detector state machine, `replay.py`. | Replay over a test video prints the expected events. |
| 5.3 | Capture loop, debug overlay, `client.py` with the privacy rules. | Live webcam: collapse posts `person_down` with the right `witnessed`; sitting posts nothing; raised hand posts `responsive`. |
| 5.4 | Tuning set: with a second person, record the six clips in `vision/DESIGN.md` into `demo/clips/` plus a stock frame in `demo/frames/`; tune thresholds. | All clips produce their expected events. |
| 5.5 | Mobile scaffold (no dependency): Expo app, router, Supabase client, profile storage, onboarding with consents and the two required lines. | A new responder row appears in Supabase from a real phone in Expo Go. |
| 5.6 | Home and location: on-duty toggle, foreground location updates. | `last_seen_at` stays fresh while the app is open. |
| 5.7 | Alert flow: Realtime dispatch subscription, alarm and haptics, accept, decline, countdown, arrived, released. | A hand-inserted dispatch alarms the phone; Accept reaches the agent (or a stub) and shows the role. |
| 5.8 | CPR guide: 110 bpm metronome, spec wording, AED steps. | Works with the phone on silent. |
| 5.9 | Stretch, only if everything else is done: Raspberry Pi run of `vision/`. | Measured frame rate reported. |

---

## Integration points

| When | What meets | Check |
|---|---|---|
| CP0 | 1.8 | hit rates decide the pitch lead |
| CP1 | 1.7 + 2.4 to 2.6 + 3.4 | one real building end to end on the building page |
| CP1 | 4.5 + 5.7 | simulate cardiac, audio, confirm, app alert, accept |
| CP2 | 2.8 + 3.5 + 4.7 | 20-building run with the console and city map live |
| CP2 | 4.6 + 5.3 + 2.6 | real collapse, census route in the speaker script, EMS door in the briefing |

## Open questions (need a team decision)

1. **Dataset shape.** Everything in `data/` is provisional until 1.4. If panoramas are not downloadable in bulk, workstream 1 switches to SDK screenshots and the schema may need a change (ask first).
2. **Occupancy factors.** `estimate_occupancy` needs a per-type people-per-area factor with a citable source. Until someone supplies one, `people_at_risk` is labeled an estimate and the table is marked unverified.
3. **Thresholds.** The 180 s AED round trip, the NFPA 10 distance and the exit travel distance are unverified defaults (spec §20). They stay configurable and are labeled approximations in the UI.
4. **Budget.** `CENSUS_BUDGET_USD` must be set by the team before CP3.
5. **Map provider.** Leaflet with OpenStreetMap tiles needs no key and is the default. Mapbox only if someone wants it and has a token.
6. **Speaker location.** Default is the laptop running `agent/`. A Raspberry Pi speaker is a stretch.
7. **Repo visibility.** The GitHub repo starts private. Devpost judging needs it public before submission.
