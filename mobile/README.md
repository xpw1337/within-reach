# Within Reach responder app (mobile/)

Expo Go app for trained responders (spec section 9.11). Foreground only: no push notifications and no
background location. Design notes are in `DESIGN.md`.

Expo SDK 58 (React Native 0.88, expo-router 58). The phone needs an Expo Go build that supports SDK 58.
Expo's SDK 58 release notes (October 15, 2026) said the store builds would follow within a few weeks; if
Expo Go reports that the project's SDK is not supported, update Expo Go from the store.

## Setup

```sh
cd mobile
npm install
# create mobile/.env with the four EXPO_PUBLIC_* lines below (Expo reads .env from this folder)
npx expo start               # scan the QR code with the phone (Camera app on iOS, Expo Go on Android)
```

| Variable | Value |
|---|---|
| `EXPO_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `EXPO_PUBLIC_SUPABASE_ANON_KEY` | anon key (the demo policies in `supabase/migrations/0002_demo_policies.sql` must be applied) |
| `EXPO_PUBLIC_AGENT_URL` | the agent's public tunnel URL (ngrok / cloudflared). Not `localhost`: the phone must reach it. |
| `EXPO_PUBLIC_DASHBOARD_URL` | the dashboard's URL as reachable from the phone |

`.env` is git-ignored. Never commit keys or phone numbers. Restart `npx expo start` after editing `.env`.

## Checks that run without a phone

```sh
npm run typecheck       # tsc --noEmit
npm run lint            # expo lint
npm run export:ios      # bundles to dist-check/ios (git-ignored)
npm run export:web      # bundles to dist-check/web
npm run check:georef    # Node check of lib/georef.ts (Node 22.18+ or 24) and the GPS noise simulation
npm run sounds          # regenerates assets/alarm.mp3 and assets/tick.wav from sine tones (needs ffmpeg)
```

## Real-device checks (not yet verified)

None of these have been run: there was no Supabase project and no phone available when this was
built. Each one needs a person with a phone.

### 1. Onboarding writes a responders row (5.5)

1. Fresh install in Expo Go. The Onboarding screen opens.
2. Fill in a name, your own phone number, CPR trained, a role, a building (or "Not in a listed building"),
   and both consents. Check that the privacy line and the Good Samaritan line are shown.
3. Tap "Join as a responder". The Home screen opens.
4. In the Supabase table editor, `responders` has a new row with those values, `callable = false`.
5. Kill and reopen the app: it goes straight to Home (the id is stored on the phone).
6. Edit profile, change the role, save: the same row is updated (no second row).
7. Seeded teammate: on a fresh install, type the phone number of a seeded callable responder (from
   `seed.local.sql`). No new row is created; that row's name, role and consents are updated, and its
   `callable` and stored phone stay as they were. Dispatches to that row now alarm this phone.

### 2. On duty and location (5.6)

1. With location consent on, Home asks for location permission. Allow it ("While using the app").
2. Home shows "Sharing. Last update <time>". In Supabase, the row's `last_lat`, `last_lng` and
   `last_seen_at` are set.
3. Leave the phone still with the app open for a minute: `last_seen_at` keeps advancing, about every
   15 to 20 seconds, never more often than every 15 seconds.
4. Toggle Off duty: `responders.on_duty` becomes false and the location writes stop. Toggle back on.
5. Background the app for a minute: `last_seen_at` stops advancing (foreground only, by design).

### 3. Alert flow (5.7)

Find your responder id: Supabase table editor, `responders`, the row with your name. You need one
incident row to point at (run `POST /simulate/cardiac` on the agent, or insert one by hand).

1. App open on Home ("Alerts: Connected"). In the SQL editor run:
   ```sql
   insert into dispatches (incident_id, responder_id, channel, status)
   values ('<incident id>', '<your responder id>', 'app', 'sent');
   ```
2. Within about a second the phone alarms (sound plus vibration) and shows the red Alert screen with a
   20 s countdown, the location, distance, map and "View route in 3D".
3. Silent mode (iPhone): flip the ring/silent switch to silent and repeat step 1. The alarm must still
   be audible. This is the check for `playsInSilentMode`.
4. Tap Accept. With the agent running, the role appears ("Go to the person" or "You're the AED
   runner") and the dashboard shows it. Without the agent, an error appears; to fake the role, run
   `update dispatches set status='accepted', role='aed_runner' where id='<dispatch id>';`
5. Tap "I'm here" (or, as AED runner, "I have the AED" then "I'm with the person"): the agent
   receives `arrived` with `with_aed`. The full indoor flow is section 5.
6. Release: insert another dispatch, then `update dispatches set status='released' where id='<id>';`
   The alarm stops and the Released screen shows.
7. Countdown: insert another dispatch and do nothing. At 0 the screen closes and the alarm stops.
8. Can't help: insert another dispatch, tap "Can't help": the alarm stops, Home shows, and the agent
   gets `decline`.
9. Missed while away: background the app, insert a dispatch, reopen within 20 s: the alert opens.
10. One at a time: insert two dispatches quickly: only the first one alerts.

### 4. CPR guide (5.8)

1. Home, "CPR guide", "Start metronome": a tick plus a vibration on every beat, with the circle pulsing.
2. Count ticks for 60 seconds with a stopwatch: expect 110.
3. iPhone silent switch on silent: the tick must still be audible (`playsInSilentMode`). Also check
   that haptics are felt; iOS turns haptics off in Low Power Mode.
4. During a phone call on speaker (simulating 911 on speaker), start the metronome: the call must not
   be cut off or muted, and note whether the tick is audible over it.
5. After "I'm here" on an alert, the guide opens with the metronome already running. If the incident
   has the `breathing` or `seizure` modifier, the matching spec line is shown.

### 5. Indoor plan, AED runner and AED help (not yet verified on a phone)

Bundling, typecheck and lint pass, and the plan drawing, the walking dot and the AED help screen
(speech on Next, stop on leaving) were checked in a web browser with made-up graph data. Nothing
below has run on a phone or against real demo data. Needs: the demo building's `twin_nodes`, a
camera row with `sweep_id` and `floor`, an AED `assets` row and a `camera_routes` row with
`target='aed'`, plus the agent with the new accept rule and the `aed_picked_up` and
`aed_help_started` milestone kinds.

1. Phone A (will be the AED runner) and phone B (patient) both on Home, on duty.
2. Run `POST /simulate/cardiac` with the demo camera. Both phones alarm. The Alert screen shows the
   indoor floor plan (not the outdoor map): the person in red with the camera's floor, the AED in
   green labeled "Demo AED (placed by team)" if its `flags` has `simulated` (otherwise "AED"), a
   dashed route between them, and no blue dot yet.
3. Phone A taps Accept first: role "You're the AED runner", title "Go to the AED". With no
   georeference calibration for the building (section 7), "Tap the map where you are" shows for about
   8 s; do not tap, and a blue dot appears
   on the far side of the AED from the person with a solid route to the AED. How it moves depends on
   the phone (section 6): on an Android phone in Expo Go it shows "Position simulated for the demo"
   and walks to the AED at walking speed, then stops on it; on an iPhone that allows Motion it shows
   "Position estimated from your steps" and moves only as you walk.
4. Tap "I have the AED" (try it before the dot arrives too): the dot jumps to the AED and starts the
   AED -> person route; the title becomes "Bring the AED to the person". On the dashboard /live
   timeline, an `aed_picked_up` milestone appears.
5. Tap "I'm with the person": the dot sits on the person, "You are marked as arrived." shows, and the
   agent gets `arrived` with `with_aed: true`. The big "GIVE ME HELP WITH AED" button shows.
6. Tap it: the AED help screen opens and speaks step 1 ("Turn on the AED..."), shown in large text,
   and the agent gets `aed_help_started`. Next speaks step 2, and so on; it never advances by itself.
   Repeat speaks the current step again; Back goes one step back.
7. Silent mode: flip the iPhone ring/silent switch to silent and tap Repeat. The step must still be
   audible (expo-audio `playsInSilentMode` with expo-speech on the app audio session). On Android,
   turn the ringer to silent with media volume up: speech should play. Note the result for both.
8. Leave the AED help screen mid-sentence (CPR guide button or back gesture): speech stops at once.
9. Phone B taps Accept second: role "Go to the person", a dot moves start -> person, "I'm here"
   opens the CPR guide with the metronome running, and the guide shows "GIVE ME HELP WITH AED".
   Tapping it stops the metronome and opens AED help.
10. Failure handling: stop the agent (or break `EXPO_PUBLIC_AGENT_URL`), then tap "I have the AED"
    and "I'm with the person". Each screen still moves on at once with no error; the call is retried
    once about 2 s later and then dropped.
11. No AED: delete the camera's `camera_routes` row with `target='aed'` (or use a camera without
    one) and repeat step 2: the plan shows the person only with "No AED route is mapped for this
    spot", no blue dot, and no AED steps.
12. No twin: use a building with no `twin_nodes`: the outdoor map shows, as before.

### 6. Helper dot from the phone's steps (not yet verified on a phone)

Typecheck, lint and both bundles pass, and the pure step logic (`lib/stepWalk.ts`: baseline, steps
to meters, clamping, glide) was checked in Node. Nothing below has run on a phone. Use the setup of
section 5. Walk somewhere with room to take 20 or more steps; hold the phone normally (in hand or
pocket). The app must stay in the foreground: step updates stop in the background.

**iPhone (Expo Go):**
1. Fresh state: in iOS Settings, Expo Go, make sure Motion & Fitness has not been answered yet (or
   delete and reinstall Expo Go). Open the app and go On duty. No motion prompt appears at launch.
2. Trigger an alert and tap Accept. Right after the role appears, iOS asks for Motion & Fitness
   access. The prompt text is Expo Go's own, not ours (Expo Go ignores our `app.json` text).
3. Allow. Under the plan: "Position estimated from your steps". Stand still for 15 seconds: the dot
   must not move at all. After about 10 s with no steps the line "No steps counted yet. Use the
   button below when you get there." appears.
4. Walk 10 steps, counting them. The dot moves forward along the solid route and the "No steps" line
   goes away. Note how long after your first step the dot starts moving and whether it moves in
   bursts. Each burst should glide over about a second, never jump. Stop: the dot stops within a
   couple of seconds and stays.
5. Rough distance check: after 10 counted steps the dot should be about 7 m along the route (10 x
   0.7 m, the assumed step length). Write down the real distance you walked; we do not claim it
   matches.
6. Keep walking past the AED: the dot stops on the AED and goes no further.
7. Tap "I have the AED": the dot jumps to the AED and the next leg starts from zero (no prompt this
   time). Walk: it moves along AED -> person. Tap "I'm with the person": the dot sits on the person
   with no position line.
8. Denied: in iOS Settings, Expo Go, turn Motion & Fitness off, then repeat steps 2 to 3. The plan
   shows "Position simulated for the demo" and the dot walks on its own at walking speed, as before.
9. Background: on step tracking, walk 5 steps with the app in the background, then reopen it. Note
   whether the dot catches up (iOS resumes counting from the leg's start) or not.

**Android (Expo Go):** Expo's SDK 58 docs say the pedometer is not available in Expo Go on Android.
1. Accept an alert. Expect no motion prompt and "Position simulated for the demo" with the timed walk,
   exactly as before. If the app instead shows "Position estimated from your steps", write that down
   and run the iPhone steps 3 to 7 on it.
2. To test real step tracking on Android you need a development build (`npx expo run:android` or an
   EAS development build), which includes the `ACTIVITY_RECOGNITION` permission. Then on Accept,
   Android asks for "Physical activity" access; run the iPhone steps 3 to 8 (deny in Settings, Apps,
   Within Reach, Permissions, Physical activity). Android drops the very first step of each leg on
   purpose (the first sensor report is taken as the baseline).

**If steps arrive late:** some phones report steps only every few seconds, and some only after
several steps. Expected: the dot waits, then glides forward over about a second to catch up; it never
moves while you stand still, and it never switches to the timed walk in the middle of a leg. If no
steps ever arrive, the buttons still work and snap the dot. Note the phone model, the delay before
the first movement, and the typical gap between bursts.

### 7. Georeference calibration on site, and the GPS start

**Status: the demo building is already calibrated.** The team recorded it on site on 2026-11-14 from
4 spots (patient spot, AED spot, corridor wing, atrium edge), residual 3.64 m RMS, and it is committed
in `lib/georefDefaults.ts` under `'DEMO-RABINOWITZ'`. Every phone with this build uses it, so **nobody
needs to calibrate for the demo**. Calibrate again only if the blue dot in an alert starts in the wrong
part of the building. The calibration screen was then rebuilt as the step-by-step flow below:
typecheck, lint of the changed files, the web and iOS bundles and the Node check of the math
(`npm run check:georef`: round trips, a known rotation, the mirror check, exact and mirrored solves,
the start accuracy rule, and the noise simulation below) pass, and the flow was clicked through in
headless Chrome at phone size with faked GPS. The new screen has not run on a phone yet.

**What it does.** After Accept, if the building has a calibration and the app already has location
permission, the phone takes one fresh high-accuracy fix, converts it to the floor plan and snaps it to
the nearest sweep on the camera's floor. It is used only if the phone reports an accuracy of 15 m or
better and the point is within 15 m of a sweep (both limits are our judgment calls for this demo, not
a standard). Otherwise the helper can tap the plan, and after about 8 s without a tap the simulated
start is used. The buttons always work.

**Before you go.**
1. The building's `twin_nodes`, its camera row (with `sweep_id`) and its AED `assets` row are in
   Supabase (the demo building is `DEMO-RABINOWITZ`).
2. iPhone: Settings, Expo Go, Location: "While Using the App" and **Precise Location on**. With
   Precise Location off, iOS reports positions that are deliberately coarse and the calibration is
   useless. Android: location on, and "Use precise location" allowed for Expo Go.
3. Each spot takes 10 s of recording plus the walk; plan for all the labeled spots.

**Open the calibration screen.** On Home, press and hold the "Within Reach" title for about a second.
It opens the building from your profile; "Change building" searches for another. The first card says
whether the building is calibrated: "Already calibrated" with the team's date, spot count and typical
error (or this phone's own calibration, with "Remove this phone's calibration"), or "Not calibrated
yet". Below it: what calibration does, the plan with the numbered spots, the list of spots (tap one to
go straight to it) and what to set up first. This screen is for the team only and writes nothing to the
database.

**Walk the spots.** Tap the big button at the bottom: "Calibrate again" ("Start calibration" when there
is no calibration, "Continue at spot n of 4" when some are recorded). The spots are the patient spot
(the camera's sweep), the AED spot and every other labeled sweep, in this order for the demo building:
1 "Central atrium" (patient), 2 "Gothic arcade gate" (AED), 3 "Atrium edge near the main corridor",
4 "Corridor wing". The screen shows one spot at a time: "Spot 2 of 4", a row of numbered circles to
jump between spots (green once recorded), the spot's name in large type and why it is on the list.
1. Find the spot. On the plan it is the big red numbered circle with its name: exactly where the
   scanner stood for that sweep. When a calibration is already in use (it is for the demo building),
   a blue dot shows where GPS puts you, with a halo the size of the accuracy the phone reports, a
   dashed line from you to the spot and an N arrow for north, and the line above the plan says "GPS
   puts you about n m from spot 2". When you are within the phone's reported accuracy of the spot and
   that accuracy is 15 m or better, it says "You are close" instead. The dot comes from the calibration
   in use (about 3.6 m typical error), so it only gets you to the right area: use the name and the plan
   to stand on the exact place. Being a meter off adds about a meter of error to that spot.
2. Wait for GPS. Hold the phone flat at chest height, screen up. The line above the button shows the
   accuracy the phone reports: green "good enough" at 15 m or better (the same limit the alert's GPS
   start uses), amber "wait for 15 m or better" above that. Waiting about half a minute after arriving
   helps it settle (a habit, not a measured figure). If location is not allowed or Precise Location is
   off, the screen says so in red, the button stays off, and "Check again" retries after you fix it in
   Settings.
3. Tap "I'm standing at spot n" and stand still. A blue bar counts down the 10 s with the number of GPS
   readings. When it is done the phone buzzes, the circle turns green, the line says "Spot n recorded"
   and the button becomes "Go to spot n+1" (or "See the result" after the last one). The page also shows
   the readings, the accuracy and "Record spot n again". If no fix arrives, the line says so: move
   nearer a window or the entrance and tap the button again. "Skip this spot" moves on; "All spots"
   goes back to the first screen.
4. Record as many spots as you can, and always the two that are farthest apart. Rotation error is
   roughly GPS error divided by the distance between the spots, so spots close together (the atrium edge is
   only 3.4 m from the atrium center) add little on their own.

**Read the result.** With two or more spots, "See the result" shows "Typical error: about n m" in large
type (the RMS of the per-spot residuals: how far each spot's GPS lands from its scan position after the
fit), a verdict in plain words, and each spot with its own error, "Redo" and "Leave out" (the worst one
is marked when there are 3 or more).
- **Better than the calibration in use** (3 or more spots, a lower typical error than the one in use,
  no warning): the bottom button is "Use it on this phone". Otherwise the bottom button takes you to
  the spot to record or redo, and "Use it on this phone anyway" is in the page.
- **Two spots:** the fit always splits the difference, so both residuals are equal: half the gap
  between the GPS distance and the scan distance. Small residuals do NOT mean the rotation is right.
  The screen asks for a third spot.
- **Three or more spots:** residuals of a few meters are what indoor GPS usually gives. One spot much
  worse than the others: redo it. A typical error of 15 m or more shows "Too rough to use": the GPS
  start would rarely be used in an alert, and when it is, the start may be on the wrong side of the room.
- **Mirror check** (three or more spots): the same fit with the plan flipped. If it fits closer than
  the real one, the screen says "Something is off": stop and tell the team.
- "Show details for the team" has the rotation, the translation, the RMS, the mirror RMS, the GPS and
  scan distance for each pair of spots (if GPS says two spots are 30 m apart and the scan says 11 m, at
  least one of the fixes is bad) and the block for `lib/georefDefaults.ts`.

What to expect from GPS noise (from `npm run check:georef`: a simulation with independent Gaussian
noise on each fix's east and north, not a measurement). With the patient and AED spots alone, 11.0 m
apart, 2 m of noise gives a median rotation error of about 10 degrees (90th percentile about 25), and 5
m of noise about 26 degrees (90th percentile about 71). At the far end of floor 2 (about 24 m from
those spots) that rotation error alone moves the converted point by a median of about 4 m and 11 m.
All four labeled spots together roughly halve the rotation error. Indoor GPS noise is often larger
than this and is not independent between nearby fixes, so treat these as a guide only.

**Save and commit.**
1. "Use it on this phone" stores the calibration with today's date. Alerts on this phone now use it
   in this building. A calibration saved on the phone always wins over the committed one.
2. "Send the numbers to the team" opens the share sheet (Copy, Notes or AirDrop to a laptop); the same
   block is selectable under "Show details for the team". Paste it between the braces of
   `GEOREF_DEFAULTS` in `mobile/lib/georefDefaults.ts` in place of the entry with the same key (keep the
   key it shows, `'DEMO-RABINOWITZ'` for the demo building), run `npm run typecheck`, and commit. Every
   other phone then uses it.
3. To go back to the committed numbers on the phone that calibrated, tap "Remove this phone's
   calibration" on the first screen (it then shows the team's calibration from the build).

**Test the GPS start on a phone.**
1. On the first screen of the calibration, tap "Check where GPS puts me" and walk to three or four
   places you can identify on the plan. It shows the live blue dot, the phone's accuracy, the nearest
   named spot and whether an alert would use the GPS start, and if so rings the scan point it would
   start from. Compare that with where you are actually standing.
2. Then the real flow: phone on duty with location allowed, standing somewhere on the camera's floor.
   Trigger an alert (section 5 setup) and tap Accept. Expect "Checking GPS for your start
   position..." for up to 4 s, then the blue dot at the nearest sweep with "Start position from GPS
   (accurate to about n m)" and "Movement estimated from your steps" (or "Movement simulated for the
   demo"). The route goes from there to the AED (runner) or to the person.
3. Fallbacks: turn location off for Expo Go and repeat: "Tap the map where you are". Tap a spot: the dot
   starts at the nearest sweep with "Start position set by you". Repeat and do not tap: after about
   8 s the simulated start with "Position simulated for the demo" (or the steps line), as before. Tap
   "I have the AED" or "I'm here" while the prompt shows: the screen moves on at once.
4. Outside, more than 15 m from the building's sweeps: expect the tap prompt (off the map), not a dot.

**What a bad result looks like.** The dot starts on the other side of the atrium or in another wing
from where you stand; on "Check where GPS puts me" the blue dot jumps several meters or the alert start
moves between scan points while you stand still; the reported accuracy is above 15 m so the tap prompt
shows every time; or the route starts behind a wall from you. Any of these: record more spots farther
apart, check Precise Location, or leave the calibration out (remove it on the phone and take the
building's entry out of `lib/georefDefaults.ts`) and use the tap start for the demo.
