# agent/

FastAPI command API and the deterministic live response graph. Design: `agent/DESIGN.md`.

## Run

```
uv sync --extra dev
uv run pytest agent                                  # all tests, fakes only, no network
uv run uvicorn agent.main:app --port 8000            # one worker only (timers and locks are in-process)
```

What the app uses depends on the environment (`agent/deps.py`):

| Piece | Configured | Not configured |
|---|---|---|
| Store | `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`: Supabase through `shared.db` | in-memory dev fixture (`live/devseed.py`, values not measured, never reaches the dashboard) |
| Calls | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (or Photon SIP), `PUBLIC_BASE_URL` | `FakeTelephony`: calls are recorded, nothing rings |
| iMessage | `PHOTON_API_KEY` + `PHOTON_PROJECT_ID` (replies: `PHOTON_WEBHOOK_SECRET`) | no texts; the webhook answers 503 |
| Speaker audio | Polly (`TTS_PROVIDER=polly` + AWS credentials) | macOS `say` into `.cache/audio/{camera_id}/*.aiff` |
| Scene check | `shared.llm` (reasoning tier, hard timeout 8 s) | fails at once; the graph proceeds without it |

At startup the app renders speaker audio for `CAMERA_ID` if `voice_check` is missing. To re-render
after the census writes real routes: `uv run python -c "import asyncio; from agent.io.tts import render_camera_audio; asyncio.run(render_camera_audio('cam-lobby-1'))"`.

## Live graph: why a signal inbox

Checked on LangGraph 1.2.22 with a throwaway experiment (two parallel branches that both call
`interrupt()`, AsyncSqliteSaver):

- Both interrupts surface with their own ids and one can be resumed with `Command(resume={id: value})`.
- But the successor of the resumed branch (classify) does not run until every interrupt in that
  superstep is resumed: classify would wait for the desk confirm, which breaks the spec timing.
- `Command(resume=value)` with two pending interrupts raises `RuntimeError`.
- Two concurrent unlocked resumes on one thread lost one signal.

So all waiting is one `interrupt()` in `await_signal`; `live/reducer.py` applies each signal
(pure, unit-tested), `plan()` picks the next nodes, the fan-out uses `Send`, and `signals.deliver`
locks per incident. 60 sequential resumes on one thread took about 2.2 ms each with SQLite.

## Twilio tunnel setup (needs a person and an account; not verified)

1. Upgrade the Twilio account, buy a voice number, put `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
   `TWILIO_FROM_NUMBER` in `.env`. `DISPATCH_SIM_NUMBER` is a teammate's phone, never an emergency
   number (the app refuses to start with one).
2. Start the agent: `uv run uvicorn agent.main:app --port 8000`.
3. Open a tunnel to port 8000, either `ngrok http 8000` or `cloudflared tunnel --url http://localhost:8000`.
4. Put the public https URL in `PUBLIC_BASE_URL` (no trailing slash) and restart the agent. Calls
   fetch TwiML from `{PUBLIC_BASE_URL}/twilio/voice/{dispatch_id}` and
   `{PUBLIC_BASE_URL}/twilio/briefing/{incident_id}`; digits post to `/twilio/gather/{dispatch_id}`.
   No webhook needs to be set on the number itself.
5. With `TWILIO_AUTH_TOKEN` set, webhooks must carry a valid `X-Twilio-Signature` for
   `PUBLIC_BASE_URL` + path, so `PUBLIC_BASE_URL` must match the tunnel URL exactly.
6. Responder phones are called only when the responder is `callable` and has `consent_calls`.
   Trial accounts can only call verified numbers.
7. Test: `curl -X POST localhost:8000/simulate/cardiac`, then confirm on the dashboard. The
   callable responder's phone rings; pressing 1 assigns a role; the sim-911 phone hears the briefing twice.

## Photon 2.0: iMessage and voice over SIP (needs a person; not verified end to end)

What the code does (docs/CONTRACTS.md, Photon 2.0):

- Calls: with `PHOTON_SIP_SERVER`, `PHOTON_SIP_USERNAME`, `PHOTON_SIP_PASSWORD` and `PHOTON_NUMBER`
  all set, Twilio places each call to `sip:<number>@<PHOTON_SIP_SERVER>;transport=tls;secure=true`
  from `PHOTON_NUMBER` (`io/telephony.py`). Our TwiML webhooks run as before.
- iMessage (`io/messaging.py`, `live/imessage.py`), with `PHOTON_API_KEY` and `PHOTON_PROJECT_ID`:
  the wave alert next to the app alert and the call (`channel` is `imessage` only when no call
  was placed), the staff alert to callable staff, a role follow-up with the route and "Reply HERE",
  a stand-down text when a texted responder is released, and the 911 briefing text to
  `DISPATCH_SIM_NUMBER` after the call speaks it (fallback 90 s after the call is placed). Every
  send is a background task with a hard timeout: a failure is an `imessage_failed` timeline event.
- Replies (`api/photon.py`, `POST /photon/webhook`): `1` accept, `2` decline, `here` arrived.

Only read-only Photon requests were made while building this: the project is on shared iMessage
lines (25 seats, 0 assignments), no Voice profiles or numbers, and the assignment lookup (`GET
.../platforms/imessage/assignments`) works with the project key.

Steps:

1. iMessage lines. In app.beta.photon.codes, project, iMessage: for every phone that must get texts
   (each responder with `callable` and `consent_calls`, and the `DISPATCH_SIM_NUMBER` phone), add
   the number and assign a line from the shared pool. Each assignment uses a seat.
2. From each of those phones, text its assigned line once (anything, for example "hi"). A shared
   line cannot send the first message; without this every send fails with
   `HTTP 403 SHARED_LINE_INBOUND_REQUIRED` on the timeline.
3. `.env`: `PHOTON_API_KEY` (a project key with project read/write and platforms read) and
   `PHOTON_PROJECT_ID`. Restart the agent.
4. Webhook. With the agent and the tunnel running (`PUBLIC_BASE_URL`, see above), project,
   Webhooks, Add a destination: URL `{PUBLIC_BASE_URL}/photon/webhook`, API version `2026-07-01`,
   event `message.received`. Copy the `whsec_...` signing secret into `PHOTON_WEBHOOK_SECRET` and
   restart. Photon does not deliver to localhost, only to the public tunnel URL.
5. Voice. Get a voice-eligible Photon SMS number (shared iMessage lines do not support Voice).
   Voice, Default profile, SIP. Under Outbound calls choose Digest algorithm **MD5 (legacy)**
   (Twilio needs it), Enable outbound and save the one-time password. Set `PHOTON_NUMBER` (E.164),
   `PHOTON_SIP_SERVER` (the SIP connection `host:TLS port`, for example `sip.photon.codes:5061`),
   `PHOTON_SIP_USERNAME` and `PHOTON_SIP_PASSWORD`. Twilio credentials and `PUBLIC_BASE_URL` are
   still required; `TWILIO_FROM_NUMBER` becomes optional. The startup log says
   "calls go out through the Photon number over SIP".
6. Self-test. `curl -X POST localhost:8000/simulate/cardiac`, confirm on the dashboard. Expected:
   the callable responder's phone rings with `PHOTON_NUMBER` as caller ID and gets the iMessage
   alert; replying `1` assigns a role and brings the route text; replying `here` marks them
   arrived on `/live`; the sim-911 phone hears the briefing twice, then gets it as a text. The
   timeline shows `imessage_sent` / `imessage_received` (actor `photon`). A SIP `403` means the
   profile is not on MD5.

## Not done or not verified

- Photon: no message was sent and no call was placed; webhook delivery from Photon, the
  assignment-based chat lookup (`POST /users`, `POST /spaces`) and SIP calls are written from the
  OpenAPI spec and the Beta docs and tested with fakes only.

- Supabase store, Polly rendering and real Twilio calls: written, never run (no credentials).
- Windows and Linux audio playback: written, only macOS `afplay` was run.
- Wording for `cardiac_aed_arrived`, `unsafe_stay_back` and `all_clear` is not spec text: it was
  approved by the team lead on 2026-11-14 (`live/playbooks.py`). With no AED route, `cardiac_main`
  drops only its AED sentence.
- A restart loses timers; open incidents from before a restart are not resumed. Use `POST /reset`.
