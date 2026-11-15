# mobile/ design

Expo Go responder app (spec §9.11). Foreground only this weekend: no push notifications, no background location.

## Layout

```
mobile/
  app/                     expo-router
    _layout.tsx              providers; redirects to onboarding if no local profile
    onboarding.tsx
    index.tsx                Home: on-duty switch, status, last location time
    alert/[dispatchId].tsx   Alert: role, distance, directions, map, Accept / Can't help, countdown
    cpr.tsx                  CPR guide: 110 bpm metronome, spec §3 wording, AED steps, AED help button
    aed-help.tsx             AED help: one step at a time, large text, spoken on the phone (expo-speech)
    calibrate.tsx            hidden: georeference calibration (long press on the Home title)
    released.tsx
  components/
    FloorPlan.tsx            indoor plan (react-native-svg) and the walking helper dot
    CalibrationPlan.tsx      calibration plan: numbered spots, the spot to stand on, GPS dot, north
  lib/
    supabase.ts              client from EXPO_PUBLIC_SUPABASE_URL / ANON_KEY
    api.ts                   accept, decline, arrived, milestone (agent API); quiet one-retry helper
    floorPlan.ts             floor graph, shortest paths, simulated start sweep, plan for an alert
    stepWalk.ts              pure: step readings -> steps on a leg -> meters along it, glide smoothing
    useStepWalk.ts           per leg: pedometer (expo-sensors) or the timed walk fallback
    georef.ts                pure: lat/lng <-> plan (x, z), calibration solve, GPS start accuracy rule
    georefDefaults.ts        committed calibrations per building (only from a real calibration on site)
    georefStore.ts           calibrations and recorded spots in AsyncStorage; GPS recording and fresh fix
    calibration.ts           calibration screen data: building, sweeps, reference spots (read only)
    useLiveFix.ts            live GPS watch for the calibration screen (accuracy, precise location)
    useHelperStart.ts        first leg's start: GPS, a tap on the plan, or the simulated start
    speech.ts                on-device speech, audible with the iOS silent switch on
    aedHelp.ts               "GIVE ME HELP WITH AED": milestone + open the AED help screen
    profile.ts               responder id + profile in AsyncStorage
    location.ts              foreground watch -> responders.last_lat/lng, last_seen_at
    alarm.ts                 looped alarm sound + haptics, start/stop
    useDispatches.ts         Realtime subscription filtered to my responder id
    copy.ts                  privacy and Good Samaritan lines, CPR wording (verbatim from the spec)
  assets/alarm.mp3
```

Env: `EXPO_PUBLIC_SUPABASE_URL`, `EXPO_PUBLIC_SUPABASE_ANON_KEY`, `EXPO_PUBLIC_DASHBOARD_URL`, `EXPO_PUBLIC_AGENT_URL` (add to `.env.example`). The agent URL must be reachable from the phone (the tunnel URL, not localhost).

## Flows

**Onboarding**: name, phone, CPR-trained, role, building; two consents (location while open, calls). Shows the privacy line and the Good Samaritan line from the spec, verbatim. Upserts a `responders` row and stores its id locally.

**Home**: on-duty toggle (`responders.on_duty`); starts the foreground location watch, writing `last_lat/lng` and `last_seen_at` at most every 15 s. The live agent requires `last_seen_at` within 10 minutes, so the app must be open.

**Alert**: a new `dispatches` row for me with `status='sent'` navigates here, starts the alarm and haptics.
- Shows role once assigned, distance, text directions from `camera_routes`, a map (`react-native-maps`) with the building and my position, and "View route in 3D" opening `EXPO_PUBLIC_DASHBOARD_URL/building/{id}/route` in the browser, with the camera, the current leg, the dispatch role and the helper's start sweep in the query (dashboard/DESIGN.md). The start is where the phone is: the plan's start when already set (GPS or tap), else a fresh GPS fix snapped to the scan with the building's calibration and the same accuracy and distance limits as the GPS start; with no usable fix the 3D walk starts at the person.
- Accept -> `POST /dispatches/{id}/accept`; the response carries the role (`patient` or `aed_runner`) or `released`.
- Can't help -> decline.
- 20 s countdown from `sent_at`; at zero the screen closes (the agent marks the timeout).
- After accept: see "Indoor plan" below for the runner's two steps; others tap "I'm here" -> `arrived`, then the CPR guide.
- A Realtime update to `released` at any time stops the alarm and shows Released.

**Indoor plan (approved demo flow)**: when the building has `twin_nodes` and the camera's sweep is
among them, the Alert screen draws the camera's floor from x and z (y is up) instead of the outdoor
map: neighbor edges faintly as the walkable area, the person (camera sweep), the AED (`assets`
`type='aed'`, `source != 'proposed'`; labeled "Demo AED (placed by team)" when `flags` has
`simulated`) and the route. Without an AED or an AED route: the person only, plus "No AED route is
mapped for this spot", and no AED steps. Without twin nodes: the outdoor map as before.
- Helper dot start (first leg only: start -> AED for the runner, start -> person for everyone else),
  decided once per alert after Accept by `lib/useHelperStart.ts`. No dot is drawn while it is
  decided; the buttons work throughout.
  1. **GPS start**, only when the building has a georeference calibration (see "Georeference"
     below) and `lib/location.ts` already has foreground permission (status `watching`). One fresh
     fix (`Accuracy.Highest`, `START_FIX_TIMEOUT_MS` 4 s, no prompt) is converted to plan (x, z). It
     is used only if the phone reports an accuracy no worse than `MAX_START_ACCURACY_M` (15 m) and
     the point is within `MAX_SNAP_DISTANCE_M` (15 m) of a sweep on the camera's floor. Both are
     judgment calls for this demo, not standards. It snaps to the nearest sweep on that floor that
     can reach the leg's target over the floor graph; the leg is the shortest path from there.
     The plan shows "Checking GPS for your start position..." meanwhile.
  2. **Tap start**, when the GPS start is not used for any reason (no calibration, no permission,
     no fix in time, no accuracy reported, accuracy too poor, off the map): "Tap the map where you
     are" above the plan. A tap snaps to the nearest sweep that can reach the target. The prompt
     waits `TAP_START_WAIT_MS` (8 s).
  3. **Simulated start**, when no tap comes in time or the helper moves on with a button:
     `pickStartSweep` as before. Walking out from the AED sweep, the sweep 2 or 3 hops away that is
     farthest from the person (graph distance) among those farther from the person than the AED;
     else the AED's neighbor farthest from the person; else the AED sweep. Ties go to the smaller
     sweep id.
  Leg 2 (AED -> person) is unchanged, and the AED stays where the data puts it whatever the
  helper's position.
- Labels under the plan. Simulated start: one line, exactly as before ("Position simulated for the
  demo" or "Position estimated from your steps"). GPS or tapped start: two short lines, the start
  first ("Start position from GPS (accurate to about {n} m)", `n` the phone's own reported accuracy
  rounded to a meter, or "Start position set by you"), then the movement ("Movement estimated from
  your steps" or "Movement simulated for the demo"). Movement is worded as movement so a real start
  never reads as simulated and a timed walk never reads as GPS. "No steps counted yet..." is a third
  line when it applies. The start line stays for the whole first leg; the accuracy is the one at the
  start and is not updated as the helper walks.
- How the dot moves, decided once per leg when the leg starts (`lib/useStepWalk.ts`):
  - **Step tracking** (`expo-sensors` Pedometer): labeled "Position estimated from your steps". Each
    counted step moves the dot `STRIDE_LENGTH_M` (0.7 m, in `lib/stepWalk.ts`: a commonly cited
    average adult step, an unverified approximation, not measured for this user) along the leg,
    clamped to the leg's end. Standing still keeps the dot still. Step reports can arrive in batches,
    so the dot glides to each new distance over `GLIDE_MS` (1 s) instead of jumping; a batch that
    arrives mid-glide continues from where the dot is. The dot never moves backwards.
  - **Baseline**: every leg opens its own pedometer subscription (removed when the leg changes, the
    dispatch is released or the screen unmounts). Its readings are cumulative from when it started.
    iOS: the baseline is 0 (CoreMotion counts from the subscription's start date). Android: the first
    reading is the baseline, because the step counter is an on-change sensor that reports once right
    after it is turned on; at worst this drops the leg's first real step.
  - **Timed walk fallback**, labeled "Position simulated for the demo": exactly the old behavior,
    1.4 m/s from the leg's first point, stopping at the end. Used when the platform is web, the
    pedometer is not available (`isAvailableAsync` false, an error, or no answer within 3 s), or
    motion permission is not granted. This is always the case in Expo Go on Android (see Notes).
  - Once a leg is on step tracking it stays on it. If no step is reported for 10 s, the plan adds "No
    steps counted yet. Use the button below when you get there." and the dot stays put; it never
    switches to the timer mid-leg, which would move the dot while the person stands still.
  - Motion permission is requested when the first leg starts (after Accept), not at app launch, with
    the standard OS prompt. Later legs re-check it without prompting again.
  - After "I'm with the person" the dot sits on the person with no position line (a button put it
    there).
- AED runner: leg 1 start -> AED, then "I have the AED" (`milestone aed_picked_up`), leg 2
  AED -> person (the census route reversed), then "I'm with the person" (`arrived` with
  `with_aed: true`), then the big "GIVE ME HELP WITH AED" button (`milestone aed_help_started`)
  opening the AED help screen.
- Patient and staff: start -> person, "I'm here" (`arrived`), then the CPR guide, which also offers
  the AED help button.
- The buttons drive the state, not the dot; each tap snaps the dot to that point. Milestone and
  arrived calls never block the screen: the next step shows at once and a failed call is retried
  quietly once.

**Georeference** (`lib/georef.ts`, pure, checked by `npm run check:georef`): lat/lng to plan
(x, z) per building. Local east/north meters from an origin (equirectangular, fine over a
building), then a rotation, then a translation; scale stays 1 (the scan is in meters):
`x = tx + cos(r) e - sin(r) n`, `z = tz - (sin(r) e + cos(r) n)`.
- Handedness is fixed, not fitted. `data/matterport.py` maps the Model API's z-up position to the
  y-up SDK frame as (x, z, -y), which has determinant +1, and the SDK frame (three.js) is
  right-handed, so the Model API frame is right-handed z-up and its horizontal axes are a plain
  rotation of (east, north). Stored z is minus the Model API y, so (east, north) -> (x, -z) is a
  rotation and (east, north) -> (x, z) is a rotation plus a flip. The plan is drawn x right, z down,
  so it is a true top view: rotated, never mirrored (with r = 0 it would be north up, east right).
- Solve: 2D least-squares rotation + translation (Procrustes without reflection) from 2 or more
  spots, origin at the mean of the fixes, unweighted. With 3 or more spots it also reports the RMS
  of the mirrored fit as a diagnostic only.
- Where a calibration comes from: AsyncStorage on the phone (`within-reach.georef.v1.<building id>`,
  saved by the calibration screen with its date) wins over `lib/georefDefaults.ts` (keyed by
  `costar_property_id`, else building id; filled only from a real calibration on site). The demo
  building (`DEMO-RABINOWITZ`) has one, recorded 2026-11-14 from 4 spots, 3.64 m RMS. With neither,
  the GPS start is off. No database writes and no schema change.

**Calibration** (`app/calibrate.tsx`, hidden: long press about 1 s on the Home title; not in the alert
flow). A step-by-step flow with one big button pinned at the bottom of every step and all wording in
`lib/copy.ts`. Four views:
- **Overview.** The building (the profile's, or searched). First the status: "Already calibrated"
  with the date, spot count and typical error of the calibration in use (the team's committed one,
  or this phone's with a remove button), or "Not calibrated yet" with what that means for alerts.
  Then what calibration does, the plan with the reference spots numbered (each camera's sweep, the
  patient spot; each AED's sweep; then every other labeled sweep), the list of spots by name (sweep
  label, else the camera's landmark), and the setup (Precise Location, how to hold the phone). Button:
  "Start calibration", "Calibrate again" or "Continue at spot n of N"; "See the result" when all are
  recorded.
- **One spot** ("Spot 2 of 4", numbered circles to jump, green when recorded). The spot's name and
  why it is on the list; the plan (`components/CalibrationPlan.tsx`) with the spot large and red with
  its name, the others numbered. With a calibration in use, `lib/useLiveFix.ts` watches GPS
  (`Accuracy.BestForNavigation`, 1 s) and the plan adds where GPS puts you converted with that
  calibration, a halo of the phone's reported accuracy, a dashed line to the spot, a north arrow from
  the calibration's rotation (north on the drawing is (-sin r, -cos r) in x right, z down) and "GPS
  puts you about n m from spot 2"; "You are close" only when the distance is within the reported
  accuracy and that accuracy is at most `MAX_START_ACCURACY_M` (15 m). The line above the button
  shows the phone's accuracy as good enough (at most `MAX_START_ACCURACY_M`, the alert's own limit, no
  separate figure) or "wait for 15 m or better"; no permission or approximate location only (iOS
  Precise Location off, Android coarse) disables the button with how to fix it. "I'm standing at spot
  n" runs the unchanged recording: GPS in `Accuracy.BestForNavigation` for `RECORD_MS` (10 s),
  fixes time-stamped before the start ignored, mean lat/lng, mean reported accuracy and fix count
  stored (AsyncStorage `within-reach.georef-spots.v1.<building id>`). The live watch pauses during
  the recording so the recording's watch runs alone. A countdown bar replaces the button, a haptic
  marks the end, then "Go to spot n+1" (the next unrecorded spot) or "See the result".
- **Result** (2 or more spots). "Typical error: about n m" (the RMS of the residuals) with what it
  means, then a verdict: better or not than the calibration in use (3 or more spots), a warning with
  2 spots (the residuals cannot show a wrong rotation), "Too rough to use" at `MAX_START_ACCURACY_M`
  or more, "Something is off" when the mirrored fit is closer than the real one. Each spot with its
  residual, the worst marked, "Redo" and "Leave out". The bottom button is "Use it on this phone" when
  the verdict is good, else the spot to record or redo. Rotation, translation, pair distances, the
  mirror RMS and the block for `lib/georefDefaults.ts` (selectable, and the system share sheet) sit
  behind "Show details for the team".
- **Check** ("Check where GPS puts me"). The live GPS dot on the camera's floor with the alert's own
  GPS start rule (`judgeStartFix`) in plain words, the scan point it would start from ringed, and the
  nearest named spot.
The math, the stored formats and the committed values are unchanged. README section 7 has the
on-site procedure.

**AED help**: the seven steps in `lib/copy.ts` (general public AED guidance, not medically reviewed
by the team; the AED's own voice comes first). Step 1 is spoken on open, the screen only advances on
Next, Repeat speaks again, and speech stops when the screen loses focus. Opening it from the CPR
guide stops the metronome so it does not talk over the steps.

**CPR guide**: metronome at 110 bpm (audio tick + haptic), the depth and rate wording from spec §3, AED steps ("turn it on and follow its voice").

## Notes

- Check the current Expo SDK for the audio module name and API (`expo-audio`) before coding.
- On iOS in Expo Go, the alarm must play in silent mode: set the audio mode accordingly and test on a real phone.
- If the subscription drops, refetch open dispatches on app focus.
- Keep one alert at a time; a second dispatch while one is open is ignored.
- Pedometer in Expo Go: the Expo SDK 58 Pedometer docs say it is not available in Expo Go for
  Android (Expo Go does not have the `ACTIVITY_RECOGNITION` permission), so Android in Expo Go always
  uses the timed walk; step tracking on Android needs a development build. On iOS, Expo Go has its
  own Info.plist, so the motion prompt text there is Expo Go's, not ours. The `expo-sensors` plugin
  entry in `app.json` (`motionPermission`, sets `NSMotionUsageDescription`) only takes effect in a
  development or store build.
- Pedometer updates stop while the app is in the background (Expo docs). Update timing is not
  documented by Expo or Apple ("regularly"), so expect batches.

## Acceptance

- Insert a `dispatches` row by hand: the phone alarms within about a second on Wi-Fi.
- Accept reaches the agent and the dashboard shows the role.
- A release from the server silences the phone.
