# Next to-dos (after the offline build)

Written 2026-11-14 after pulling `b18ee15`. Status detail is in `docs/PROGRESS.md`.

## Where we are

- All five lanes are coded and pass offline: 339 Python tests pass (2 skipped without the vision extra), the dashboard typechecks, builds and passes 31 tests, the mobile app typechecks.
- **Nothing has run against a real database, a real LLM, a real phone call, a real camera or a real building yet.** Every remaining risk is in integration.
- Side test by the team: AEDs were not visible in any of 10 Matterport models checked. Decision: plant simulated AEDs in specific demo buildings (section 2).

## 1. Unblock integration (people, do these first)

| # | To-do | Unblocks |
|---|---|---|
| P1 | Put the hosted Supabase keys and `SUPABASE_DB_URL` in the root `.env`; apply migrations 0001 to 0004 | every end-to-end check |
| P2 | Add an Anthropic API key or Bedrock credentials (request Bedrock model access now if using it) | Scanner, Deep Agent, owner letters, live scene verify |
| P3 | Confirm dataset access: where the Matterport models, CoStar records and Vexcel data live and how to pull them | 1.4, 1.5, 1.7, 1.8 |
| P4 | Twilio account, a number, `DISPATCH_SIM_NUMBER`, a tunnel URL in `PUBLIC_BASE_URL` | 4.6 |
| P5 | `supabase/seed.local.sql` with real teammate phone numbers (untracked) | calls and app alerts |
| P6 | `mobile/.env` with the four `EXPO_PUBLIC_*` values | phone testing |

## 2. Planted AEDs (new work)

The spec's rule is that only real numbers from our runs reach the UI, slides or Devpost. Planted AEDs are compatible with that only if they can never be mistaken for a finding. The design:

**Marking.** A planted AED is an `assets` row with `source='manual'` and `'simulated'` in `flags`. No schema change. They come from one committed file, `demo/planted_assets.json` (building, sweep, label), loaded by a `data.load --plant` command, so the full list of what we planted is reviewable.

**What planted AEDs may be used for**
- The live demo: the route in the speaker script, the fly-through, the responder's AED-runner directions.
- Showing the walking-time heatmap on a demo building, labeled as simulated.

**What they must never touch**
- The headline number, the city map's AED layer, `census.cli report`, `building_scores` ranking across the city.
- The registry list (it is "AEDs visible in the scan"; a planted one is not).
- Any owner-letter sentence about equipment found in the scan.

**Recommendation: plant as few as possible.** Two things reduce how much simulation the pitch carries:
1. The drop-AED moment (demo step 4) does not need a planted AED. On a building with no AED visible in the scan, the agent proposes the first one: "no AED visible in the scan" becomes "worst case X s round trip". That is entirely real.
2. Only the live demo building needs a planted AED, because the speaker has to send someone to an AED that exists.

**Pitch consequences (need team sign-off, this changes demo script steps 2 and 4)**
- The headline moves to extinguishers and exits, which are real detections. The spec planned for this at CP0 ("if AEDs are rarely visible, extinguishers and exits carry the census").
- The AED finding we can state is the real one: "no AED visible in the scan in N of N models checked", with N from an actual run, and the reminder that not visible is not the same as absent.
- On stage, say the live demo's AED is simulated. Judges asking "how accurate are the detections" will find out anyway.

| # | To-do | Owner |
|---|---|---|
| S1 | `demo/planted_assets.json` format, `data.load --plant`, tests | Agent 1 |
| S2 | Exclude `simulated` assets from scoring, ranking, `report`, the registry list and owner-letter facts; keep them for `camera_routes` | Agent 2 |
| S3 | "Simulated AED (demo)" marker and legend on the heatmap, twin and live page; city map AED layer ignores them | Agent 3 |
| S4 | Confirm the live path reads routes built from simulated assets; nothing in the 911 briefing or handoff card presents it as a detected device | Agent 4 |
| S5 | Team picks the live demo building and the sweep for its planted AED and for `cam-lobby-1` | people |

## 2a. Live demo building (chosen 2026-11-14)

**Princeton, Rabinowitz Hall.** Matterport model `P3S6VUTP3qB` (the older public copy `2K7G7cdukZV` is not reachable through the API; see `demo/PLANTED_AED.md`). This answers S5's building choice; the sweeps are still to pick.

What follows from that choice:

- **It is not a census building.** It is in Princeton, not Houston or LA, and has no CoStar record. Load it with `costar_property_id = 'DEMO-RABINOWITZ'` and `city = 'Princeton'`, and exclude the `DEMO-` prefix from the headline, rankings and `report` the same way `FALLBACK-` is excluded today. The census "N buildings" never includes it.
- **Prefer the real AED over a planted one.** If the team is in or near the building, find its actual AED, extinguishers and exits and enter them at their true sweeps as `source='manual'`, verified in person. Then the live demo uses a real device location and nothing in it is simulated. Plant a `simulated` AED only if no real one can be located.
- **No Vexcel data is expected for it.** The EMS door is entered by hand from the real entrance, marked as manually chosen.
- **The scan contains people.** If the Scanner runs on it, the no-face-crops rule applies in full; check the stored crops by eye.
- **Loading needs a new path.** There is no dataset record, so the sweep graph (positions, neighbors, floors) has to come from the Matterport SDK for this one model. Needs `MATTERPORT_SDK_KEY`.

| # | To-do | Owner |
|---|---|---|
| D1 | Export the sweep graph for `P3S6VUTP3qB` through the Matterport Model API into the fallback-building JSON format (`demo/rabinowitz/building.json`); load it with the existing loader | Agent 1 |
| D2 | `DEMO-` prefix excluded from headline, rank and report | Agent 2 |
| D3 | Walk the building: note the real AED, extinguishers, exits and the best ambulance entrance, each matched to a sweep in the model | people |
| D4 | Pick the camera position: the sweep for `cam-lobby-1` and a landmark a stranger would recognize (replaces the placeholder "east elevators") | people |
| D5 | Enter D3 and D4 into `demo/rabinowitz/building.json`; rerun the census on it; precompute routes and audio | Agent 1 + 2 |
| D6 | Dashboard twin embed pointed at this model; check the fly-through to the AED | Agent 3 |

## 3. First integration pass (as soon as P1 and P2 are done)

In this order, fixing what breaks before moving on:

1. Apply migrations; `python -m data.load --fallback`; run `supabase/seed.sql`.
2. `python -m census.cli rerun --building <fallback id>`: coverage, scores, fix, documents, camera routes, with the console streaming on the dashboard.
3. Start `agent/`; check `/health`; confirm audio renders for `cam-lobby-1`.
4. `/simulate/cardiac`: audio under 1 s, confirm from `/live`, dispatch row, handoff card. Then `/simulate/fall`.
5. Dashboard: all four pages against real rows; Realtime updates without refresh.
6. Mobile on a real phone: onboarding, alert alarm, accept, release.

This is checkpoint CP1 minus the real building.

## 4. Real data (needs P3)

| # | To-do | Owner |
|---|---|---|
| R1 | 1.4: inspect the dataset, write `data/README.md` | Agent 1 |
| R2 | 1.5: real adapter and loader | Agent 1 |
| R3 | 1.7 on one real building, then 1.8: hit rates for extinguishers and exit signs on 50 to 100 scans, dollars and seconds per building, 30 samples for hand-check | Agent 1 |
| R4 | Label the 30 samples on `/handcheck`; record the precision | people |
| R5 | Set `CENSUS_BUDGET_USD` from R3's cost per building | people |
| R6 | 20-building agent run (CP2), then the overnight run (CP3) | Agent 2 |

## 5. Live demo hardening (needs P4, P5)

| # | To-do | Owner |
|---|---|---|
| L1 | 4.6: real responder call with digit accept, 911 briefing to the sim phone, hangup on release | Agent 4 |
| L2 | 5.4: record the six vision clips; tune thresholds | Agent 5 + a person |
| L3 | Real collapse on the webcam end to end; 4.8 latency numbers | Agent 4 + 5 |
| L4 | Backup recording #1 | people |

## 6. Open checks carried over

- Occupancy factors against IBC 2021 Table 1004.5 (marked unverified in code).
- The three red-zone thresholds (spec section 20).
- Peri gym visit and scan (spec section 13).
- Seeded responders go stale after 10 minutes: re-run the seed right before the demo.
- Repo is private; make it public before the Devpost deadline.
