# demo/clips: vision tuning set

Six short videos and, next to each, a JSON file with the events the detector must produce. Until
these clips are recorded and pass, every UNTUNED constant in `vision/config.py` is a placeholder.

The JSON files are here already. The videos are a team task: record them, drop them in this folder
with the exact file names below, and run the check.

| Clip | What happens | Must produce (and nothing else) |
|---|---|---|
| `fall_witnessed.mp4` | stand 3 s, quick sideways collapse, lie still 15 s | `person_down` with `witnessed: true` |
| `lie_down_slowly.mp4` | stand 3 s, lie down slowly over 5 to 6 s, lie still 15 s | `person_down` with `witnessed: false` |
| `sit_down.mp4` | chair 30 s, then the floor with legs out 30 s | nothing |
| `fall_then_raise_hand.mp4` | collapse, lie still 8 s, raise one arm straight up and hold 3 s | `person_down` (witnessed), `responsive` |
| `fall_then_shake.mp4` | collapse, shake arms and legs rhythmically for 10 s | `person_down` (witnessed), `possible_seizure` |
| `fall_then_helper_arrives.mp4` | collapse; about 8 s later a second person kneels beside for 10 s | `person_down` (witnessed), `responder_arrived` |

The exact scenario text for whoever performs it is in the `scenario` field of each JSON.

## Recording

- Use the demo camera and position: about 2 m high over the taped-off zone, the whole body in view
  standing and lying, falls sideways across the frame onto a mat. Same lighting as the demo.
- Constant frame rate (a laptop webcam recording, or a phone set to 30 fps). Replay timing is
  frame index / fps, so variable-frame-rate phone video should be converted first:
  `ffmpeg -i in.mov -vf fps=30 -an fall_witnessed.mp4`.
- Keep each clip short: start a few seconds before the action, stop a few seconds after.
- Only teammates who agree to be filmed. The videos show real people, so `.gitignore` here keeps
  video files out of the repo. Share them with the team directly, and commit one only if
  everyone in it agrees.

## Checking

```
uv run python -m vision.replay --all demo/clips                    # every clip with a JSON
uv run python -m vision.replay demo/clips/sit_down.mp4 --check     # one clip
uv run python -m vision.replay demo/clips/fall_then_shake.mp4 --set oscillation_min_peak_ratio=0.3
```

Exit status: 0 all recorded clips pass, 1 a clip fails, 2 clips are missing (none failed).
Each run prints the events as JSON lines with their time in the clip, then PASS or FAIL with the
reason.

## Tuning

1. Run `--all`. For a failing clip, read which event is missing, extra, or has the wrong
   `witnessed`.
2. Try one `--set name=value` at a time on that clip (names and meanings: `vision/config.py`).
3. Rerun `--all` with the new value: a fix for one clip must not break another.
4. Put the winning values in `.env` as `VISION_<NAME>=value` (or `DOWN_SECONDS`,
   `RESPONSIVE_HOLD_SECONDS`), and change the defaults in `vision/config.py`, replacing the word
   UNTUNED with "tuned on demo/clips, <date>".

## Expected-events JSON format

```json
{
  "clip": "fall_then_raise_hand.mp4",
  "scenario": "what the person does",
  "setup": "camera placement",
  "events": [
    {"kind": "person_down", "witnessed": true},
    {"kind": "responsive", "min_t": 10.0, "max_t": 20.0}
  ],
  "allow_other_events": false
}
```

- `events`: the ordered events the clip must produce. `kind` is one of `person_down`,
  `responsive`, `possible_seizure`, `responder_arrived`.
- `witnessed` (optional, `person_down` only): the expected value.
- `min_t`, `max_t` (optional): window in seconds from the start of the clip. Add them after
  recording if timing matters.
- `allow_other_events`: `false` means exactly these events and nothing else; `true` means these in
  this order, with anything else allowed in between.
- Every event after a `person_down` must name that `person_down`'s victim track.

The harness is `vision/replay.py` (`check_events`), with its tests in `vision/tests/`.
