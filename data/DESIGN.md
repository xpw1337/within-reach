# data/ design

Dataset adapters and the loader (spec §9.1). This is the first thing built: nothing else can use real buildings until it works.

`data/README.md` does not exist yet on purpose. It is a deliverable: written after inspecting the real CoStar track dataset, describing what is actually there.

## Files

| File | Purpose |
|---|---|
| `README.md` | (to write) Fields per building, how to get sweeps, positions, neighbors, room types and panorama images, what Vexcel gives, access limits, one full sample building. |
| `adapter.py` | `DatasetAdapter` protocol and `get_adapter()` (see `docs/CONTRACTS.md` §4). |
| `costar.py` | `CoStarAdapter`: the real implementation, shaped by what inspection finds. |
| `fallback.py` | `FallbackAdapter`: reads `demo/fallback/building.json`. |
| `load.py` | CLI: normalize adapter output into `buildings`, `twin_nodes`, `panos`. `--file <path>` loads any building file in the fallback format (for example `demo/rabinowitz/building.json`). |
| `matterport.py` | CLI: export a Matterport model through the Model API into the fallback format (the live demo venue, `DEMO-RABINOWITZ`). Walkable edges only: same floor within 6.0 m, floors joined through stair sweeps. |
| `inspect_dataset.py` | Throwaway exploration script whose output feeds `README.md`. Keep it in the repo. |
| `raw/` | Git-ignored local dataset files. |

## load.py

```
python -m data.load --fallback
python -m data.load --city Houston --types gym,office --limit 100
python -m data.load --ids <costar_property_id> ...
```

- Idempotent: upsert on `buildings.costar_property_id` and on the `twin_nodes` / `panos` primary keys.
- Neighbors must be symmetric after load (if A lists B, B lists A). Fix asymmetry here and log a count.
- Sets `is_stairs` / `is_elevator` from whatever the dataset offers (tags, room types, labels). If the dataset has nothing, infer stairs from an edge whose endpoints differ in `floor`, and record that this is an inference in `README.md`.
- `floor` must be an integer per sweep. If the dataset only gives heights, cluster `y` into floors.
- Does not download panoramas. `panos.image_uri` stores where the image can be fetched; `fetch_pano` downloads lazily into `.cache/panos/`.
- With `--fallback`, also inserts the fallback `assets` and `cameras` rows so every downstream screen works without the Scanner.

## Panorama fallback

If panoramas cannot be downloaded in bulk, implement `fetch_pano` with Matterport SDK screenshots per sweep (slower) and say so in `README.md`. The interface does not change.

## Things inspection must answer (write them into README.md)

1. Is there a stable building ID that joins CoStar records, Matterport models and Vexcel data?
2. Sweep graph: are neighbors given, or must they be derived from positions and visibility?
3. Panorama format and resolution; equirectangular or cube faces? Per-sweep heading offset (needed to turn tile heading into a world-space ray)?
4. Are there existing Matterport tags (some scans already tag AEDs or exits)? They would become `assets(source='tag')`.
5. Vexcel: structured entrances, parking and hydrants, or imagery only? If imagery only, the Outside subagent needs a vision step (ask before adding it).
6. Rate limits and total size: how many buildings can be pulled per hour?

## Acceptance

- `data/README.md` exists and answers the six questions with a real sample.
- `python -m data.load --fallback` and a real 50-building load both succeed twice in a row with no duplicates.
