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
    cpr.tsx                  CPR guide: 110 bpm metronome, spec §3 wording, AED steps
    released.tsx
  lib/
    supabase.ts              client from EXPO_PUBLIC_SUPABASE_URL / ANON_KEY
    api.ts                   accept, decline, arrived (agent API)
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
- Shows role once assigned, distance, text directions from `camera_routes`, a map (`react-native-maps`) with the building and my position, and "View route in 3D" opening `EXPO_PUBLIC_DASHBOARD_URL/building/{id}` in the browser.
- Accept -> `POST /dispatches/{id}/accept`; the response carries the role (`patient` or `aed_runner`) or `released`.
- Can't help -> decline.
- 20 s countdown from `sent_at`; at zero the screen closes (the agent marks the timeout).
- After accept: "I'm here" (patient) or "AED here" (runner) -> `arrived` with `with_aed`; then the CPR guide.
- A Realtime update to `released` at any time stops the alarm and shows Released.

**CPR guide**: metronome at 110 bpm (audio tick + haptic), the depth and rate wording from spec §3, AED steps ("turn it on and follow its voice").

## Notes

- Check the current Expo SDK for the audio module name and API (`expo-audio`) before coding.
- On iOS in Expo Go, the alarm must play in silent mode: set the audio mode accordingly and test on a real phone.
- If the subscription drops, refetch open dispatches on app focus.
- Keep one alert at a time; a second dispatch while one is open is ignored.

## Acceptance

- Insert a `dispatches` row by hand: the phone alarms within about a second on Wi-Fi.
- Accept reaches the agent and the dashboard shows the role.
- A release from the server silences the phone.
