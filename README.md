# Within Reach

For every spot inside a building, Within Reach measures how far you are from the things that keep you alive: an AED, a fire extinguisher, an exit. An AI agent finds the dangerous gaps and drafts the fix. When a camera sees someone collapse, the same map tells bystanders where the AED is, alerts the nearest responders on their phones, walks the AED runner to the AED and back in a 3D view of the building, and briefs a (simulated) 911 dispatcher.

Built at HackPrinceton Fall 2026 for the CoStar track (Matterport, Vexcel and CoStar data).

## What it does

**Census (offline, agentic).** A LangChain Deep Agent plans the work and delegates to Records, Scanner, Mapper, Outside and Fixer subagents; every decision streams to an on-screen agent console. Plain Python does the math: the Matterport sweep graph becomes a walking graph, multi-source Dijkstra gives walking time from every scan point to the nearest AED, extinguisher and exit, red zones and a gap score rank the building, and a greedy search places one new AED where it most reduces the worst case. The Fixer drafts an owner letter, a 911 registry list and a one-page emergency card (drafts only, never sent).

**Live response (real time, deterministic).** A laptop webcam runs YOLOv8-pose. When someone goes down, a LangGraph state machine (no LLM before the first spoken instruction) does this:

1. The laptop speaker asks "Are you okay? If you can hear me, raise your hand."
2. With no raised hand after 5 s, it is a possible cardiac arrest. The speaker gives hands-only CPR instructions and the AED location from the census map ("14 meters, near the Gothic arcade gate").
3. Responders are alerted nearest first, in waves (app alert over Supabase Realtime, iMessage through Photon, phone calls through Twilio when configured). With an AED mapped for the camera, the first to accept is the AED runner and the second goes to the person. On-site staff get a "go to the person" alert.
4. The simulated 911 dispatcher gets a briefing: type, address, floor and landmark, time since collapse, CPR and AED status, EMS door, callback number.
5. The responder app shows the floor plan with the route. "View route in 3D" opens the Matterport twin, which walks the route at walking pace or follows the responder's steps; "I have the AED" switches to the way back, and the laptop says "The AED is here" when the runner arrives.
6. The dashboard shows the incident, latency, timeline and a Utstein-style handoff card.

## Demo building

The live demo runs in the Julis Romo Rabinowitz Building (Princeton), from its Matterport model. No AED is visible in that scan, so the team placed a demo AED by the Gothic arcade gate. It is labeled "Demo AED (placed by team)" everywhere and is excluded from every census number.

## What we measured

From our own test runs on 2026-11-15:

- After the camera reported a collapse, the voice check played in the same second, and responder alerts went out 5 to 6 s later (the voice check takes 5 s).
- A responder accepted 4 to 8 s after the alert and became the AED runner.
- In a headless browser, "Walk it" walked the 18 m route to the AED in about 13 s (1.4 m/s), one scan point about every 3 s.
- Test suites: 460 Python tests, 66 dashboard tests.

## Honest status

- **City-scale census not run.** We did not get CoStar dataset access, so there is no Houston or LA headline number. The census pipeline has run end to end on a fallback building and on the demo building only.
- **No phone ring yet.** Twilio is not configured, so responder and 911 calls are logged, not placed. iMessage alerts and the 911 briefing text are real (Photon).
- **No Claude keys in the demo setup.** The live path never depends on an LLM; the scene check is skipped and documents use templates.
- **Indoor position is approximate.** The app starts the responder from GPS and moves them by step count; "Walk it" replays the route at walking pace for a reliable demo.
- **Never calls real 911.** The 911 briefing goes to a teammate's phone. "No AED visible in the scan" never means "no AED".

## Run it

Prerequisites: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node 22, Expo Go on a phone, a Supabase project, and `cloudflared` for a tunnel. Copy `.env.example` to `.env` and fill it in (Supabase keys, Matterport keys, optional Photon, Twilio, Anthropic or Bedrock). `mobile/.env` needs the four `EXPO_PUBLIC_*` values.

```bash
uv sync --extra dev --extra vision
(cd dashboard && npm install) && (cd mobile && npm install)

# database: migrations in supabase/migrations, then the demo building and its seed
uv run python -m data.load --file demo/rabinowitz/building.json
psql "$SUPABASE_DB_URL" -f supabase/seed_demo.sql      # then supabase/seed.local.sql with real numbers (git-ignored)

uv run uvicorn agent.main:app --port 8000              # live agent
cloudflared tunnel --url http://localhost:8000         # put the URL in mobile/.env as EXPO_PUBLIC_AGENT_URL
(cd dashboard && npx next dev -p 3000)                 # http://localhost:3000/live
(cd mobile && npx expo start -c --lan)                 # scan the QR code with Expo Go
uv run python -m vision.main                           # webcam (CAMERA_ID=cam-atrium-1)
```

Fall sideways in view of the webcam and keep your arms down, or use Simulate on `/live`. Seeded responders count as nearby for 10 minutes; re-run the seed before each take.

The dashboard is also deployed at https://within-reach-nu.vercel.app (the 3D route page needs the domain on the Matterport SDK key's allow list).

## Layout

```
shared/      Python: config, database, LLM client, thresholds, event emitters
data/        Python: dataset adapters, Matterport Model API export, loader
census/      Python: the census Deep Agent and the math behind it
vision/      Python: live person-down detection (standalone)
agent/       Python: FastAPI + deterministic LangGraph live response, Photon, Twilio, TTS
dashboard/   Next.js: city map, building twin, agent console, live desk, responder 3D route
mobile/      Expo: responder app (alerts, floor plan, step tracking, 3D route link, CPR guide)
supabase/    migrations and seeds
demo/        fallback and demo buildings, planted AED notes
```

| Read | For |
|---|---|
| [CLAUDE.md](CLAUDE.md) | The build spec: behavior, triage, data model, demo script |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module boundaries and key decisions |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Every interface between modules |
| [docs/PROGRESS.md](docs/PROGRESS.md) | What is built, how each part was verified, open items |

## Safety and privacy

- The demo runs with `REQUIRE_CONFIRM=false`: alerts go out without a desk confirm. Set it to `true` for the medically reviewed rule (spec section 3) that a human confirms before strangers are alerted, with witnessed collapses going ahead after 10 s.
- Camera frames leave the laptop only with a person-down event; no face recognition; only equipment crops are kept from scans.
- The database policies are a demo auth bypass, not production security.
- Every number shown comes from our own runs.
