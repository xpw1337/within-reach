# demo/ design

Everything needed when something else fails, plus the Peri materials.

```
demo/
  fallback/
    building.json      one hand-built building (format: docs/CONTRACTS.md §7)
    panos/             optional: a few panoramas so the Scanner can be shown on it
  clips/               short videos + expected-events JSON for vision replay tests
  frames/              stock frame used by /simulate/cardiac
  recordings/          backup demo videos (git-ignored; keep on two laptops and a drive)
  peri/                gym scan notes, recommended AED spot, emergency card, staff quote / photo (with permission)
```

## Fallback building requirements

Small but exercising every feature: about 30 sweeps on 2 floors, one stair and one elevator connecting them, 1 AED placed so the far end of floor 2 is clearly red, 3 extinguishers, 2 exits, a labeled sweep "east elevators" for `cam-lobby-1`, and a Vexcel block with two entrances so `pick_ems_door` has a choice.

It is a fixture. It is excluded from every headline count (`costar_property_id` starts with `FALLBACK-`, and the census report filters on that).

## Backup recordings

- #1 at CP2, final at CP5 (spec §10). Record the full 3:00 script, screen plus room audio.

## Peri (spec §13)

Store only what the staff member agreed to share. A photo or quote needs their explicit permission, noted in `peri/README.md`.
