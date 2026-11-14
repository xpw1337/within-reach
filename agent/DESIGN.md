# agent/ design

FastAPI service: the command API for everything, and the deterministic live response graph (spec §3, §8, §9.8, §9.10). Runs as one process, one worker, on the demo laptop.

## Layout

```
agent/
  main.py            app factory; lifespan: settings, warm-up, checkpointer, timer registry, graph compile
  deps.py            FastAPI dependencies (graph, timers, speaker, telephony)
  api/
    census.py          /census/runs, /census/buildings/{id}/rerun|fix|documents
    handcheck.py       /census/handcheck, /census/detections/{id}/label, summary
    config.py          /config/thresholds, /health
    events.py          POST /events
    incidents.py       confirm, cancel_911, milestone, resolve
    dispatches.py      accept, decline, arrived
    twilio.py          voice, gather, briefing webhooks (TwiML)
    photon.py          POST /photon/webhook: iMessage replies 1 / 2 / here (Photon 2.0)
    simulate.py        /simulate/{cardiac|fall|outdoor}, /reset
  live/
    state.py           IncidentState (TypedDict) + Signal types
    graph.py           build_graph(): nodes, edges, conditional routing, Send fan-out
    nodes/
      ingest.py  first_response.py  verify.py  confirm.py  voice_check.py
      classify.py  gate.py  announce.py  dispatch.py  brief_911.py
      police.py  staff.py  fall_timer.py  guide.py  handoff.py
    playbooks.py       speaker templates from spec §3, verbatim; script selection logic
    responders.py      eligibility, priority, waves, role assignment
    briefing.py        911 briefing text in the spec §9.10 order
    imessage.py        iMessage side channel: texts in the background, never awaited
    timers.py          TimerRegistry: named asyncio tasks that resume the graph with a timeout signal
    signals.py         deliver(incident_id, signal): the single entry point that resumes the graph
  io/
    speaker.py         Speaker protocol; LocalSpeaker (plays files), FakeSpeaker (tests)
    tts.py             Polly rendering; render_camera_audio(camera_id)
    telephony.py       Telephony protocol; TwilioTelephony (optionally over Photon SIP), FakeTelephony; destination allowlist
    messaging.py       Messenger protocol; PhotonMessenger (httpx), FakeMessenger; same allowlist
    verify.py          the one LLM call on the live path
  tests/
```

## The hot path

`POST /events(person_down)` -> `ingest` -> `first_response` must put voice-check audio on the speaker in under 1 second.

- No LLM, no TTS, no Twilio and no Storage upload before the audio starts.
- `ingest` inserts the `incidents` row; the snapshot upload is a background task.
- `first_response` plays `.cache/audio/{camera_id}/voice_check.mp3` and sets `first_instruction_at`.
- `collapse_at` is the event `ts` from vision minus `DOWN_SECONDS` for witnessed events (the drop happened before the down timer finished); for `found_down` it is `NULL` and the handoff card says "found down, time unknown".
- Warm-up in lifespan: load audio files into memory, open the DB connection, ping the LLM, pre-fetch `cameras` and `camera_routes`.

## State

```python
class IncidentState(TypedDict):
    incident_id: str
    camera_id: str
    building_id: str | None
    victim_track_id: int
    witnessed: bool
    type: Literal["unknown", "cardiac", "fall"]
    modifiers: list[str]              # subset of [breathing, seizure, overdose, notify_police]
    scene_safe: bool | None
    hazards: list[str]
    responsive: bool                  # set only by a vision "responsive" event
    confirm: Literal["pending", "confirmed", "false_alarm", "auto", "escalated_911_only"]
    voice_check_done: bool
    routes: dict                      # target -> {distance_m, directions, audio_url, path}
    dispatches: list[dict]            # id, responder_id, wave, role, status
    roles: dict                       # {"patient": responder_id | None, "aed_runner": responder_id | None}
    milestones: dict                  # cpr_started, aed_arrived, responder_arrived -> ts
    ems_briefed: bool
    resolved: bool
```

The database rows are the public view of this state. Nodes write through small helpers that update the row and emit the matching `incident_events` kind together.

## Signals and interrupts

Everything that can wake the graph is a typed signal delivered through `signals.deliver`:

```
vision:   responsive | possible_seizure | responder_arrived
desk:     confirm | false_alarm | cancel_911 | milestone(kind) | resolve
dispatch: accept(dispatch_id) | decline(dispatch_id) | arrived(dispatch_id, with_aed)
timer:    timeout(name)      names: voice_check, confirm_auto, found_down_escalate,
                                    wave_{n}, fall_911, announce_repeat, guide_tick
```

Design intent (spec §9.8): checkpointer keyed by `thread_id = incident_id`, `interrupt()` at confirm, voice_check and await_accept, resumed with `Command(resume=signal)`.

Implementation guidance:

1. **Check the current LangGraph semantics for several pending interrupts in parallel branches before building on them.** Resuming one specific interrupt among several has changed across versions.
2. If parallel interrupts are awkward, use the **signal inbox** pattern, which is the approved fallback: one `await_signal` node calls `interrupt()`, receives a signal, applies it to state through a pure reducer (`apply_signal(state, signal) -> state updates`), then a conditional edge decides what runs next (classify, gate, fan-out actions, or back to `await_signal`). Verify, announce loops and waves are then driven by timers and background tasks that deliver signals. The spec node list stays the same; only the waiting is centralized.
3. Either way, `apply_signal` is a pure function with exhaustive unit tests. It ignores signals that no longer apply (a confirm after false alarm, an accept after both roles are filled, a timeout whose timer was superseded). This is what makes races safe.
4. `signals.deliver` serializes per incident with an `asyncio.Lock` so two resumes never interleave.

## Decision logic (spec §3, do not simplify)

- `classify` runs when the voice check ends (timer or `responsive`):
  - `confirm == false_alarm` -> false alarm, stop audio, resolve.
  - `scene_safe is False` -> unsafe: play `unsafe_stay_back`, notify police, no responders.
  - `responsive` -> FALL. Otherwise -> CARDIAC with modifiers.
- `responsive` is set **only** by the vision `responsive` event (sustained raised wrist). No other movement signal can set it. `possible_seizure` adds the `seizure` modifier and still escalates.
- `verify` (LLM) returns `{is_emergency, scene_safe, hazards[], modifiers[]}`. Its output is filtered through the allowlist `[breathing, seizure, overdose, notify_police]` and merged by union: it can add modifiers and can mark the scene unsafe; it cannot remove a modifier, cancel an incident, or delay the script. `is_emergency=false` is shown to the desk as advice only. If verify fails or is slow, the graph proceeds without it.
- `gate` for external actions (responders, 911 briefing):
  - witnessed: proceed on desk confirm, or automatically after `CONFIRM_AUTO_PROCEED_SECONDS`.
  - found_down: proceed only on desk confirm; after `FOUND_DOWN_ESCALATE_SECONDS` with no tap, send the 911 briefing only, no responders.
  - The speaker script is **not** gated: local audio instructions start right after classify.
- FALL: staff alert first; 911 briefing after `FALL_911_CANCEL_SECONDS` unless `cancel_911`.
- `overdose` script is used only if naloxone is mapped for the camera.

## Fan-out actions

| Node | Behavior |
|---|---|
| `announce` | Plays the playbook script, repeats every 20 s until `cpr_started`, then hands over to `guide`. Emits `speak` events with `audio_url` and `target`. |
| `dispatch` | Waves per spec §9.10: eligible = consent + on duty + seen < 10 min + in geofence. Order: staff, security, tenants, then public; CPR-trained first for cardiac. `WAVE_SIZE` per wave, app alert (insert `dispatches` row) and Twilio call to `callable` phones at the same time, `ACCEPT_TIMEOUT_SECONDS` per wave, 3 waves max. First accept is `patient`, second is `aed_runner`; then everyone else is `released` and their calls are hung up. |
| `brief_911` | Calls `DISPATCH_SIM_NUMBER`, speaks the briefing twice. Never waits for waves. Sets `ems_notified_at`. |
| `police` | Only when hazards exist or `notify_police` is set. Demo: an `incident_events` row, no call. |
| `staff` | Staff alert as dispatches with role `staff` (app only). |
| `guide` | CPR coaching loop: `cardiac_cpr_coach` after `cpr_started`, `cardiac_aed_arrived` after `aed_arrived`. |
| `handoff` | Builds the Utstein-style card from `incidents` timestamps on resolve. |

## io/ notes

- `telephony.py`: `call_responder(dispatch)`, `call_briefing(incident_id)`, `hangup(call_sid)`. A hard allowlist: the destination must be `DISPATCH_SIM_NUMBER` or the phone of a `callable` responder with `consent_calls`. Any number matching an emergency short code (911, 112, 999) raises. This check has its own unit test.
- `tts.py`: Polly with `POLLY_VOICE`; `render_camera_audio(camera_id)` renders every script in `docs/CONTRACTS.md` §6 to `.cache/audio/` and mirrors to the `audio` bucket, then fills `camera_routes.audio_url`. Twilio call text uses Twilio `<Say>` and does not need Polly files.
- `speaker.py`: `play(script_id, camera_id)`, `stop()`. `LocalSpeaker` plays through the laptop output; a new `play` interrupts the current one. Pick a playback library that works on Windows and macOS and verify it at CP1.
- `verify.py`: one `shared.llm.complete_json` call, reasoning tier, snapshot image in, strict schema out, hard timeout.

## Simulate and reset

- `/simulate/cardiac`: injects `person_down` with `witnessed=true` and a stock frame from `demo/`, never followed by `responsive`.
- `/simulate/fall`: `person_down` then `responsive` after 2 s.
- `/simulate/outdoor`: stretch; returns 501 until built.
- `/reset`: cancel all timers, hang up calls, stop audio, delete incidents (cascades), clear checkpoints, re-warm.

## Tests (with FakeSpeaker, FakeTelephony, fake clock)

1. Witnessed cardiac, no tap: voice check -> CARDIAC script -> auto-proceed at 10 s -> wave 1 + briefing.
2. Witnessed cardiac, desk confirm at 3 s: phones ring before 15 s from collapse.
3. Found down, no tap: script plays, no responders ever, briefing only at 60 s.
4. Raised hand during voice check: FALL, staff alert, briefing at 60 s unless cancelled.
5. Seizure event: CARDIAC + seizure script, still escalates.
6. Unsafe scene from verify: stay-back script, police event, zero dispatches.
7. Verify tries to drop a modifier or returns junk: ignored.
8. False alarm tap at any point: everything stops, calls hung up.
9. Two accepts, then a third: patient, aed_runner, released.
10. No accepts: three waves, then stop; briefing was not delayed.
11. Races: confirm and auto-proceed timeout in the same tick; duplicate accept; signal after resolve.
12. Telephony refuses 911.

## Acceptance

- All tests above pass.
- `/simulate/cardiac` against the fallback seed shows first-instruction latency under 1 s from event receipt on the dashboard, with real audio.
- A real Twilio call reaches a teammate phone and digit 1 assigns a role.
