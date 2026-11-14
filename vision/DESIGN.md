# vision/ design

Live person-down detection (spec §9.9). A standalone process: webcam in, HTTP events out. It imports no other repo package so the same code runs on a laptop or a Raspberry Pi.

## Layout

```
vision/
  main.py          capture loop, CLI flags, debug overlay window
  config.py        reads env: CAMERA_INDEX, CAMERA_ID, AGENT_URL, DOWN_SECONDS, RESPONSIVE_HOLD_SECONDS
  tracker.py       Ultralytics YOLOv8n-pose with model.track(persist=True); yields per-frame tracks + keypoints
  features.py      pure functions on keypoints: torso angle, bbox aspect, hip height, wrist-above-shoulder, limb oscillation
  detector.py      per-track state machines that turn features into events
  client.py        POST /events with retry; attaches one JPEG on person_down only
  replay.py        run the detector over a video file and print events (tests, tuning)
  requirements-pi.txt   minimal dependency set for the Pi
  tests/
```

Extra env (add to `.env.example`): `CAMERA_ID` (default `cam-lobby-1`), `AGENT_URL` (default `http://localhost:8000`).

## Detection rules (from the spec, thresholds as named constants)

| Signal | Rule |
|---|---|
| down | torso near horizontal, or bbox width/height > 1.3, held for `DOWN_SECONDS` |
| not down | sitting must not trigger: require the hip keypoints near floor level relative to the track's standing height, not just a short bbox |
| witnessed | hip-y drop of more than 40% of body height within 2 s before the person went down |
| found_down | already down when the track first appears, or went down slowly (no qualifying drop) |
| responsive | the **victim track's** wrist above its shoulder for at least `RESPONSIVE_HOLD_SECONDS`. Nothing else counts. |
| possible_seizure | 1 to 5 Hz oscillation of wrist or ankle keypoints while down (windowed frequency estimate) |
| responder_arrived | a second track within a set distance of the victim track |

## Detector state machine (per track)

```
UPRIGHT -> DOWN_PENDING (down pose seen) -> DOWN (held DOWN_SECONDS) => emit person_down {witnessed}
DOWN: wrist-above-shoulder held        => emit responsive      (once)
DOWN: oscillation detected             => emit possible_seizure (once)
DOWN: other track nearby               => emit responder_arrived (once)
DOWN -> UPRIGHT (standing for N seconds) => clear victim, allow a new incident
```

- Exactly one victim at a time: the first track to reach DOWN. Its `track_id` goes in every later event.
- If the tracker loses and re-acquires the victim (ID switch), re-associate by position so `responsive` is still attributed to the victim.
- Each event kind is sent once per incident. The agent side is idempotent anyway.

## Privacy rules (enforced in client.py)

- Frames leave the device only inside a `person_down` event: one JPEG, downscaled.
- No frames are written to disk. No face processing of any kind.
- The debug overlay draws skeletons only.

## Raspberry Pi (stretch, only if working by CP2)

- Same code with `requirements-pi.txt`, a smaller input size and a lower frame rate. Measure fps before committing to it.
- Optional `speaker_server.py`: a tiny HTTP endpoint `POST /play {audio_url}` so the Pi's speaker can be the output. The agent side would add a `RemoteSpeaker`. Do not build until the laptop path is solid.

## Tests

- `features.py` unit tests on synthetic keypoints.
- `replay.py` over clips in `demo/clips/`: `fall_witnessed`, `lie_down_slowly`, `sit_down`, `fall_then_raise_hand`, `fall_then_shake`, `fall_then_helper_arrives`. Expected events are listed in a JSON file next to each clip. Recording these clips is a team task.

## Acceptance

- Live webcam: a real collapse in the taped zone posts `person_down` with `witnessed=true` about `DOWN_SECONDS` after hitting the floor.
- Sitting on a chair or the floor for 30 s posts nothing.
- A raised hand posts `responsive` after the hold time; flailing does not.
