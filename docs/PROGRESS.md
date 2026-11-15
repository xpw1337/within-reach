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
| 2026-11-14 | Photon 2.0: calls stay on Twilio but go through the Photon number over SIP; iMessage alerts, role follow-ups and the briefing text through Photon's REST API; migration 0005 adds dispatch_channel 'imessage'. |
| 2026-11-14 | Photon messaging: keep staff texts with the ungated staff alert, the stand-down text on release, and the late-reply notice. Shared iMessage line (the free plan cannot buy dedicated lines); each receiving phone texts the line once before the demo. |
| 2026-11-14 | Live roles and ranking (team lead, landed in e51ae85): with an AED route for the camera the first helper accept is the AED runner and the second goes to the person; with no AED route the first accept goes to the person. Waves rank nearest to the camera first. A staff accept means "go to the person" (status only, no helper role). |
| 2026-11-14 | Live demo building: Rabinowitz Hall, Princeton (Matterport `P3S6VUTP3qB`), loaded as `DEMO-RABINOWITZ` and kept out of the census headline, rankings and report (d18e318, docs/NEXT.md section 2a). |
| 2026-11-15 | No desk confirm (team lead): `REQUIRE_CONFIRM=false` in `.env` makes every collapse the camera reports go ahead right after the 5 s voice check, found down included (responders and the 911 briefing, no CONFIRM tap). The spec default `true` is kept in `.env.example`. The desk keeps a False alarm button on `/live`. This departs from spec section 3 and section 16 ("a human confirms before strangers"). |
| 2026-11-15 | 3D route (team lead): treat GPS as accurate. The 3D walk starts at the scan point nearest the phone (no accuracy limit) and follows the phone's GPS as the helper walks. The floor plan's own GPS start in the app keeps its limits. |
| 2026-11-14 | Supabase: hosted project created. Root `.env` uses the new key format: the publishable key as `SUPABASE_ANON_KEY`, the secret key as `SUPABASE_SERVICE_ROLE_KEY` (supabase-py 2.34 accepts both). `SUPABASE_DB_URL` is the Session pooler string (the direct host is IPv6 only). |

## Subtask status

Legend: done = pushed and verified offline; partial = pushed, more to do; -- = not started.

| ID | Status | Notes |
|---|---|---|
| 1.1 | done | 18d95c7, 484e7e0 |
| 1.2 | done offline | 5d41e4a (adds 0004_run_cost.sql). Realtime check needs the hosted project |
| 1.3 | done offline | a6e3940 |
| 1.4, 1.5, 1.8 | blocked | need CoStar dataset access |
| 1.6 | done | 30aae3b |
| 1.7 | done offline | e5468ab, 866f50d, bulk.py. One real building needs dataset + keys |
| 2.1 to 2.8 | done offline | a376a6b to 3ef0f03; follow-ups 0abdddd, ab9c45a (exit signs as exits, red fraction over reachable positions, placement stays in the connected part with the equipment) |
| 3.1 to 3.8 | done offline | 0629313 to 71fb735; follow-ups a085f76, 3dc92bb, 07638bd (first ring) |
| 4.1 to 4.5, 4.7 | done offline | 4bbb297 to 1451d7a; follow-up 884586d (approved scripts, event payloads, call_sid) |
| 4.6, 4.8 | partial | d2de5d7 (calls over Photon SIP). Real calls and collapse-to-first-ring need Twilio credentials, a Photon number and a human |
| 4.9 | send verified | 8a92ce4 (Photon iMessage alerts, follow-ups, replies, webhook). 2026-11-14: a real text through `PhotonMessenger` on the shared line reached the team lead's phone (API call 1.43 s; receipt confirmed by the team lead). Inbound replies are not verified yet: they need the tunnel, the webhook destination and its secret; steps in agent/README.md |
| 5.1 to 5.3 | done offline | 2af4e8d to 53d7973, 7821284. Live webcam steps in vision/README.md |
| 5.4 | code done | 0ec1961. Six clips need humans |
| 5.5 to 5.8 | done offline | 3a741e9 to 6285bf1, 2d27b2f (adopt seeded responder by phone). Device steps in mobile/README.md |

Hosted Supabase, 2026-11-14:
- Migrations 0001 to 0004 applied: 17 tables, Realtime on the 7 spec tables, 4 buckets.
- `data.load --fallback` run twice: 1 building, 33 sweeps, 6 assets, 1 camera, no duplicates (1.3 verified).
- seed.sql: 8 fictional responders.
- Realtime: an agent_events insert arrived in 0.32 s on a subscription made with the anon (publishable) key (1.2 verified).
- `census.cli rerun --mode pipeline` on the fallback building: 198 coverage rows (current and proposed), 1 score, 2 fixes, 2 proposed assets, 3 documents (owner letter used the template: no model keys), 3 camera routes, 35 console events.

Full Python suite on main: 422 passed, 2 skipped without the vision extra (2026-11-14, at ad79cce). Dashboard: 44 vitest tests pass; `tsc --noEmit` is clean after `npx next typegen` (PageProps and LayoutProps are generated types). Mobile: `npm run typecheck` is clean; `npm run check:georef` needs Node 22.18 or later (it imports TypeScript): on Node 22.13 run it with `--experimental-strip-types`, and all checks pass.

Teammate commits d18e318 to ad79cce (2026-11-14): Rabinowitz demo building through the Matterport Model API (`data/matterport.py`, needs `MATTERPORT_API_KEY` and `MATTERPORT_API_TOKEN`), the roles and ranking change above, AED pickup and AED help milestones, and the mobile floor plan, step-tracked dot and on-site calibration. Open demo-building to-dos D3 to D6 are in docs/NEXT.md section 2a.

Contract fix 2026-11-14: `camera_routes.directions` excludes the distance (spec section 3 template adds it).

Dashboard on Vercel, 2026-11-14: project `within-reach` on the team lead's Vercel account, production https://within-reach-nu.vercel.app (built from `dashboard/`, `vercel.json` sets the framework). Production env has only the three public values (Supabase URL, publishable key, Matterport SDK key); no `NEXT_PUBLIC_AGENT_URL` yet, so desk actions on the deployed `/live` need the tunnel first. `mobile/.env` points "View route in 3D" at it. The team lead added `within-reach-nu.vercel.app` to the Matterport SDK key's allowed domains; after that the deployed route page loaded the Rabinowitz model in about 4 s at phone size (430x932, headless Chrome) and Next moved it to point 3 of 4 (2026-11-14). Not yet opened from the app on a real phone. Checked locally: the SDK loads the Rabinowitz model with the key on localhost in about 3 s, all 66 SDK sweep ids equal `twin_nodes.sweep_id`, and `Sweep.moveTo` works.

Privacy, open: the publishable key can read every `responders` row including phone numbers (two real numbers on 2026-11-14), and the key ships in the app and the deployed dashboard. Fixing it is a policy change (needs the team lead's approval).

## Before going on stage

- Which phone rings: staff are never called (they get the ungated staff alert and are left out of the waves), so the ringing responder phone must be a non-staff callable responder (teammate B, public). Waves are nearest first to the camera (e51ae85). With an AED route for the camera, the first accept is the AED runner and the second goes to the person; with no AED route the first accept goes to the person and there is no runner. Both moments on stage need two real phones that accept in that order.
- Move `DISPATCH_SIM_NUMBER` to a different teammate's phone than the responder phone, or the briefing call lands as call waiting.
- Seeded responders go stale 10 minutes after `last_seen_at`: refresh them (re-run the seed) right before the demo.
- Demo on Rabinowitz Hall: the laptop webcam plays the building's camera `cam-atrium-1` (`CAMERA_ID=cam-atrium-1` in `.env`, read by both the agent and vision/). `supabase/seed_demo.sql` puts the eight responders and a caller of record on that building; run it, then seed.local.sql. Checked on the hosted DB 2026-11-14: staff alert to teammate A and seeded security; wave 1 is teammate B (the team lead's phone, called, 20 m), then three app-only responders; wave 2 the two outdoor responders (inside this building's 500 m geofence). To test on the fallback building again, run seed.sql and set `cam-lobby-1`.
- Rabinowitz still lacks an EMS door (the briefing says "EMS entrance not mapped") until D3 is done.

## Waiting on a person

- Photon is set up for solo testing (values only in the untracked `.env` and `supabase/seed.local.sql`): a voice-enabled number with the default SIP Voice profile and MD5 outbound; the team lead's phone is on the shared iMessage line and plays teammate B (public, callable: it gets the responder call), the caller of record and the sim-911 dispatcher. That phone has opted in and received a real test text. Still needed: a Twilio account (it runs the calls), and the webhook destination once the tunnel exists. Swap the dispatcher to a teammate's phone before the real demo.

- Bedrock model access for Sonnet 5.5 and Haiku 5.5 (access-controlled), or an Anthropic API key.
- Someone to check the occupancy factors against the ICC text of IBC 2021 Table 1004.5.
- Anthropic API key or AWS Bedrock credentials (AWS also covers Polly).
- Twilio account (4.6), CoStar dataset access (1.4, 1.5, 1.7, 1.8).
- Recording the six vision clips (5.4); a real phone for the mobile checks.
- `mobile/.env` with the four `EXPO_PUBLIC_*` values (Expo reads it from mobile/, not the root); `EXPO_PUBLIC_AGENT_URL` is the tunnel URL.
