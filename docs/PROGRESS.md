# Build progress (coordinator checkpoint)

Updated by the coordinator as lanes report. The source of truth for what is done is `git log origin/main`: every commit starts with its subtask ID, and partial commits end with a `Next:` line saying what remains.

## How to resume after an interruption

1. `git fetch && git log --oneline origin/main` shows which subtasks landed.
2. `git log -1 --format=%B <last commit of a lane>` shows its `Next:` line.
3. Work that was not pushed yet may still sit in a local agent worktree: `git worktree list` (under `.claude/worktrees/`). Check `git status` there before discarding anything.
4. Restart a lane with the prompt in `docs/LANES.md` ("How to start an agent"), plus the decisions below.

## Decisions confirmed by the team lead

| Date | Decision |
|---|---|
| 2026-11-14 | One coordinator runs all five lanes in parallel; Agent 5 is split into a vision half and a mobile half. |
| 2026-11-14 | Every `*_s` column is one-way walking seconds (CONTRACTS section 1). AED times are shown as round trip (2x) only through the thresholds helpers. |
| 2026-11-14 | `propose_fix(building_id, asset_type="aed") -> str` added to CONTRACTS section 4. |
| 2026-11-14 | Speaker scripts: spec section 3 wording verbatim, with each em-dash replaced by a comma. |
| 2026-11-14 | Supabase: the team lead is creating a hosted project; keys go in the untracked root `.env`, plus `SUPABASE_DB_URL` for applying migrations. |

## Subtask status

Legend: done = pushed and verified offline; partial = pushed, more to do; -- = not started.

| ID | Status | Notes |
|---|---|---|
| 1.1 | done | 18d95c7 (types, lock), 484e7e0 (config, db, events, thresholds, geo, llm) |
| 1.2 | done offline | 5d41e4a. Realtime check needs the hosted project |
| 1.3 | done offline | a6e3940. Load into the hosted project pending keys |
| 1.4, 1.5, 1.8 | blocked | need CoStar dataset access |
| 1.6, 1.7 | -- | 1.7 offline part only until the dataset arrives |
| 2.1 to 2.5 | done offline | a376a6b, 6f3d0ac (IBC 2021 Table 1004.5, unverified), 2d40124, 8b4122b, 00a816d |
| 2.6 to 2.8 | -- | |
| 3.1, 3.2 | done offline | 0629313, 14ce667 |
| 3.3 to 3.8 | -- | |
| 4.1 | done | 4bbb297 |
| 4.2 to 4.5 | -- | 4.6 needs Twilio; 4.7 needs 2.8 |
| 5.1, 5.2 | done | 2af4e8d, bc7ad29 |
| 5.3, 5.4 | -- | 5.4 clips need humans |
| 5.5 to 5.8 | done offline | 3a741e9, 8fa3349, a66581d, 6285bf1. Device steps in mobile/README.md. Follow-up: adopt seeded responder by phone |

Contract fix 2026-11-14: `camera_routes.directions` excludes the distance (spec section 3 template adds it).

## Waiting on a person

- Hosted Supabase project keys in `.env` (team lead, in progress).
- Anthropic API key or AWS Bedrock credentials (AWS also covers Polly).
- Twilio account (4.6), CoStar dataset access (1.4, 1.5, 1.7, 1.8).
- Recording the six vision clips (5.4); a real phone for the mobile checks.
- `mobile/.env` with the four `EXPO_PUBLIC_*` values (Expo reads it from mobile/, not the root); `EXPO_PUBLIC_AGENT_URL` is the tunnel URL.
