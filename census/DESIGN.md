# census/ design

The offline, agentic half (spec §9.2 to §9.7). A Deep Agent planner decides; plain Python computes.

## Layout

```
census/
  core/            pure functions, no IO (unit-tested offline)
    tiling.py        equirectangular -> perspective tiles; tile pixel -> heading/pitch -> world ray
    triangulate.py   closest point between two rays
    graph.py         build_graph, walking_time_map, shortest_route, stairs-only detection
    scoring.py       red fractions, worst case, people_at_risk, gap_score, ranking
    placement.py     greedy place_one
    occupancy.py     estimate_occupancy
    ems_door.py      pick_ems_door
    directions.py    describe_route (text a stranger can follow)
    docs.py          structured facts -> prompt inputs and fixed wording for documents
  vision/          LLM perception, images in, typed results out, no DB
    first_pass.py    detect_first_pass(tile) -> [{type, bbox, confidence}]
    verify.py        verify_crop(crop, claimed_type) -> {confirmed, reason, blocked_exit}
    prompts.py
  tools/           DB io + agent_events around core and vision; these are the agent's tools
    records.py       get_costar_profile, estimate_occupancy
    scanner.py       tile_pano, detect_first_pass, verify_crop, find_second_view, pin_asset
    mapper.py        build_graph, walking_time_map, flag_routes
    outside.py       get_vexcel, pick_ems_door
    fixer.py         place_one (propose_fix), draft_owner_letter, registry_list, emergency_card
    routes.py        precompute_camera_routes (used by the live path)
    bulk.py          scan_building_bulk: tiling + first pass for a whole building in a worker pool
  agent/
    planner.py       Deep Agent construction: planner prompt, todo list, subagent registry
    subagents.py     the five subagent definitions (name, prompt, tool list)
    prompts.py
  run.py           run lifecycle, budget guard, worker pool, start/stop/rerun
  cli.py           python -m census.cli run|rerun|rank|report
  tests/
```

Tool names and subagent responsibilities are exactly the table in spec §9.2.

## core/ notes

**graph.py**
- Nodes are sweeps, edges are neighbor pairs, weight is 3D Euclidean distance in meters.
- `walking_time_map` is multi-source Dijkstra (`networkx.multi_source_dijkstra_path_length`) divided by walk speed. Unreachable sweeps are omitted from the result (stored as `NULL`).
- Stairs-only: a sweep on a non-ground floor is flagged when its shortest path to any exit must pass a stairs node and no path exists with stairs nodes removed.
- Disconnected components are common in real scans. Report the component count; do not crash.

**scoring.py**
- `red_frac` is the fraction of sweeps in the red zone. Sweep count stands in for floor area; say "of scanned positions" in the UI unless real area per sweep is available.
- `people_at_risk = occupancy_est * red_frac` for the worst gap (spec §9.5).
- `gap_score` weights the AED gap highest. The weights are constants at the top of the file with a comment that they are a product choice, not a guideline.
- Buildings with no AED visible in the scan get `aed_red_frac = 1.0`, `aed_worst_s = NULL` and a flag; the UI wording is "no AED visible in the scan".

**placement.py**
- Greedy over candidate sweeps: for each candidate, recompute the time map with it added; choose the one that minimizes worst case, ties broken by the smallest red fraction.
- Candidates exclude stairs, elevators and sweeps whose `room_type` suggests a private or unsuitable room when that data exists.
- Returns before and after stats for `fixes` and the full proposed time map for `coverage(scenario='proposed')`.
- Performance: one Dijkstra per candidate. Fine for hundreds of sweeps; for very large scans subsample candidates and say so in the rationale.

**tiling.py / triangulate.py**
- 6 to 8 tiles at about 90 degrees FOV with `py360convert`; keep heading and pitch per tile.
- Bbox center -> (heading, pitch) -> unit ray in model space, using the sweep position and the per-sweep rotation from the dataset.
- `triangulate` returns `None` when the rays are near parallel or the closest points are more than a tolerance apart; the caller then pins at the viewing sweep.

**docs.py**
- Builds a facts dict (measured numbers, asset lists, placement, EMS door, address) and the fixed sentences that must not vary ("visible in the scan", "draft, not sent", registry instructions).
- The LLM drafts prose from the facts only. After drafting, a checker confirms every number in the output appears in the facts dict; otherwise regenerate once, then fall back to a plain template.
- The emergency card and registry list are deterministic templates with no LLM.

## vision/ notes

- First pass: fast tier, downscaled tile, strict JSON schema `{items:[{type, bbox, confidence}]}`, types limited to `aed, extinguisher, exit_sign, sprinkler, smoke_detector, first_aid, naloxone`.
- Verify: reasoning tier on the crop (with padding for context), returns `{confirmed, reason, blocked_exit}`.
- Borderline band (config, default 0.35 to 0.6 after verify) triggers the second-view check.
- Privacy: prompts ask for equipment only. Crops are cut from the equipment bbox. If a verify response reports a person filling the crop, discard the crop and keep the detection without an image.
- An open-vocabulary detector can replace the first pass behind the same function signature if a GPU appears.

## tools/ notes

- Every tool: read rows, call core or vision, write rows, emit a `tool_call` and a `result` event, return a short JSON-serializable summary. Tools return summaries, not bulk data: the agent must never have a thousand detections in its context.
- `find_second_view(detection_id)`: among the neighbors of the viewing sweep (and their neighbors), pick the one with the best angular separation that plausibly sees the same spot; render one tile facing it; run first pass + verify there.
- `pin_asset`: merges duplicates (same type within a small radius) so one AED seen from five sweeps becomes one asset with five `detection_ids`.
- `bulk.py`: bounded concurrency (config), resumable via `panos.tiles_done`, checks the budget between batches.
- `routes.py`: for a camera, compute routes from its sweep to the nearest AED, exit, extinguisher and naloxone; write `camera_routes`. It does not render audio; see "Audio rendering" below.

### Audio rendering

`precompute_camera_routes` writes `camera_routes` rows with `audio_url = NULL`. The live side owns audio: `agent/io/tts.py` exposes `render_camera_audio(camera_id)`, which reads the routes, renders every script and fills `audio_url`. The seed step and `POST /reset` call both in order. This keeps the import rule (census never imports agent).

## agent/ notes

- Use the `deepagents` package; check its current API before writing code. The planner has the built-in todo tool; mirror every todo update into `agent_events(kind='todo')` with the full list.
- The planner's own tools are coarse: `list_candidate_buildings`, `scan_building_bulk`, `get_building_summary`, `get_run_status`, plus delegation to subagents. Fine-grained tools belong to the subagents.
- Decisions that must be visible in the console (spec §9.2): scan order, each second-view double-check, each placement, each letter. Emit `decision` events from the tool layer when the agent picks an option, with its stated reason.
- Per-building flow is a guideline in the planner prompt, not hardcoded control flow, but each subagent's output is validated by code before the next step (for example, Mapper refuses to run on a building with no twin nodes and emits a warning).
- Budget: `run.py` exposes `budget_remaining(run_id)`; the planner tool `scan_building_bulk` refuses new buildings when it is exhausted and emits a `warning`. The planner is also told the budget in its prompt, but the code check is the real guard.

## run.py

- `start_run` creates the `runs` row, launches the planner in a background task, returns the id.
- Overnight shape: Records ranks the candidate pool (cheap, no vision), then buildings are processed in ranked batches with bounded concurrency. After each batch: update `runs`, re-rank on measured gaps, checkpoint progress so a crash resumes from `buildings.census_status`.
- `rerun_building` is the stage demo: a one-building run with events paced so the console is readable (config `DEMO_EVENT_DELAY_MS`, default 0).
- Failure policy: a building that errors gets `census_status='error'`, a `warning` event, and the run continues.

## cli.py report

`python -m census.cli report --run <id>` prints the real numbers for the pitch: buildings scanned, panoramas, cost, fraction with an AED red zone, hand-check precision. The headline number comes from here and nowhere else.

## Acceptance

- `pytest census/tests` passes offline (graph, placement, triangulation, scoring on synthetic inputs with known answers).
- `rerun_building(<fallback id>)` writes `coverage` for both scenarios, `building_scores`, one `fixes` row, three `documents`, and a console stream that reads like decisions.
- A 20-building run stays within a small test budget and survives one forced building error.
