# Planted AED for the live demo (Rabinowitz Hall)

Hand-off brief for whoever sets up the demo AED. Read this whole file first.

## Situation

- **Demo building:** Princeton, Julis Romo Rabinowitz Building (the venue). Matterport model `P3S6VUTP3qB` (reachable with the team's Matterport API token). An older public copy, `2K7G7cdukZV`, is not reachable through the API; do not use it.
- **Scan:** 66 sweeps, all panoramas available (cube maps, 6 faces per sweep, up to 4K). 36 sweeps are on "Floor 2" (the atrium level, ground in practice) and 30 on "Floor 3" (the gallery ring). No sweeps on "Floor 1". No Mattertags, almost no room labels.
- **What a manual visual check of 51 of 66 sweeps found (2026-11-14):**
  - AED: **none visible**.
  - Fire extinguisher: one cabinet in the Floor 3 stairwell (Model API location index 44, id `4z3dsh3hzihrqcr8fsxqdkf6c`), sign reads "2.5in fire department valve & fire extinguisher".
  - Exit signs everywhere, pull stations at the arcade gate and stairwell doors, smoke detectors and strobes on all ceilings.
  - Sweeps 51 to 65 (Floor 3) were not checked.
  - These are eyeball observations, not pipeline output. Do not quote them as results.
- **Why plant one:** the live collapse demo (spec section 11, step 6) needs a real route to a real AED. With none visible, we place one ourselves and disclose it.

## The rule (non-negotiable, from CLAUDE.md rules 4 and 16)

A planted AED is a **disclosed demo prop**, never a census finding.
- It must never count toward any census number, headline, city map, ranking or precision figure.
- Anywhere it shows up, it is labeled as placed by the team.
- The judge answer is: "We placed an AED trainer in our own venue scan to test the pipeline end to end."
- Do not fabricate a detection for an object that is not physically there.

## Option A (preferred): physical AED trainer + rescan

1. **Get an AED trainer** (or a real AED cabinet, or at minimum the standard green AED sign with a white heart and lightning bolt plus a wall box). Ask the organizers/venue first; do not borrow the building's own equipment.
2. **Pick the spot.** It has to be realistic, visible from a hallway, and a short walk from the taped-off collapse zone. Candidates near the east elevators / main corridor (Model API location index, sweep id, floor, position x,y,z in meters):
   - index 34, `az0h181td1h01x8x9gxhnp47a`, Floor 2, (1.66, -3.00, -0.03): atrium edge near the main corridor.
   - index 11, `1k478kza39tbfu1uhbttg5ybb`, Floor 2, (0.01, 0.01, -0.03): central atrium.
   - index 42, `0f2a2fyf5iibscursb5gkyu9a`, Floor 2, (-11.03, 0.08, 0.02): by the Gothic arcade gate, next to a pull station. Placing an AED next to existing life-safety gear is realistic.
   - index 19, `w5kacr4ci0d92c5wkzrfs4erd`, Floor 2, (-8.04, -13.05, 0.00): corridor wing.
   Mount it at about 1.2 m, on a wall a camera can see from at least two sweeps (so the second-panorama double-check, spec section 9.3 step 4, can fire).
3. **Rescan only that area** with the Matterport app (Peri plan, spec section 13). Add at least two scan points with a clear view of the AED from different angles.
4. **Wait for processing**, then confirm the new sweeps and panoramas come back from the Model API for the model.
5. **Run the real Scanner** on the new sweeps. It must detect the AED on its own. If it does not, fix the prompt or tiling, not the data.
6. **Record it honestly:** the resulting `assets` row keeps `source='detected'`, and the building or run notes say "AED trainer placed by team on 2026-11-1x for the demo". Exclude this building from census statistics (flag it in `runs.notes` or a `buildings` field; ask the team which before changing the schema).

## Option B (fallback, no rescan): manual owner-provided entry

Use this if there is no trainer or no time to rescan.
1. Pick one candidate spot from the list above.
2. Insert an `assets` row with `type='aed'`, `source='manual'`, `verified=false`, the chosen `sweep_id`, `floor`, and the sweep position as x,y,z. Put "demo AED, placed by team, not in scan" in `label` or `flags`.
3. Compute `camera_routes` from `cam-lobby-1` to it as usual.
4. On screen and in the owner letter it reads as owner-provided, never as detected.
5. Optional: run the Fixer's placement first and use **its** recommended sweep, so the "drop AED" moment and the planted AED are the same spot.

## Data notes for the agent

- Use the Matterport **Model API** (GraphQL at `https://api.matterport.com/api/models/graph`, Basic auth with `MATTERPORT_API_KEY:MATTERPORT_API_TOKEN` from `.env`). Query `model(id){ floors, locations{ id floor position neighbors pano{ skyboxes{ resolution urlTemplate } } } }`. `urlTemplate` has a `<face>` placeholder, faces 0 to 5.
- Model API positions are **z-up**; the Showcase SDK reports **y-up**. Pick one when writing `twin_nodes`.
- `neighbors` are line-of-sight links, not walkable edges: 210 of them cross between floors straight over the open atrium. Keep only short same-floor edges (sweep spacing is about 3 m, so a 5 to 6 m cutoff) and join floors only through stair sweeps, or walking times will be wrong.
- The location index numbers above follow the order of `model.locations` from the Model API; match on `id`, not the index.
- The scan contains many people (hackathon attendees). Never store face crops; equipment crops only.
- Never write keys into code, files or logs.

## Done when

- One AED location exists in the demo data, clearly labeled as team-placed.
- `camera_routes` gives the speaker a real distance and direction ("{n} meters, {directions}") to it.
- The census numbers are unchanged by it.
