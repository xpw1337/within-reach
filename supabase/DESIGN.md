# supabase/ design

## Files

| File | Status | Purpose |
|---|---|---|
| `migrations/0001_init.sql` | written | The schema from spec §7, unchanged. Ask before editing. |
| `migrations/0002_demo_policies.sql` | written | Demo auth bypass (spec §6). |
| `migrations/0003_storage.sql` | written | Buckets from `docs/CONTRACTS.md` §5. |
| `migrations/0004_run_cost.sql` | written | `add_run_cost(run_id, delta)`: atomic increment of `runs.est_cost_usd` for `shared/llm.py` metering. A function only, no table change. |
| `seed.sql` | written | Demo rows from spec §12. Fictional 555-01xx phones only. |
| `seed_demo.sql` | written | The same eight responders and a placeholder caller of record on the demo building (`DEMO-RABINOWITZ`, camera `cam-atrium-1`). The last seed file run decides where the responders are. |
| `seed.local.example.sql` | written | Template for the git-ignored `seed.local.sql` with real teammate numbers. |

## 0002_demo_policies.sql

- Enable RLS on every table, then add permissive policies for the `anon` role:
  - `select` on all tables.
  - `insert` and `update` on `responders` only (the mobile app manages its own row).
- All other writes go through the service-role key held by Python.
- Put a comment at the top: demo only, not production security.

## 0003_storage.sql

- Public-read buckets: `crops`, `audio`, `outside`.
- `snapshots`: public-read for the demo so the dashboard can show the incident frame; noted as something a real deployment would lock down.

## seed.sql (spec §12)

- `cameras`: `cam-lobby-1` mapped to a sweep in the demo building, landmark "east elevators". Until a real building is chosen it points at the fallback building, which `python -m data.load --fallback` inserts.
- `responders`: teammate A (staff, CPR, callable), teammate B (public, callable), 4 non-callable seeded responders, 2 outdoor responders (stretch). Phone numbers are placeholders in the committed file; real numbers go in an untracked `seed.local.sql`.
- `buildings.monitoring_callback`: a teammate, also in `seed.local.sql`.
- No census results in the seed: coverage, scores and fixes come from running the pipeline on the fallback building, so the demo never shows hand-typed numbers.

## Order of operations for a fresh project

```
apply migrations 0001..0004
python -m data.load --fallback
psql < supabase/seed.sql   (and seed.local.sql)
# live demo on Rabinowitz Hall instead (CAMERA_ID=cam-atrium-1 in .env):
python -m data.load --file demo/rabinowitz/building.json
psql < supabase/seed_demo.sql   (then seed.local.sql)
python -m census.cli rerun --building <fallback id>     # coverage, scores, fix, documents, camera_routes
# agent startup renders camera audio if missing
```

## Indexes to consider (add in a later migration if queries are slow)

`agent_events(run_id, id)`, `detections(building_id, status)`, `coverage(building_id, scenario, asset_type)`, `dispatches(responder_id, status)`, `incident_events(incident_id, id)`.
