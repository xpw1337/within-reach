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

### 2. On duty and location (5.6)

1. With location consent on, Home asks for location permission. Allow it ("While using the app").
2. Home shows "Sharing. Last update <time>". In Supabase, the row's `last_lat`, `last_lng` and
   `last_seen_at` are set.
3. Leave the phone still with the app open for a minute: `last_seen_at` keeps advancing, about every
   15 to 20 seconds, never more often than every 15 seconds.
4. Toggle Off duty: `responders.on_duty` becomes false and the location writes stop. Toggle back on.
5. Background the app for a minute: `last_seen_at` stops advancing (foreground only, by design).
