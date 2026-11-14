# Within Reach — Build Spec v3 (HackPrinceton Fall 2026)

> Hand-off doc for Claude Code. Read this whole file before writing code.
> v3 merges two team ideas:
> - **Within Reach**: a life-safety census of the CoStar buildings in Houston and LA. This is the lead.
> - **First Five Minutes**: live emergency response. This is the visceral demo moment.
>
> It keeps the feedback from three mock judges (technical, emergency medicine, CoStar/product). See §21 for what changed.
>
> **Rules for Claude Code**
> 1. **Census first, camera second.** Camera fall detection is played out at hackathons; the building census is the differentiator. The camera is only the trigger that shows the census data saving a life.
> 2. **Agentic where it's safe, deterministic where lives are at stake.**
>    - The census runs as a LangChain Deep Agent that visibly plans and decides (§9.2).
>    - The live emergency path is a deterministic LangGraph state machine with no LLM before the first spoken instruction (§9.8).
> 3. **Heavy math lives in plain Python tools**, not in the LLM: routing, coverage, placement, scoring.
> 4. **Only real numbers from our own runs** go into the UI, slides or Devpost. Never invent a statistic. Say "visible in the scan," never "the building has no AED."
> 5. **Never call real 911.** The demo uses a simulated dispatcher phone.
> 6. Build integration-first and commit after each working step. Ask before changing the architecture, data model, triage logic (§3) or demo script (§11).

---

## 1. One-liner and hook

**Within Reach** measures, for every spot inside thousands of real buildings in Houston and LA, how far you are from the things that keep you alive — an AED, a fire extinguisher, an exit. An AI agent finds the dangerous gaps, ranks them by how many people are at risk, and drafts the fix. When a camera sees someone collapse, the same map tells bystanders where the AED is, alerts nearby trained responders, and tells EMS which door to use.

**Hook:** "For every spot in **{N}** buildings, we measured how far you are from the things that keep you alive." N is the real count from our overnight run.

## 2. Why this matters (verify every figure against §20 before it goes on a slide)
- 350,000+ out-of-hospital cardiac arrests a year in the US (AHA). Survival falls roughly 7–10% per minute without CPR and defibrillation.
- People shocked by a public AED survived 66.5% of the time vs 43% for those who weren't (ISHN, from Harsh's doc — verify).
- AEDs are often invisible to the system: in one North Carolina survey 65.1% of AEDs weren't in the state registry. The national PulsePoint/ZOLL registry connects 200,000+ AEDs to 911, but many more are unregistered.
- CARES 2025: bystander CPR 42.5%, bystander AED use in public 13.9%, survival 10.5%.
- **The gap we fill:** help is often nearby, but nobody knows where it is, and nobody has measured how far it is from every spot in a building.

## 3. Live triage & playbooks (medically reviewed — do not simplify)
Cardiac arrest = **unresponsive and not breathing normally (or only gasping)**. A camera can't judge breathing, so every unresponsive person down is treated as *possible* cardiac arrest, and the bystander is told to check breathing.

**Vision signals:**
- `witnessed`: sudden standing→down drop within ~2 s.
- `found_down`: already down when first seen, or got down slowly. Often asleep or intoxicated.
- `responsive`: **only** the victim's track holding a wrist above the shoulder for ≥ 1.5 s. Movement alone never counts — gasping and seizure-like jerks are common early in an arrest.
- `possible_seizure`: rhythmic limb movement while down. Still escalates.

**Decision tree:**
```
person_down → immediately: speaker voice check "Are you okay? If you can hear me, raise your hand."
            → in parallel: Claude verify {is_emergency, scene_safe, hazards[], modifiers[]} + desk CONFIRM request
            → after VOICE_CHECK_SECONDS: raised hand → FALL ; otherwise → CARDIAC (+ modifiers)
scene_safe=false → bystanders told to stay back, police notified, no responders sent in
external actions (responders, 911 briefing) gated by CONFIRM:
   witnessed  → auto-proceed after 10 s if nobody taps
   found_down → needs a human confirm; after 60 s, 911 briefing only (no strangers)
```

**Speaker templates** (pre-rendered per camera; `{…}` filled from the census map):

| Playbook | Script / actions |
|---|---|
| **CARDIAC** | "Emergency: someone has collapsed by **{landmark}**. Go to them, tap their shoulder and shout. If they don't respond and aren't breathing normally, call 911 on speaker and start CPR: push hard and fast in the center of the chest. Someone else: get the AED — **{aed_distance} meters, {aed_directions}**." Repeat every 20 s. After CPR starts: "Push at least 2 inches deep, 100 to 120 times a minute, let the chest come back up. When the AED arrives, turn it on and follow its voice." **Actions:** responder roles (§9.10), 911 briefing with the EMS door, staff alert. |
| + breathing | "If they are breathing, roll them onto their side and stay with them." |
| + seizure | "If they're shaking, don't hold them down or put anything in their mouth. Move hard objects away. When it stops, check breathing — if they're not breathing normally, start CPR." |
| + overdose | "Naloxone is in **{naloxone_location}**. Spray one dose in a nostril." (Only if naloxone is mapped.) |
| **FALL** (responsive) | "Help is on the way. Try not to move. Staff have been notified." **Actions:** staff first. 911 briefing automatically after 60 s unless staff cancel. |

The modifier allowlist is `[breathing, seizure, overdose, notify_police]`. Claude may only *add* modifiers, never remove a safety step.

## 4. Architecture

```
            ┌──────────────── CENSUS (offline, agentic) ────────────────┐
 CoStar     │  Deep Agent planner                                        │
 dataset ──▶│   ├─ Records  (CoStar: type, tenants → people at risk)     │
 (scans,    │   ├─ Scanner  (panoramas → equipment, double-check)        │──▶ Supabase ──▶ dashboard/
 panoramas, │   ├─ Mapper   (sweep graph → walking-time maps, red zones) │   (Postgres +   city map, building twin,
 records,   │   ├─ Outside  (Vexcel: entrances, ambulance parking,       │    Realtime)    agent console, fix + docs,
 Vexcel)    │   │            hydrants → EMS door)                         │                 live incident panel
            │   └─ Fixer    (placements, owner letter, registry list,    │        ▲
            │                emergency card)                              │        │
            └────────────────────────────────────────────────────────────┘        │
                                                                                   │
            ┌──────────────── LIVE (real time, deterministic) ──────────┐          │
 webcam ───▶│ vision/ YOLO track → person_down / responsive / seizure    │          │
 (or Pi)    │ agent/ LangGraph state machine: checkpointer + interrupts  │──────────┘
            │ uses the census routes + EMS door; Polly speaker; Twilio   │──▶ mobile/ responder app (Expo Go)
            └────────────────────────────────────────────────────────────┘
```

## 5. Repo layout
```
within-reach/
  CLAUDE.md  .env.example
  data/        # dataset adapters + data/README.md (what the CoStar track actually provides)
  census/      # Python: tiling, detection, pinning, mapping, scoring, placement, docs; Deep Agent
  vision/      # Python: live person-down detection
  agent/       # Python: FastAPI + LangGraph live graph, Twilio, Polly, APIs for dashboard/mobile
  dashboard/   # Next.js + Tailwind
  mobile/      # Expo responder app
  supabase/    # migrations + seed.sql
  demo/        # backup recordings, Peri materials, fallback data
```

## 6. Tech stack
- **Census agent:** LangChain **Deep Agents** (`deepagents` package — check the current API): a planner with a todo list plus subagents. Claude models via env.
  - `CLAUDE_MODEL_REASONING=claude-sonnet-5-5` for the planner and verification.
  - `CLAUDE_MODEL_FAST=claude-haiku-5-5` for the first-pass detection.
  - `USE_BEDROCK=true` → Claude on Amazon Bedrock (look up the Bedrock model IDs; fall back to the Anthropic API).
  - For big overnight vision volumes, use the Anthropic Message Batches API (or the Bedrock batch equivalent) where it fits.
- **Live agent:** FastAPI + LangGraph (checkpointer, `interrupt()`, `Command(resume=…)`, `Send`). LangSmith tracing for both agents.
- **Vision (census):** py360convert (equirectangular → perspective tiles), a first-pass detector, Claude verification. Optional open-vocabulary detector (YOLO-World / OWLv2) if a GPU is available.
- **Vision (live):** OpenCV + Ultralytics YOLOv8n-pose with `model.track()`. Runs on a laptop, or a Raspberry Pi + camera + speaker for the Hardware/Physical AI tracks.
- **Graphs:** networkx (A*, multi-source Dijkstra, greedy placement).
- **Voice:** Amazon Polly (`TTS_PROVIDER=polly`), with scripts pre-rendered per camera.
- **Data:** Supabase (Postgres + Realtime). Demo auth bypass.
- **Calls:** Twilio Programmable Voice. Upgrade the account (~$20). Webhooks via ngrok/cloudflared.
- **Dashboard:**
  - Next.js + Tailwind, with Leaflet/Mapbox for the city map.
  - 2D SVG floor heatmaps drawn from sweep x/z (always works).
  - Matterport Showcase SDK embed for the 3D twin and fly-through.
- **Mobile:** Expo Go (foreground Realtime alerts), expo-location, expo-haptics, expo-audio, react-native-maps. No push notifications or background location this weekend.

## 7. Data model (supabase/migrations/0001_init.sql)
```sql
create extension if not exists pgcrypto;

create type asset_type as enum ('aed','naloxone','extinguisher','exit','exit_sign','sprinkler','smoke_detector','first_aid','stairs','elevator');
create type incident_type    as enum ('cardiac','fall','fire','unknown');
create type incident_status  as enum ('detected','awaiting_confirm','voice_check','confirmed','responding','resolved','false_alarm');
create type dispatch_channel as enum ('app','call','speaker','broadcast');
create type dispatch_status  as enum ('sent','accepted','declined','timeout','released','arrived');
create type dispatch_role    as enum ('patient','aed_runner','staff','broadcast');
create type responder_role   as enum ('public','staff','security','tenant');

-- ===== Census =====
create table buildings (
  id uuid primary key default gen_random_uuid(),
  costar_property_id text unique, matterport_model_id text,
  name text, address text, city text,              -- 'Houston' | 'Los Angeles'
  lat double precision, lng double precision, geofence_m int default 60,
  property_type text, floors int, size_sqft int, tenants_count int,
  occupancy_est int,                                -- derived: tenants/size × type factor
  manager jsonb, contacts jsonb default '[]', monitoring_callback text,
  vexcel jsonb,                                     -- {entrances:[], ambulance_parking:[], hydrants:[], image_url}
  ems_door jsonb,                                   -- chosen entrance {lat,lng,desc,reason}
  census_status text default 'pending',             -- pending|scanning|mapped|fixed|error
  priority_score real, created_at timestamptz default now()
);

create table twin_nodes (
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, floor int, x double precision, y double precision, z double precision,
  neighbors text[] not null default '{}', room_type text, label text,
  is_elevator boolean default false, is_stairs boolean default false,
  primary key (building_id, sweep_id)
);

create table panos (
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, image_uri text, tiles_done boolean default false,
  primary key (building_id, sweep_id)
);

create table detections (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, asset_type asset_type, tile_heading real, tile_pitch real,
  bbox real[], crop_uri text, confidence real,
  verified_by text,                                 -- 'first_pass'|'claude'|'second_pano'|'human'
  status text default 'candidate',                  -- candidate|confirmed|rejected
  human_label text,                                 -- for the ~30 hand-checks
  notes text, created_at timestamptz default now()
);

create table assets (                               -- confirmed equipment pinned to the twin
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  type asset_type not null, sweep_id text, floor int, label text,
  x double precision, y double precision, z double precision,   -- triangulated if seen from 2 panos
  source text check (source in ('detected','tag','manual','proposed')) default 'detected',
  detection_ids uuid[] default '{}', verified boolean default false,
  flags text[] default '{}'                          -- e.g. 'blocked_exit'
);

create table coverage (                             -- walking-time map
  building_id uuid references buildings(id) on delete cascade,
  sweep_id text, asset_type asset_type, time_s real,
  scenario text default 'current',                  -- 'current'|'proposed'
  primary key (building_id, sweep_id, asset_type, scenario)
);

create table building_scores (
  building_id uuid primary key references buildings(id) on delete cascade,
  aed_worst_s real, aed_red_frac real,
  ext_worst_s real, ext_red_frac real,
  exit_worst_s real, exit_red_frac real,
  stairs_only boolean, blocked_exits int,
  worst_gap text,                                   -- 'aed'|'extinguisher'|'exit'|'none'
  people_at_risk int, gap_score real, rank int, updated_at timestamptz default now()
);

create table fixes (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  asset_type asset_type, sweep_id text,
  before_worst_s real, after_worst_s real, before_red_frac real, after_red_frac real,
  rationale text
);

create table documents (
  id uuid primary key default gen_random_uuid(),
  building_id uuid references buildings(id) on delete cascade,
  kind text check (kind in ('owner_letter','emergency_card','registry_list')),
  content_md text, created_at timestamptz default now()
);

create table runs (
  id uuid primary key default gen_random_uuid(),
  started_at timestamptz default now(), finished_at timestamptz,
  buildings_target int, buildings_done int default 0, panos_done int default 0,
  est_cost_usd real default 0, status text default 'running', notes text
);

create table agent_events (                         -- powers the on-screen agent console
  id bigserial primary key, run_id uuid references runs(id) on delete cascade,
  ts timestamptz default now(),
  agent text,                                       -- planner|records|scanner|mapper|outside|fixer
  kind text,                                        -- todo|decision|tool_call|result|warning
  building_id uuid, message text, payload jsonb default '{}'
);

-- ===== Live =====
create table cameras (
  id text primary key, name text, building_id uuid references buildings(id),
  sweep_id text, floor int, landmark text, lat double precision, lng double precision,
  has_speaker boolean default true
);

create table camera_routes (
  camera_id text references cameras(id) on delete cascade,
  target text check (target in ('aed','naloxone','exit','extinguisher')),
  path text[], distance_m real, directions text, audio_url text,
  primary key (camera_id, target)
);

create table responders (
  id uuid primary key default gen_random_uuid(),
  name text not null, phone text not null, callable boolean default false,
  cpr_trained boolean default false, role responder_role default 'public',
  building_id uuid references buildings(id),
  last_lat double precision, last_lng double precision, last_seen_at timestamptz,
  consent_location boolean default false, consent_calls boolean default false, on_duty boolean default true
);

create table incidents (
  id uuid primary key default gen_random_uuid(),
  type incident_type default 'unknown', status incident_status default 'detected',
  camera_id text references cameras(id), building_id uuid references buildings(id),
  witnessed boolean, modifiers text[] default '{}', scene_safe boolean, hazards text[] default '{}',
  verification jsonb, confirmed_by text, snapshot_url text,
  collapse_at timestamptz, first_instruction_at timestamptz, confirmed_at timestamptz,
  ems_notified_at timestamptz, first_accept_at timestamptz, responder_arrived_at timestamptz,
  cpr_started_at timestamptz, aed_arrived_at timestamptz, resolved_at timestamptz,
  created_at timestamptz default now()
);

create table incident_events (
  id bigserial primary key, incident_id uuid references incidents(id) on delete cascade,
  ts timestamptz default now(), actor text, kind text, payload jsonb default '{}'
);

create table dispatches (
  id uuid primary key default gen_random_uuid(),
  incident_id uuid references incidents(id) on delete cascade, responder_id uuid references responders(id),
  channel dispatch_channel, role dispatch_role, wave int default 1,
  status dispatch_status default 'sent', call_sid text,
  sent_at timestamptz default now(), responded_at timestamptz
);

alter publication supabase_realtime add table agent_events, runs, building_scores, incidents, incident_events, dispatches, responders;
```
**Ask before changing the schema** once `data/README.md` shows what the dataset really contains (§9.1).

## 8. API contracts (agent/ FastAPI)
- **Census:**
  - `POST /census/runs` `{buildings_target, city?, types?, budget_usd}` → starts a Deep Agent run
  - `GET /census/runs/{id}`
  - `POST /census/buildings/{id}/rerun` (demo: watch the agent work one building live)
  - `POST /census/buildings/{id}/fix`
  - `GET /census/buildings/{id}/documents`
- **Hand-checks:** `GET /census/handcheck?n=30` (random sample) · `POST /census/detections/{id}/label` `{human_label}`
- **Live:**
  - `POST /events` (vision: `person_down|responsive|possible_seizure|responder_arrived`, with `victim_track_id`, `witnessed`, `frame_jpeg_b64` on person_down only)
  - `POST /incidents/{id}/confirm` `{decision, by}` · `POST /incidents/{id}/cancel_911` · `POST /incidents/{id}/milestone` `{kind}` · `POST /incidents/{id}/resolve`
  - `POST /dispatches/{id}/accept|decline|arrived`
  - `POST /twilio/voice/{dispatch_id}` · `POST /twilio/gather/{dispatch_id}` · `POST /twilio/briefing/{incident_id}`
  - `POST /simulate/{cardiac|fall|outdoor}` · `POST /reset`

## 9. Components

### 9.1 data/ — dataset adapter (do this first)
- The CoStar track provides scans for ~15,000 buildings in Houston and LA (per Harsh's doc). **Inspect the real dataset before writing anything else.**
- Write `data/README.md` covering:
  - what fields exist per building (CoStar records, tenants, type)
  - how to get Matterport sweeps, positions, neighbors, room types and **panorama images**
  - what Vexcel gives (entrances, parking, hydrants, imagery)
  - access limits
- Include one full sample building.
- Build `data/load.py` to normalize everything into `buildings`, `twin_nodes` and `panos`.
- If panoramas aren't downloadable in bulk, fall back to SDK screenshots per sweep. That's slower; note it in `data/README.md`.

### 9.2 census/ — the Deep Agent (agentic depth is ~30% of the CoStar score)
The **planner** keeps a visible todo list and delegates to five subagents. Every decision is written to `agent_events` so judges *see it decide*:
- which buildings to check first
- when to double-check a detection from a second panorama
- where the new AED goes
- drafting the letters

| Subagent | Tools (plain Python) | Decisions it makes |
|---|---|---|
| **Records** | `get_costar_profile`, `estimate_occupancy` | Which buildings are highest-risk (type × tenants × size) → the scan order |
| **Scanner** | `tile_pano`, `detect_first_pass`, `verify_crop`, `find_second_view`, `pin_asset` | Is this crop really an AED / extinguisher / exit sign? Low confidence → get a second panorama and triangulate. Flag exits that look blocked. |
| **Mapper** | `build_graph`, `walking_time_map`, `flag_routes` | Red zones per equipment type; stairs-only routes; which gap is worst |
| **Outside** | `get_vexcel`, `pick_ems_door` | Best ambulance entrance, staging spot and nearest hydrant |
| **Fixer** | `place_one`, `draft_owner_letter`, `registry_list`, `emergency_card` | Where one new AED or extinguisher covers the most floor space; owner letter + 911 registry list + one-page emergency card |

- **Budget awareness:** the planner tracks `runs.est_cost_usd` and stops dispatching new buildings at `CENSUS_BUDGET_USD`.
- **Overnight execution:** the planner chooses *what* to do. Bulk work (tiling, first-pass detection) runs through a worker pool or batch API. The planner monitors and handles anomalies. For the demo, run `POST /census/buildings/{id}/rerun` live on one building with the console streaming.

### 9.3 Scanner details
1. **Tiling:** equirectangular → 6–8 perspective tiles at ~90° FOV. Keep the heading/pitch for each tile.
2. **First pass:** `CLAUDE_MODEL_FAST` on downscaled tiles, with a strict JSON schema `{items:[{type, bbox, confidence}]}`. Use an open-vocabulary detector instead if a GPU is available.
   - Types: aed, extinguisher, exit_sign, sprinkler, smoke_detector, first_aid, naloxone.
3. **Verify:** for candidates above `DETECT_MIN_CONF`, crop and send to `CLAUDE_MODEL_REASONING` → confirmed/rejected + short reason. Flag `blocked_exit` if an exit door/sign is obstructed.
4. **Double-check:** if confidence is borderline, the agent finds a neighboring sweep facing that direction and checks there. A match in both views → triangulate the 3D position (closest point between the two rays) and mark `verified_by='second_pano'`.
5. **Pin:** confirmed items → `assets` at the triangulated position (or the viewing sweep + heading) and the nearest sweep.
6. **Privacy:** panoramas may contain people. Never store face crops; only equipment crops are kept.
7. **Accuracy:** sample ~30 detections for human labels and report precision on screen and in Devpost ("29/30 correct" style, real numbers only).

### 9.4 Mapper — walking-time maps
- Graph: sweeps as nodes, neighbors as edges, weight = 3D distance. Mark stairs/elevator nodes.
- Multi-source Dijkstra from every confirmed asset of a type → walking time per sweep at `WALK_SPEED_MPS` (1.4).
- **Red-zone thresholds** — check each against the source before quoting it:

| Equipment | Measure | Red when |
|---|---|---|
| AED | round trip (2× one-way) | > `AED_ROUNDTRIP_TARGET_S` (default 180 s; check the guideline) |
| Extinguisher | one-way travel distance | > `EXT_MAX_TRAVEL_M` (default 22.9 m ≈ 75 ft, NFPA 10 Class A; verify) |
| Exit | one-way travel distance | > `EXIT_MAX_TRAVEL_M` (default 61 m ≈ 200 ft; varies by occupancy and sprinklers; verify) |

- **Flags:**
  - stairs-only routes from upper floors (accessibility)
  - blocked exits
  - "no AED visible in the scan" (never "no AED")
- Write `coverage` + `building_scores`.

### 9.5 Rank
- `people_at_risk` = occupancy estimate × red-zone fraction for the worst gap.
- `gap_score` weights the AED gap highest.
- `rank` across the city. The planner uses Records' priors to choose the scan order, then re-ranks on the measured gaps.

### 9.6 Fixer
- **Placement:** greedy search over candidate sweeps — where one new AED (or extinguisher) minimizes the worst case and maximizes the covered floor area. Store as `fixes` + `assets(source='proposed')` + `coverage(scenario='proposed')`.
  - Show "worst case 140 s → 60 s; red area 38% → 4%."
- **Documents** (Claude drafts from structured facts; facts only, no invented numbers):
  - **Owner letter:** what we measured, the gaps, the recommended placement, how to register AEDs. Drafts only — never sent automatically.
  - **Registry list:** AEDs visible in the scan, to confirm registration with the national registry / 911.
  - **Emergency card** (one page, printable): AED and extinguisher locations, exits, EMS door (Vexcel), address.

### 9.7 Outside (Vexcel)
- Entrances, ambulance parking and hydrants for the building.
- Pick the EMS door: closest entrance to the building's highest-risk zone with ambulance access.
- Store in `buildings.ems_door`. Shown in the live moment and on the emergency card.

### 9.8 Live response graph (deterministic LangGraph)
- **State:** incident, camera, victim track, witnessed, type, modifiers, routes (from `camera_routes`, precomputed from the census map), dispatches, timestamps.
- Checkpointer keyed by `thread_id = incident_id`.
- Interrupts for **confirm**, **voice_check** and **await_accept**, resumed by `/events`, `/confirm`, `/dispatches` and `/twilio/gather`, or by timer tasks resuming with `"timeout"`.
- **Nodes:**
  1. ingest
  2. local_first_response — pre-rendered voice check, set `first_instruction_at`
  3. parallel: verify, request_confirm, voice_check
  4. classify (conditional: false alarm / unsafe scene / FALL / CARDIAC + modifiers)
  5. gate (confirm rules from §3)
  6. fan-out via `Send`: announce loop, dispatch_responders, brief_911, notify_police (only if hazards), alert_staff, fall_911_timer
  7. guide — CPR coaching loop, switching to the depth/rate script and then the AED script on milestones
  8. handoff
- **Latency budget:**
  - event → voice-check audio < 1 s
  - first CPR instruction ≤ 12 s after the collapse
  - first phone ringing ≤ 15 s with a desk confirm
  - Show both live on the dashboard. Warm up Claude, Polly and YOLO at start.

### 9.9 vision/ (live)
- Camera ~2 m high over a taped-off zone. `model.track(persist=True)`.
- Down = torso near horizontal or bbox w/h > 1.3 for ≥ `DOWN_SECONDS` (demo 5). Sitting must not trigger.
- Witnessed = hip-y drop > 40% of body height within 2 s.
- Responsive = victim track wrist above shoulder ≥ 1.5 s.
- Seizure = 1–5 Hz limb oscillation.
- Responder arrived = second track near the victim.
- Frames go to the cloud **only** with a `person_down` event.
- Optional: run on a Raspberry Pi + camera + speaker for the Hardware/Physical AI tracks.

### 9.10 Responders, calls, 911 briefing, handoff
- **Responders:** consent + on duty + seen < 10 min, in the building geofence (or radius outdoors).
  - Priority: staff/security/tenants, then opted-in public; CPR-trained first for cardiac.
  - `WAVE_SIZE` 4, app alert + Twilio call to `callable` phones at the same time. 20 s timeout, 3 waves max. **911 never waits for waves.**
  - **Roles:** first accept = **patient**, second = **AED runner** (routed past the AED). Others released and their calls hung up.
- **Responder call:** situation + role + AED location → press 1 / 2.
- **911 briefing** (to `DISPATCH_SIM_NUMBER`, twice), in this order:
  1. type ("possible cardiac arrest, witnessed collapse")
  2. address + floor + landmark
  3. time since collapse
  4. CPR / AED status
  5. modifiers
  6. **EMS door + staging spot (Vexcel)**
  7. caller-of-record callback (`monitoring_callback`)

  Bystanders are also told to call 911 on speaker. Real deployments send this as a data feed via a monitoring center / RapidSOS-style integration, not AI cold calls.
- **Handoff card (Utstein-style):** collapse time, witnessed, time to first instruction, 911 notified, responder accepted/arrived, CPR started, AED arrived, modifiers.

### 9.11 mobile/ (Expo Go responder app)
- **Onboarding:**
  - Name, phone, CPR-trained, role, building.
  - Consents (location while open, calls).
  - Privacy line: "We only use your location to alert you to emergencies nearby; we never identify people on camera."
  - Good Samaritan line: "Every US state has a Good Samaritan law protecting people who help in good faith; details vary by state."
- **Alerting:** foreground location → `last_lat/lng`. A Realtime subscription to my dispatches → alarm + haptics + Alert screen.
- **Screens:**
  - **Onboarding**
  - **Home**
  - **Alert** — role, distance, directions, map, "View route in 3D", Accept / Can't help + 20 s countdown, then I'm here / AED here
  - **CPR guide** — 110 bpm metronome, §3 wording, AED steps
  - **Released**

### 9.12 dashboard/ (Next.js)
- **`/` City map:**
  - Houston / LA buildings colored by worst gap, with a toggle for AED / extinguisher / exit.
  - Headline number from the last run.
  - Run progress (buildings done, $ spent).
- **Agent console** (pinned on every page): streaming `agent_events` — todos, decisions, double-checks, placements, letters. This is what makes it read as an agent, not a dashboard.
- **`/building/[id]`:**
  - 2D floor heatmap (green / yellow / red per sweep) with an equipment toggle.
  - Matterport twin with markers and red zones.
  - **"Drop AED" moment:** the agent's proposed AED appears and the zones turn green (animate current → proposed).
  - Flags: stairs-only, blocked exits.
  - CoStar facts. Vexcel image with the EMS door, parking and hydrants. Documents tab (letter, card, registry list).
- **`/handcheck`:** label ~30 sampled detections → precision number.
- **`/live`:**
  - Incident card, CONFIRM / FALSE ALARM with countdown, latency metrics, timeline.
  - Twin fly-through to the AED synced to the speaker.
  - EMS door panel, responders + roles, handoff card.
  - Simulate buttons, Reset.

## 10. Build plan — parallel lanes + checkpoints (Devpost due 6:30 AM Sunday)

| Lane | Owner | Scope |
|---|---|---|
| A — Scanner | | §9.1, §9.3 |
| B — Census agent | | §9.2, §9.4–9.7, overnight run |
| C — Dashboard | | §9.12 |
| D — Live | | §3, §9.8–9.11 |
| Peri + pitch | | §13, demo script, Devpost |

If there are only 4 people, lanes A and B pair up after CP1.

| Checkpoint | By (Sat→Sun) | Acceptance criteria |
|---|---|---|
| **CP0 First test** | 3:30 PM | `data/README.md` written. Tiles from 50–100 commercial scans (gyms + offices first) run through the Scanner. Report the hit rate for AEDs / extinguishers / exit signs, seconds and $ per building, and save 30 samples for hand-check. **Decide the pitch lead:** if AEDs are rarely visible, extinguishers and exits carry the census and we say "visible in the scan." **Peri: scan the local gym with the Matterport app now** (processing takes time). |
| **CP1 One building end-to-end** | 7:00 PM | One building: detections pinned → walking-time maps → red zones → flags → greedy fix → letter + card + registry list → building page renders the heatmap and the drop-AED animation. Live thin slice: `/simulate/cardiac` → audio → confirm → app alert → accept. |
| **CP2 Agent + live cardiac** | 11:00 PM | The Deep Agent runs on 20 buildings with visible decisions in the console (scan order, second-pano double-checks, placements, letters). City map live. Live: a real collapse on camera → voice check → CARDIAC script with the census route → confirm → app alert + real call (AED runner) → 911 briefing with the EMS door → handoff card. **Record backup video #1.** |
| **CP3 Overnight run starts** | 11:30 PM | Launch the full run on the risk-ranked buildings within `CENSUS_BUDGET_USD`. It keeps going while everyone polishes. |
| **CP4 Real numbers** | 3:30 AM | Run results in. ~30 hand-checks labeled → precision. Headline number computed from real data. Peri gym materials in. Stretch only if everything is green: outdoor scene → live fire reroute → dispatcher bridge. |
| **CP5 Freeze** | 5:00 AM | Feature freeze, final backup recording, README, Devpost submitted by **6:30 AM**, rehearse 5 times. |

## 11. Demo script (3:00 — one person talks, one drives)
1. **Hook (15 s):** "For every spot in {N} real buildings in Houston and LA, we measured how far you are from the things that keep you alive."
2. **City map (15 s):** buildings colored by worst gap; the headline finding, e.g. "{X}% have a spot more than 3 minutes round-trip from any AED visible in the scan" (real number only).
3. **Agent at work (20 s):** the console streams the agent choosing which buildings to check first and double-checking an AED from a second panorama.
4. **Click a gym (30 s):** the 3D twin shows red zones → the agent drops a virtual AED → zones turn green ("worst case 140 s → 60 s") → owner letter + emergency card appear.
5. **Flip the map (10 s):** extinguishers and exits.
6. **Live collapse (45 s):**
   - A teammate collapses in the taped zone.
   - Voice check, no response.
   - The speaker: "…check breathing, call 911 on speaker, start CPR. Someone else: get the AED — 14 meters, left of the elevators."
   - The twin flies to the AED. The desk taps Confirm. A phone alarms and rings ("You're the AED runner"). The sim-911 phone on speaker hears the briefing with the EMS door.
   - The screen shows the EMS door and the handoff card. "First instruction: 9 s."
7. **Peri proof (20 s):** the local gym we scanned, where we told them to mount their AED, and the staff member's quote/photo.
8. **Close (15 s):** "Monday: CoStar adds a life-safety score to every LoopNet listing, owners get a fix list, and 911 gets AEDs it didn't know about."

Over time? Cut step 5 first, then shorten step 3. The outdoor scene is a stretch goal, not in the 3:00 script unless it fits.

**Stage hygiene:** two phones ring (responder + sim-911 on speaker), everyone else silenced, one laptop speaker.

## 12. Seed / demo data
- Real buildings from the dataset via `data/load.py`. For the live demo, pick one gym/office building with good scans, map `cam-lobby-1` to a sweep in it with landmark "east elevators", and precompute `camera_routes`.
- `monitoring_callback` = a teammate.
- Responders: teammate A (staff, CPR, `callable`), teammate B (public, `callable`), 4 non-callable seeded responders (to show waves and roles), 2 outdoor responders (stretch).
- If the dataset access stalls: `demo/fallback/` holds one hand-built building (twin JSON + assets) so every screen still works.

## 13. Peri plan (real-world proof)
1. Visit a local gym this afternoon. Ask staff whether they know where the AED is right now.
2. Scan the space with a phone (Matterport app) and run it through our pipeline.
3. Give them the best spot to mount the AED, plus an emergency card.
4. Save their name, role and a quote or photo (with permission) for the submission.

## 14. Environment (.env.example)
```
ANTHROPIC_API_KEY=
CLAUDE_MODEL_REASONING=claude-sonnet-5-5
CLAUDE_MODEL_FAST=claude-haiku-5-5
USE_BEDROCK=true
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
TTS_PROVIDER=polly
POLLY_VOICE=Joanna
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
EXPO_PUBLIC_SUPABASE_URL=
EXPO_PUBLIC_SUPABASE_ANON_KEY=
EXPO_PUBLIC_DASHBOARD_URL=
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=
DISPATCH_SIM_NUMBER=
PUBLIC_BASE_URL=
MATTERPORT_SDK_KEY=
COSTAR_DATA_PATH=           # or API credentials — see data/README.md
VEXCEL_API_KEY=
LANGSMITH_API_KEY=
LANGSMITH_TRACING=true
# census
CENSUS_BUDGET_USD=150       # set with the team before the overnight run
DETECT_MIN_CONF=0.35
WALK_SPEED_MPS=1.4
AED_ROUNDTRIP_TARGET_S=180
EXT_MAX_TRAVEL_M=22.9
EXIT_MAX_TRAVEL_M=61
# live
CAMERA_INDEX=0
DOWN_SECONDS=5
VOICE_CHECK_SECONDS=5
RESPONSIVE_HOLD_SECONDS=1.5
CONFIRM_AUTO_PROCEED_SECONDS=10
FOUND_DOWN_ESCALATE_SECONDS=60
FALL_911_CANCEL_SECONDS=60
WAVE_SIZE=4
ACCEPT_TIMEOUT_SECONDS=20
```

## 15. Risks & fixes
| Risk | Fix |
|---|---|
| Reads as a dashboard, not an agent | Agent console on every page; demo step 3; live rerun of one building on stage. |
| Wrong detections | Two-stage verify + second-pano double-check; hand-check ~30 and report precision. |
| AEDs rare in scans | Extinguishers and exits carry the census; say "visible in the scan." |
| Can't process all ~15,000 buildings overnight | Risk-ranked order + budget cap; the headline uses the real count scanned. Never claim more than we ran. |
| Dataset access / panorama download slow | `data/README.md` first; SDK-screenshot fallback; `demo/fallback/` building. |
| A map isn't visceral | Keep the 45 s live collapse. |
| Live demo fails | Simulate buttons → backup recordings (#1 at CP2, final at CP5). |
| Venue Wi-Fi | Live path on one laptop; phone hotspot for Twilio/Supabase. |

## 16. Safety, privacy & claims (non-negotiable)
- Live: say "person down" / "possible cardiac arrest"; never diagnose. Coach standard hands-only CPR (at least 2 inches, 100–120 per minute). Never call real 911.
- A human confirms before strangers or the 911 briefing, except witnessed collapses auto-proceed after 10 s.
- Cameras: pose only, frames leave the device only on a person-down event, no facial recognition, nothing stored beyond the incident snapshot.
- Census: equipment crops only; no faces stored from panoramas. Letters are drafts for owners, never auto-sent. "No AED visible in the scan" ≠ "no AED."
- Only real numbers from our runs. Code thresholds are cited and marked as approximations.

## 17. Tracks
| Track | Our angle | Proof |
|---|---|---|
| **Science & Discovery (main)** | City-scale measurement of life-safety access — a new dataset nobody has | Hook + city map + precision number |
| **Healthcare** | Live cardiac response, medically reviewed triage, Utstein handoff | Live collapse |
| **CoStar** | All three data layers (Matterport, Vexcel, CoStar) do real work; Deep Agent decisions on screen | Steps 2–5 |
| **Peri** | Real gym, real recommendation, staff quote | Step 7 |
| **LangChain** | Deep Agent (planner + 5 subagents) for the census; LangGraph with human-in-the-loop for the live path; LangSmith traces | Console + a trace in Q&A |
| **Amazon** | Claude on Bedrock, Polly voice (+ batch vision if we use it) | Devpost + close |
| **Hardware / Physical AI** | Only if a Pi camera + speaker works by CP2 | Live collapse on the Pi |
| **Best Overall** | Automatic | — |

## 18. Competitors & positioning
- **Camera person-down alerts** (Verkada, Volt.ai, many hackathon fall-detection projects) and **bystander CPR apps** (PulsePoint, GoodSAM, Heartrunner, many hackathon apps) exist.
- **AED registries** (PulsePoint/ZOLL) know registered AEDs, not walking time from every spot.
- **Matterport twins** with AED tags exist as one-off preparedness tools.
- **Ours:**
  - a census of life-safety access across thousands of real buildings
  - an agent that finds and fixes the gaps
  - the same map powering the live response
- Lead with the census; the camera is only the trigger.

## 19. Judge Q&A prep
1. **"How accurate are the detections?"** Two-stage verify + second-pano double-check; "we hand-checked 30: {x}/30 correct."
2. **"Did you really scan 15,000 buildings?"** Say exactly how many we ran overnight and how the agent prioritized them.
3. **"A missing AED in the scan doesn't mean there isn't one."** Correct — we say "visible in the scan," and the owner letter asks them to confirm and register.
4. **"Is this an agent or a dashboard?"** Show the console: it chose the scan order, double-checked a detection from a second view, placed the AED, drafted the letter.
5. **"Who pays?"** CoStar life-safety score on LoopNet listings; owners and insurers get fix lists; 911 gets unregistered AEDs.
6. **"False alarm on the camera?"** Local voice check first; a human confirm gates strangers and 911; found-down never auto-dispatches strangers.
7. **"Gasping or jerking during the voice check?"** Only a sustained raised hand counts as responsive; a seizure adds guidance but still escalates.
8. **"Who's the 911 caller of record?"** The monitoring center/security desk callback; bystanders are also told to call on speaker; real deployments use a data feed.
9. **"Why a twin, not a floor plan?"** Real walking distance over the scan graph, equipment found automatically in the panoramas, 3D routes a stranger can follow, portfolio-wide scoring.

## 20. Sources (verify before the pitch)
- AHA CPR & AED facts: https://cpr.heart.org/-/media/CPR2-Files/Course-Materials/2020-Heartsaver/HS-Marketing-Toolkit/Heartsaver-General-CPR-Stats_ucm_506893.pdf
- CARES 2025: https://mycares.net/sitepages/uploads/2026/2025_flipbook/inc/html/page61.html
- GoodSAM study: https://evidence.nihr.ac.uk/?p=54102
- Matterport SDK pathfinding: https://matterport.github.io/developer-docs/tutorials/pathfinding/
- Matterport twins for emergency preparedness: https://matterport.com/ko/industries/case-studies/transforming-emergency-preparedness-how-digital-twin-imaging-and-matterport
- **From Harsh's Within Reach doc** (links in that doc; verify the figures):
  - ISHN: AED-shock survival 66.5% vs 43%
  - North Carolina AED registry survey: 65.1% unregistered
  - JEMS: PulsePoint/ZOLL national registry, 200,000+ AEDs
- **Not yet verified:**
  - AED round-trip guideline (180 s)
  - NFPA 10 extinguisher travel distance
  - IBC exit travel distances
  - the "~3–4% per minute with bystander CPR" figure

## 21. What changed in v3
- **Lead flipped to the census (Within Reach):**
  - find / measure / rank / fix across the CoStar buildings
  - LangChain Deep Agent with Records, Scanner, Mapper, Outside and Fixer subagents
  - agent console, hand-check precision, owner letters, 911 registry list, emergency cards, city map, CoStar life-safety-score story
- **First Five Minutes became the live moment.** It reuses the census routes and the Vexcel EMS door. The medically reviewed triage, human confirm, responder roles, Utstein handoff and Expo Go app are all kept.
- **New data model** for census tables (panos, detections, coverage, building_scores, fixes, documents, runs, agent_events).
- **Live fire rerouting moved to stretch:** the census covers extinguishers and exits. **The outdoor scene moved to stretch:** not in the 3:00 script unless it fits.
- **Tracks:** Science & Discovery is now main. Peri is back with a concrete plan. Hardware/Physical AI only if the Pi works by CP2.
- **Timeline:** Devpost due 6:30 AM. The first test at 3:30 PM decides the pitch lead. The overnight run starts at 11:30 PM.
