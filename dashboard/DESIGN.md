# dashboard/ design

Next.js (App Router) + Tailwind + TypeScript (spec §9.12). Reads Supabase directly with the anon key, subscribes to Realtime, and sends commands to the agent API. It computes nothing about safety itself: zones come from `coverage` plus `GET /config/thresholds`.

## Layout

```
dashboard/
  app/
    layout.tsx               shell: nav, run status chip, AgentConsole pinned on every page
    page.tsx                 "/" city map
    building/[id]/page.tsx   building twin page
    handcheck/page.tsx       label sampled detections
    live/page.tsx            live incident panel
  components/
    console/AgentConsole.tsx, TodoList.tsx, EventRow.tsx
    map/CityMap.tsx, GapToggle.tsx, RunProgress.tsx, Headline.tsx
    building/FloorHeatmap.tsx, FloorPicker.tsx, EquipmentToggle.tsx, ScenarioToggle.tsx,
             DropAedButton.tsx, FixSummary.tsx, FlagsList.tsx, CostarFacts.tsx,
             OutsidePanel.tsx, DocumentsTab.tsx, MatterportTwin.tsx
    handcheck/CropCard.tsx, PrecisionBadge.tsx
    live/IncidentCard.tsx, ConfirmBar.tsx, LatencyMetrics.tsx, Timeline.tsx,
         ResponderList.tsx, EmsDoorPanel.tsx, HandoffCard.tsx, SimulateButtons.tsx, RouteFlythrough.tsx
  lib/
    supabase.ts              browser client
    api.ts                   typed wrappers for every endpoint in docs/CONTRACTS.md §2
    types.ts                 row types (generate with the Supabase CLI, do not hand-write)
    thresholds.ts            fetch + cache /config/thresholds; zone(assetType, timeS)
    copy.ts                  fixed wording: "visible in the scan", approximations note, estimate labels
    hooks/useRealtimeTable.ts, useRun.ts, useAgentEvents.ts, useIncident.ts, useCoverage.ts
```

Env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_AGENT_URL`, `NEXT_PUBLIC_MATTERPORT_SDK_KEY`.

## Pages

**`/` City map**
- Leaflet with OpenStreetMap tiles (no key). Houston / LA switch. One marker per building with a `building_scores` row, colored by the selected gap (AED / extinguisher / exit) from that building's red fraction.
- Headline number and run progress (buildings done, panoramas, dollars) from the latest `runs` row and an aggregate over `building_scores`. Show `--` until a run has results. No hardcoded figures.
- Ranked list beside the map (by `rank`), click through to the building.
- With thousands of buildings use marker clustering or canvas rendering.

**Agent console (every page)**
- Realtime on `agent_events` for the latest run, plus the last 100 rows on load. The latest `todo` event renders as the planner's checklist; other kinds stream as rows tagged with the agent name. Decisions are visually distinct: this component is what makes the product read as an agent.
- Collapsible, never unmounted between pages (it lives in the layout).

**`/building/[id]`**
- `FloorHeatmap`: SVG, one circle per sweep at (x, z), edges drawn faintly, colored by `zone()`. Asset markers by type. Floor picker. Equipment toggle (AED / extinguisher / exit). This must work with no Matterport SDK.
- Drop AED moment: `ScenarioToggle` switches `coverage` from `current` to `proposed`; colors animate; the proposed asset marker drops in; `FixSummary` shows before and after from the `fixes` row ("worst case X s -> Y s; red area A% -> B%"). If no fix exists, the button calls `POST /census/buildings/{id}/fix` and waits for the row via Realtime or polling.
- `MatterportTwin`: Showcase SDK embed with markers for assets, loaded lazily, hidden entirely if the key or model ID is missing.
- Flags (stairs-only, blocked exits, no AED visible in the scan), CoStar facts, outside panel (Vexcel image, EMS door, parking, hydrants), documents tab rendering `content_md` with a print stylesheet for the emergency card.
- "Rerun live" button -> `POST /census/buildings/{id}/rerun` for demo step 3.

**`/building/[id]/route`** (responder route in 3D, opened from "View route in 3D" in the app)
- Query: `camera` (camera id), `leg` (`to_aed` or `to_person`), `role` (dispatch role), `from` (the helper's start sweep in the app), `geo` (the building's GPS calibration from the app: `originLat,originLng,rotationDeg,tx,tz`). All optional; unknown values are ignored.
- Follow the app's dot (with `follow=<dispatch id>`): the page subscribes to the Realtime broadcast channel `follow:<dispatch id>` (event `pos`, payload `{x, z, leg}` in plan meters, sent by the app's floor plan as the step-tracked dot moves). Each dot goes to the scan point nearest the helper on the leg's floor (`followStep` in `lib/routePlan.ts`): along the path when it is on it, else the leg is re-planned from there, so the view is always where the helper is and never pulled back to the route from the person; a `leg` different from the page's switches the leg (for example after "I have the AED"). Once a dot arrives, GPS follow stops.
- Follow mode (with `geo`, until the app's dot arrives): the browser's GPS (`watchPosition`) is converted to the plan with the app's formula (`lib/georef.ts`, checked equal to mobile/lib/georef.ts) and the view moves to the route's nearest scan point, only when it is at least 1 m closer than the current one. GPS is taken as accurate (team lead, 2026-11-15). "Walk it" is a paced walk: each segment flies for as long as walking it takes (1.4 m/s, or 0.8 m/s with Slow), facing the next point (rotation y = atan2(-dx, -dz), measured on the model), and the counter advances per point; Stop ends it. Back / Next / Walk it pause following; "Follow me" resumes it.
- One leg at a time: to the AED, then "I have the AED" switches to the way back to the person. Without `from`, the AED leg starts at the person and uses the camera's census route (`camera_routes.path`), so the distance matches the speaker; with `from`, the shortest walk over `twin_nodes.neighbors` (`lib/routePlan.ts`).
- `MatterportTwin` with a "Person down" tag at the camera sweep (and "Your start"), Back / Next one scan point at a time, or "Walk it" along the rest of the leg. The SVG plan with the same route is the fallback and the "Plan" toggle. A team-placed AED keeps its demo label and the dashed-outline note.

**`/handcheck`**
- Loads `GET /census/handcheck?n=30`; one crop at a time with Correct / Incorrect / Unsure (keyboard shortcuts). Shows "x / y correct" from the summary endpoint, real counts only.

**`/live`**
- Subscribes to `incidents`, `incident_events`, `dispatches`; shows the open incident or an idle state.
- `ConfirmBar`: CONFIRM / FALSE ALARM with the countdown from the `confirm_requested` event.
- `LatencyMetrics`: first instruction and first ring, computed from `incidents` timestamps.
- `RouteFlythrough`: on a `speak` event with `target`, animate the route from the camera sweep along `camera_routes.path` on the SVG plan; drive the Matterport camera too when available.
- EMS door panel, responders with roles and statuses, handoff card on resolve, milestone buttons (CPR started, AED arrived) for the desk, Simulate and Reset buttons.

## Rules

- Wording for missing equipment comes from `lib/copy.ts` only.
- Thresholds are labeled approximations wherever a zone legend appears.
- Every number on screen traces to a row. Loading and empty states show `--`, never sample figures.
- Realtime can drop on venue Wi-Fi: `useRealtimeTable` refetches on reconnect and on tab focus.

## Acceptance

- With only the fallback seed: all four pages render, the heatmap toggles scenarios, the console streams when a row is inserted by hand, `/live` follows a simulated incident end to end.
- Lighthouse is not a goal; a projector at 1080p is. Check the layout at that size.
