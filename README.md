# Within Reach

For every spot inside real buildings in Houston and Los Angeles, Within Reach measures how far you are from the things that keep you alive: an AED, a fire extinguisher, an exit. An AI agent finds the dangerous gaps, ranks them by how many people are at risk, and drafts the fix. When a camera sees someone collapse, the same map tells bystanders where the AED is, alerts nearby trained responders, and tells EMS which door to use.

Built at HackPrinceton Fall 2026.

## Status

Architecture only. No implementation yet. Start here:

| Read | For |
|---|---|
| [CLAUDE.md](CLAUDE.md) | The build spec: behavior, data model, demo script |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module boundaries, layering, key decisions |
| [docs/CONTRACTS.md](docs/CONTRACTS.md) | Every interface that crosses a module boundary |
| [docs/LANES.md](docs/LANES.md) | Subtasks for the five implementing agents |
| `<folder>/DESIGN.md` | File-level plan for that folder |

## Layout

```
shared/      Python: config, database, LLM client, thresholds, event emitters
data/        Python: dataset adapters and loader
census/      Python: the census Deep Agent and the math behind it
vision/      Python: live person-down detection (standalone)
agent/       Python: FastAPI + deterministic LangGraph live response
dashboard/   Next.js: city map, building twin, agent console, live panel
mobile/      Expo: responder app
supabase/    migrations and seed
demo/        fallback building, clips, backup recordings, Peri materials
```

## Safety notes

- This project never calls real 911. The demo uses a simulated dispatcher phone.
- "No AED visible in the scan" does not mean a building has no AED.
- The database policies are a demo auth bypass, not production security.
- Every number shown comes from our own runs.
