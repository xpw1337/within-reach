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
| Calls | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `PUBLIC_BASE_URL` | `FakeTelephony`: calls are recorded, nothing rings |
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

## Not done or not verified

- Supabase store, Polly rendering and real Twilio calls: written, never run (no credentials).
- Windows and Linux audio playback: written, only macOS `afplay` was run.
- Wording for `cardiac_aed_arrived`, `unsafe_stay_back` and `all_clear` is not in the spec: those
  scripts are not rendered. Without stay-back audio an unsafe scene goes quiet (it never plays the
  CARDIAC script).
- A restart loses timers; open incidents from before a restart are not resumed. Use `POST /reset`.
