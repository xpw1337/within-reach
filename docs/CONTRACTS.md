# Cross-module contracts

Everything here crosses a lane boundary. Change it only together with the lanes on both sides, and update this file in the same commit. The database schema is `supabase/migrations/0001_init.sql` (spec §7); ask before changing it.

## 1. Conventions

- IDs are UUID strings unless stated. `camera_id` is a human-readable text ID (`cam-lobby-1`).
- Timestamps are ISO 8601 UTC.
- Coordinates in `twin_nodes` and `assets` are the scan's model space in meters. `y` is up; floor plans are drawn from `x` and `z`.
- `coverage.time_s`: one-way walking seconds from that sweep to the nearest asset of that type. `NULL` means no asset of that type is visible in the scan, or it is unreachable on the graph.
- Every `*_s` column is one-way walking seconds, the same unit as `coverage.time_s`: `building_scores.aed_worst_s`, `ext_worst_s`, `exit_worst_s` and `fixes.before_worst_s`, `after_worst_s` included. Anything that shows an AED time to a person (UI, documents, speaker) converts to round trip (2x) through the thresholds helper (`shared/thresholds.py`, `dashboard/lib/thresholds.ts`), never inline.
- Exit maps count assets of type `exit` and `exit_sign` (the Scanner finds signs, not doors). User-facing wording is "exit sign visible in the scan"; distances to exits are an approximation because directional signs count too.
- `*_red_frac` is red positions divided by positions that can reach at least one asset of that type on the graph. Positions with no route are left out and shown as unknown. A building with no asset of that type visible in the scan still gets `1.0`.
- HTTP errors: `{"detail": "<message>"}` with a 4xx or 5xx status.
- All HTTP bodies are JSON except Twilio webhooks (form-encoded in, TwiML XML out).

## 2. HTTP API (`agent/`, base `PUBLIC_BASE_URL`)

### Census

| Method and path | Body | Returns |
|---|---|---|
| `POST /census/runs` | `{buildings_target:int, city?:"Houston"\|"Los Angeles", types?:string[], budget_usd:number}` | `{run_id}` (run continues in the background) |
| `GET /census/runs/{id}` | | the `runs` row |
| `POST /census/runs/{id}/stop` | | `{status:"stopping"}` |
| `POST /census/buildings/{id}/rerun` | | `{run_id}` (single-building run, streams to the console) |
| `POST /census/buildings/{id}/fix` | `{asset_type?:"aed"\|"extinguisher"}` default `aed` | `{fix_id}` |
| `GET /census/buildings/{id}/documents` | | `[{id, kind, content_md, created_at}]` |
| `GET /census/handcheck?n=30` | | `[{detection_id, asset_type, crop_url, confidence, status}]` random sample, unlabeled first |
| `POST /census/detections/{id}/label` | `{human_label:"correct"\|"incorrect"\|"unsure"}` | `{ok:true}` |
| `GET /census/handcheck/summary` | | `{labeled:int, correct:int, incorrect:int, unsure:int}` |
| `GET /config/thresholds` | | `{walk_speed_mps, aed_roundtrip_target_s, ext_max_travel_m, exit_max_travel_m, yellow_fraction}` |

### Live

| Method and path | Body | Returns |
|---|---|---|
| `POST /events` | `{camera_id, kind:"person_down"\|"responsive"\|"possible_seizure"\|"responder_arrived", victim_track_id:int, witnessed?:bool, ts, frame_jpeg_b64?:string}` (`witnessed` and `frame_jpeg_b64` on `person_down` only) | `{incident_id, status}` |
| `POST /incidents/{id}/confirm` | `{decision:"confirm"\|"false_alarm", by:string}` | `{status}` |
| `POST /incidents/{id}/cancel_911` | `{by:string}` | `{ok:true}` (FALL playbook only) |
| `POST /incidents/{id}/milestone` | `{kind:"cpr_started"\|"aed_arrived"\|"responder_arrived", by?:string}` | `{ok:true}` |
| `POST /incidents/{id}/resolve` | `{by:string}` | `{status:"resolved"}` |
| `POST /dispatches/{id}/accept` | | `{role:"patient"\|"aed_runner"\|"staff", status:"accepted"}` or `{status:"released"}` if both roles are taken (`staff` for a staff-alert dispatch) |
| `POST /dispatches/{id}/decline` | | `{status:"declined"}` |
| `POST /dispatches/{id}/arrived` | `{with_aed?:bool}` | `{status:"arrived"}` |
| `POST /twilio/voice/{dispatch_id}` | Twilio form | TwiML: situation, role, AED location, gather 1 digit |
| `POST /twilio/gather/{dispatch_id}` | Twilio form (`Digits`) | TwiML; `1` = accept, `2` = decline |
| `POST /twilio/briefing/{incident_id}` | Twilio form | TwiML: the 911 briefing, spoken twice |
| `POST /photon/webhook` | Photon webhook event (signature verified with `PHOTON_WEBHOOK_SECRET`) | `{ok:true}`. An inbound iMessage from a responder maps to their open dispatch: `1` accept, `2` decline, `here` arrived |
| `POST /simulate/{cardiac\|fall\|outdoor}` | `{camera_id?}` | `{incident_id}` (injects the same event vision would send) |
| `POST /reset` | | `{ok:true}` clears incidents, events, dispatches; cancels timers; hangs up calls |
| `GET /health` | | `{ok, warmed:{llm, tts, db}, metrics}` (`metrics` holds the last measured event-to-audio latency) |

Rules:

- One open incident per camera. A second `person_down` from the same camera while one is open returns the existing `incident_id`.
- `responsive`, `possible_seizure` and `responder_arrived` events for a camera with no open incident are ignored with `{incident_id:null, status:"ignored"}`.
- Every command is idempotent: repeating it returns the current state, never an error.

### Photon 2.0 (approved 2026-11-14)

- Voice: Twilio still runs every call and its TwiML webhooks; when `PHOTON_SIP_*` is set, calls are placed through the Photon number over SIP (`To=sip:<number>@<PHOTON_SIP_SERVER>;transport=tls`, `From=PHOTON_NUMBER`, SIP auth from the Photon Voice profile). The 911 refusal applies to the underlying number.
- iMessage: sent with Photon's REST API (`POST /v1/projects/{id}/messages`). Only to `DISPATCH_SIM_NUMBER` or a `callable` responder with `consent_calls`, under the same allowlist as calls. A responder alert goes out alongside the app alert and the call, on the same `dispatches` row; the row's `channel` is `imessage` only when no call was placed. After a role is assigned, a follow-up iMessage carries the route and asks for `here` on arrival. The 911 briefing is also sent as text to `DISPATCH_SIM_NUMBER` after it is spoken. The SIP URI adds `;secure=true` (SRTP, per Photon's Twilio cookbook). With messaging on, the briefing TwiML ends with a `<Redirect>` to `/twilio/briefing/{incident_id}?spoken=1`, which sends the text; if that never arrives the text goes 90 s after the call is placed (an engineering timeout, not a guideline). `/photon/webhook` answers 400 on a bad signature and 503 when `PHOTON_WEBHOOK_SECRET` is unset. Shared iMessage lines can only text people who wrote to the line first.

## 3. Realtime and event streams

Published tables (spec §7): `agent_events`, `runs`, `building_scores`, `incidents`, `incident_events`, `dispatches`, `responders`.

### `agent_events` (census console)

`agent` is one of `planner|records|scanner|mapper|outside|fixer`. `kind` and `payload`:

| kind | message example | payload |
|---|---|---|
| `todo` | "Scan 20 gyms first, then offices" | `{todos:[{text, status:"pending"\|"in_progress"\|"done"}]}` (full list each time) |
| `decision` | "Borderline AED at 0.48, checking a second panorama" | `{reason, detection_id?, sweep_id?, options?}` |
| `tool_call` | "walking_time_map(aed)" | `{tool, args}` |
| `result` | "AED worst case 140 s, 38% red" | `{tool?, summary, metrics?}` |
| `warning` | "Budget 90% used, stopping new buildings" | `{code, detail}` |

`message` is always a complete human-readable sentence: the console renders it directly.

### `incident_events` (live timeline)

`actor` is one of `vision|system|desk|responder:<id>|twilio|llm|photon`. `kind` values:

`detected`, `speak`, `verify_result`, `imessage_sent`, `imessage_failed`, `imessage_received`, `confirm_requested`, `confirmed`, `false_alarm`, `voice_check_result`, `classified`, `gate_opened`, `dispatch_sent`, `dispatch_accepted`, `dispatch_declined`, `dispatch_timeout`, `dispatch_released`, `responder_arrived`, `ems_briefed`, `police_notified`, `staff_alerted`, `milestone`, `fall_911_cancelled`, `timer_started`, `timer_fired`, `resolved`.

Payloads the frontends rely on:

- `speak`: `{script_id, text, audio_url, target?:"aed"|...}`. The dashboard uses this to sync the twin fly-through and may also play the audio.
- `confirm_requested`: `{auto_proceed_at?: ts, escalate_at?: ts}` for the countdown.
- `classified`: `{type, modifiers[], scene_safe, hazards[]}`.
- `timer_started`: `{timer, fires_at}`.
- `ems_briefed`: `{briefing_text, ems_door}`.
- `voice_check_result`: `{responsive}`.
- `verify_result`: `{is_emergency, scene_safe, hazards[], modifiers[], error?}` (after the allowlist filter).
- `dispatch_sent`, `dispatch_accepted`, `dispatch_declined`, `dispatch_timeout`, `dispatch_released`: `{dispatch_id, responder_id, role, wave, channel, call_sid?}`.
- `timer_fired`: `{timer}`.
- `imessage_sent`: `{purpose, dispatch_id?, responder_id?, role?, message_id}`; `imessage_failed`: `{purpose, error, ...}`; `imessage_received`: `{reply, dispatch_id, responder_id}`. `purpose` is `alert`, `staff_alert`, `role`, `stand_down` or `briefing`. Timer names are the ones in `agent/DESIGN.md` (`voice_check`, `confirm_auto`, `found_down_escalate`, `wave_{n}`, `fall_911`, `announce_repeat`, `guide_tick`).

Latency metrics on `/live` are computed from `incidents` timestamps only (`collapse_at`, `first_instruction_at`, `confirmed_at`, `ems_notified_at`, `first_accept_at`, ...). One exception: first ring is the earliest `dispatches.sent_at` for the incident with a non-null `call_sid` (the call is placed when the row is written); `agent/` sets `call_sid` on the dispatch row it calls.

### Mobile subscription

The app subscribes to `dispatches` filtered by `responder_id = me`. A new row with `status='sent'` raises the alert. A change to `released` shows the Released screen. The app reads the incident, camera and `camera_routes` rows for directions.

## 4. Python interfaces between packages

Signatures are the contract; bodies belong to the implementing lane. Types are in `shared/types.py`.

```python
# shared/config.py
def get_settings() -> Settings                 # pydantic-settings, cached; every env var in .env.example

# shared/db.py
def get_db() -> supabase.Client                # service-role client, cached
def upload(bucket: str, path: str, data: bytes, content_type: str) -> str   # returns public URL

# shared/llm.py
def complete_json(*, tier: Literal["fast", "reasoning"], system: str, user: list[ContentPart],
                  schema: dict, run_id: str | None = None, max_tokens: int = 1024) -> dict
def get_chat_model(tier: Literal["fast", "reasoning"]) -> BaseChatModel     # for Deep Agents / LangChain
def warm_up() -> None

# shared/events.py
def emit_agent_event(run_id: str, agent: str, kind: str, message: str,
                     building_id: str | None = None, payload: dict | None = None) -> None
def emit_incident_event(incident_id: str, actor: str, kind: str, payload: dict | None = None) -> None

# shared/thresholds.py
def zone(asset_type: str, time_s: float | None) -> Literal["green", "yellow", "red", "unknown"]
def limit_seconds(asset_type: str) -> float    # the red limit expressed as one-way seconds

# data/adapter.py
class DatasetAdapter(Protocol):
    def list_buildings(self, city: str | None = None, types: list[str] | None = None) -> Iterable[BuildingRecord]
    def get_twin(self, building: BuildingRecord) -> list[TwinNode]
    def list_panos(self, building: BuildingRecord) -> list[PanoRef]
    def fetch_pano(self, pano: PanoRef) -> Path          # local cached equirectangular image
    def get_vexcel(self, building: BuildingRecord) -> VexcelInfo | None
def get_adapter() -> DatasetAdapter            # real adapter, or FallbackAdapter if COSTAR_DATA_PATH is unset

# census/core (pure)
def build_graph(nodes: list[TwinNode]) -> nx.Graph
def walking_time_map(graph: nx.Graph, sources: list[str], walk_speed_mps: float) -> dict[str, float]
def shortest_route(graph: nx.Graph, src: str, dst_sweeps: list[str]) -> Route   # path, distance_m
def place_one(graph: nx.Graph, existing: list[str], candidates: list[str],
              limit_s: float, walk_speed_mps: float) -> Placement               # sweep_id, before/after stats
def triangulate(ray_a: Ray, ray_b: Ray) -> tuple[float, float, float] | None
def score_building(coverage: CoverageByType, occupancy_est: int, flags: Flags) -> BuildingScore
def describe_route(graph: nx.Graph, route: Route) -> str                        # "left of the elevators" (no distance)

# census/run.py
def start_run(buildings_target: int, city: str | None, types: list[str] | None, budget_usd: float) -> str
def rerun_building(building_id: str) -> str
def stop_run(run_id: str) -> None

# census/tools/routes.py
def precompute_camera_routes(camera_id: str) -> None    # writes camera_routes (audio_url NULL; agent/io/tts.py fills it)

# census/tools/fixer.py
def propose_fix(building_id: str, asset_type: str = "aed") -> str   # "aed" | "extinguisher"; returns the fixes.id
```

`agent/` calls only `census.run.*`, `census.tools.fixer.propose_fix`, and `census.tools.routes.precompute_camera_routes`. It never reaches into `census/core` directly.

## 5. Storage buckets

| Bucket | Path pattern | Writer | Notes |
|---|---|---|---|
| `crops` | `{building_id}/{detection_id}.jpg` | census Scanner | Equipment crops only. Never a full tile or panorama. |
| `snapshots` | `{incident_id}.jpg` | agent ingest | The one frame sent with `person_down`. Deleted by `/reset`. |
| `audio` | `{camera_id}/{script_id}.mp3` | route precompute / seed | Mirrors the local files in `.cache/audio/`. |
| `outside` | `{building_id}.jpg` | census Outside | Vexcel image, if the license allows storing it. |

Local only, never uploaded: `.cache/panos/`, `.cache/tiles/`, `.cache/checkpoints.sqlite`.

## 6. Speaker scripts

Script IDs are stable and shared by the agent, the audio files and the dashboard:

`voice_check`, `cardiac_main`, `cardiac_cpr_coach`, `cardiac_aed_arrived`, `mod_breathing`, `mod_seizure`, `mod_overdose`, `fall_main`, `unsafe_stay_back`, `all_clear`.

Text comes from the templates in spec §3, verbatim (each em-dash spoken as a comma), in `agent/live/playbooks.py`. The spec has no text for `unsafe_stay_back`, `cardiac_aed_arrived` and `all_clear`; their wording was approved by the team lead on 2026-11-14 and lives in the same file. With no AED route, `cardiac_main` drops its AED sentence. `{naloxone_location}` is the label of the naloxone asset at the end of its route. Placeholders `{landmark}`, `{aed_distance}`, `{aed_directions}`, `{naloxone_location}` are filled per camera from `cameras` and `camera_routes` at pre-render time. `mod_overdose` is rendered only when naloxone is mapped for that camera. `camera_routes.directions` never contains the distance: the template adds it from `distance_m` (spec section 3 wins over the old `describe_route` example).

## 7. Fallback building format (`demo/fallback/building.json`)

```json
{
  "building": { "costar_property_id": "FALLBACK-1", "name": "...", "address": "...", "city": "Houston",
                "lat": 0, "lng": 0, "property_type": "gym", "floors": 2, "size_sqft": 0, "tenants_count": 0 },
  "twin_nodes": [ { "sweep_id": "s1", "floor": 0, "x": 0, "y": 0, "z": 0, "neighbors": ["s2"],
                    "room_type": "lobby", "label": "east elevators", "is_elevator": false, "is_stairs": false } ],
  "panos":  [ { "sweep_id": "s1", "image_uri": "demo/fallback/panos/s1.jpg" } ],
  "assets": [ { "type": "aed", "sweep_id": "s7", "floor": 0, "label": "by the front desk", "source": "manual" } ],
  "vexcel": { "entrances": [], "ambulance_parking": [], "hydrants": [], "image_url": null },
  "camera": { "id": "cam-lobby-1", "sweep_id": "s1", "floor": 0, "landmark": "east elevators" }
}
```

`FallbackAdapter` reads exactly this file. Any placeholder values in it are demo fixtures and must never appear in a census headline number.
