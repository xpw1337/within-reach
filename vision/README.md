# vision/

Live person-down detection (spec section 9.9): webcam in, `POST /events` out. It is a standalone
process that imports no other repo package, so the same code can run on a laptop or a Raspberry Pi.
The design is in `DESIGN.md`. The HTTP contract is `docs/CONTRACTS.md` section 2.

```
main.py      capture loop, CLI flags, skeleton-only debug overlay
config.py    env settings; detector constants (spec values and UNTUNED placeholders)
tracker.py   Ultralytics YOLOv8n-pose, model.track(persist=True) -> TrackObs
features.py  pure pose features: torso angle, bbox aspect, hip height, wrist above shoulder, limb oscillation
detector.py  per-track state machine -> person_down / responsive / possible_seizure / responder_arrived
client.py    POST /events with retry; the privacy rules
replay.py    run the detector over a video file; check it against an expected-events JSON
tests/       unit tests on synthetic keypoints (no images of people)
```

## Setup

```
uv sync --extra dev --extra vision
uv pip install lap          # ByteTrack needs it; until it is added to the vision extra in pyproject.toml
uv run pytest vision
```

The pose weights (`yolov8n-pose.pt`, about 6.5 MB) download on first use into `.cache/models/`,
which is git-ignored. Ultralytics' anonymous usage analytics are switched off in-process by
`tracker.py`; to switch them off for good on a machine, run `uv run yolo settings sync=False`.

## Run

```
uv run python -m vision.main --dry-run      # print events, post nothing
uv run python -m vision.main                # post to AGENT_URL
uv run python -m vision.main --no-overlay   # headless
```

| Flag | Env | Default |
|---|---|---|
| `--camera` | `CAMERA_INDEX` | `0` |
| `--camera-id` | `CAMERA_ID` | `cam-lobby-1` |
| `--agent-url` | `AGENT_URL` | `http://localhost:8000` |
| `--model` | `VISION_MODEL` | `.cache/models/yolov8n-pose.pt` |
| `--tracker` | `VISION_TRACKER` | `bytetrack.yaml` |
| `--imgsz` | `VISION_IMGSZ` | `640` |
| `--device` | | Ultralytics default |
| `--width`, `--height` | | camera default |
| `--set name=value` | `DOWN_SECONDS`, `RESPONSIVE_HOLD_SECONDS`, `VISION_<NAME>` | see `config.py` |

Keys in the overlay window: `q` quits, `r` resets the detector (forgets the current victim).
Colors: green upright, yellow down pending, red victim.

## Detection rules

| Signal | Rule | Constants |
|---|---|---|
| down | torso near horizontal, or bbox w/h > 1.3, held for `DOWN_SECONDS` | spec: 1.3, `DOWN_SECONDS`; untuned: "near horizontal" angle |
| not down | an upright torso vetoes it (sitting on a chair or the floor); once seen standing, the hips must also have dropped toward the floor (bending over) | untuned |
| witnessed | hip-y drop > 40% of standing height within 2 s around going down | spec |
| found_down | down when first seen, or went down slowly | |
| responsive | the victim's track only: wrist above the higher shoulder, held `RESPONSIVE_HOLD_SECONDS` without a break, and never while the limbs oscillate | spec: hold; untuned: margin |
| possible_seizure | a true spectral peak at 1 to 5 Hz in a wrist or ankle track while down | spec: band; untuned: window, amplitude, peak share |
| responder_arrived | another track within a short distance of the victim for a short hold | untuned |

One victim at a time (the first track to reach DOWN); its track id is in every later event, also
after a tracker ID switch. Each kind is sent once per incident. The victim standing up, or being
unseen for a long time, ends the incident on the vision side.

Every constant without a spec number is marked UNTUNED in `config.py`. They stay untuned until the
six clips in `demo/clips/` are recorded and pass (`demo/clips/README.md`).

Known limits, to check with the clips:

- The rules assume the fall is roughly sideways across the image. A person lying straight toward
  or away from the camera is foreshortened (short torso, narrow box) and may not count as down.
  Place the taped zone so the demo fall is across the frame.
- Seizure detection needs about twice the oscillation rate in frames per second. At 10 fps the
  top of the 1 to 5 Hz band is out of reach; frequencies above half the frame rate are never reported.
- A person first seen sitting gives a sitting height as the standing reference, so a fall from
  that chair is likely reported as found_down.

## Privacy (enforced in client.py and main.py)

- Frames leave the device only inside a `person_down` event: one JPEG, longest side 640 px. A frame
  passed with any other event kind is dropped.
- Encoding is in memory. Nothing is written to disk. No face detection, blurring or recognition.
- The overlay draws skeletons on a black canvas; the camera image is never shown.
- A test scans the vision sources for disk writes and face libraries.

## Live acceptance (needs a person, a webcam and the camera permission prompt)

Not verified yet. Steps for a human, on the demo laptop:

1. Mount the camera about 2 m high looking at a taped-off zone with a mat. Make sure the whole
   body is in view standing and lying, and that a fall goes sideways across the frame.
2. `uv run python -m vision.main --dry-run`. On macOS the first run asks for camera access for
   the terminal app: allow it, then run again. A window with skeletons only should open, and the
   log line `DOWN_SECONDS=5.0 RESPONSIVE_HOLD_SECONDS=1.5` confirms the settings.
3. Collapse: stand in the zone for 3 s, drop onto the mat, stay still. Expect, about 5 s after
   hitting the floor, one log line
   `event (dry run) {"camera_id": "cam-lobby-1", "kind": "person_down", "victim_track_id": N, "ts": "...", "witnessed": true, "frame_jpeg_b64": "<jpeg, ... bytes>"}`.
4. Raised hand: still lying, raise one arm straight up and hold it for 2 s. Expect one
   `"kind": "responsive"` line with the same `victim_track_id`. Press `r`.
5. Flailing: fall again; after `person_down`, wave both arms up and down quickly for 5 s. Expect
   no `responsive` line (`possible_seizure` may appear). Press `r`.
6. Sitting: sit on a chair for 30 s, then on the floor with legs stretched out for 30 s. Expect no
   event lines at all.
7. Slow lie-down: lie down slowly over about 5 s. Expect `person_down` with `"witnessed": false`.
   Press `r`.
8. Helper: fall; after `person_down` a second person walks up and kneels beside you. Expect one
   `"kind": "responder_arrived"` line about 2 s after they arrive.
9. With the agent: start `agent/` (see its README) and run `uv run python -m vision.main` without
   `--dry-run`. Repeat step 3. Expect the log line `sent person_down -> {'incident_id': '...', 'status': '...'}`
   and the incident on the dashboard `/live` page.

If a step fails, record that scenario as a clip (`demo/clips/README.md`), replay it with
`uv run python -m vision.replay <clip> --set name=value` to find a setting that works, and put the
new value in `.env` as `VISION_<NAME>`.

## Raspberry Pi (stretch, not started)

`requirements-pi.txt` lists the minimal dependencies. Use `--no-overlay`, a smaller `--imgsz`
and measure the frame rate before relying on it (seizure detection needs a high enough rate).
