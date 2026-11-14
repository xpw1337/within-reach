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
| 2026-11-14 | Exit maps count `exit_sign` assets as exits (labeled approximation). red_frac excludes positions with no route. gap_score weights AED 0.5, extinguisher 0.25, exit 0.25 kept. |
| 2026-11-14 | Live: wording approved for unsafe_stay_back, cardiac_aed_arrived, all_clear; no-AED cardiac drops the AED sentence; naloxone location from the asset label; staff alerts ungated; late unsafe releases dispatches. |
| 2026-11-14 | Supabase: the team lead is creating a hosted project; keys go in the untracked root `.env`, plus `SUPABASE_DB_URL` for applying migrations. |

## Subtask status

Legend: done = pushed and verified offline; partial = pushed, more to do; -- = not started.

| ID | Status | Notes |
|---|---|---|
| 1.1 | done | 18d95c7, 484e7e0 |
| 1.2 | done offline | 5d41e4a (adds 0004_run_cost.sql). Realtime check needs the hosted project |
| 1.3 | done offline | a6e3940 |
| 1.4, 1.5, 1.8 | blocked | need CoStar dataset access |
| 1.6 | done | 30aae3b |
| 1.7 | partial | e5468ab, 866f50d. bulk.py held in Agent 1's worktree until a census wiring test is relaxed. Real building needs dataset + keys |
| 2.1 to 2.8 | done offline | a376a6b, 6f3d0ac, 2d40124, 8b4122b, 00a816d, ed563ea, a03cfec, f9f6130, 3ef0f03. Follow-up: exit_sign as exit, red_frac over reachable |
| 3.1, 3.2 | done offline | 0629313, 14ce667 |
| 3.3 to 3.8 | in progress | |
| 4.1 to 4.5, 4.7 | done offline | 4bbb297, b86b69b, 1da8bbd, 1cac1c6, 1451d7a. Signal-inbox graph; event to audio median 2.5 ms locally. Follow-up: approved scripts |
| 4.6, 4.8 | partial | Real Twilio calls and collapse-to-first-ring need credentials and a human |
| 5.1 to 5.3 | done offline | 2af4e8d, 1d6babb, bc7ad29, 1454252, 53d7973. Live webcam steps in vision/README.md |
| 5.4 | code done | 0ec1961. Six clips need humans |
| 5.5 to 5.8 | done offline | 3a741e9, 8fa3349, a66581d, 6285bf1, 2d27b2f. Device steps in mobile/README.md |

Contract fix 2026-11-14: `camera_routes.directions` excludes the distance (spec section 3 template adds it).

## Before going on stage

- Seeded responders go stale 10 minutes after `last_seen_at`: refresh them (re-run the seed) right before the demo.

## Waiting on a person

- Hosted Supabase project keys in `.env` (team lead, in progress), then apply migrations 0001 to 0004.
- Bedrock model access for Sonnet 5.5 and Haiku 5.5 (access-controlled), or an Anthropic API key.
- Someone to check the occupancy factors against the ICC text of IBC 2021 Table 1004.5.
- Anthropic API key or AWS Bedrock credentials (AWS also covers Polly).
- Twilio account (4.6), CoStar dataset access (1.4, 1.5, 1.7, 1.8).
- Recording the six vision clips (5.4); a real phone for the mobile checks.
- `mobile/.env` with the four `EXPO_PUBLIC_*` values (Expo reads it from mobile/, not the root); `EXPO_PUBLIC_AGENT_URL` is the tunnel URL.
