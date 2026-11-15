# Within Reach

A camera sees someone fall (or sees fire). Within about a second, the nearest available person with the
Within Reach app gets an alert. They accept or pass; a pass goes to the next nearest. Accepting walks
them there on a live map with a compass arrow, picking up the nearest AED on the way (or a fire
extinguisher first, routing around the fire). At the same time an AI agent reports the emergency on a
**simulated** 911 call, and updates it as the responder moves.

Built at HackPrinceton Fall 2026. The census half (CoStar buildings in Houston and LA) is in `census/`
and unchanged.

## Live demo: run it

Everything runs on one laptop; the phone joins over the same Wi-Fi (or the laptop's hotspot).

```bash
uv sync --extra dev --extra vision
cd dashboard && npm install && cd ../mobile && npm install && cd ..
```

1. Agent: `uv run uvicorn agent.main:app --host 0.0.0.0 --port 8000`
2. Camera: `uv run python -m vision.main` (macOS asks for camera access the first time; allow it).
   First run downloads the pose model and builds the fire model (about 1 minute).
3. Dashboard: `cd dashboard && npx next dev -p 3100`, open http://localhost:3100/live, allow location
   (that is where the camera is). The annotated webcam feed, the incident, the 911 transcript and the
   map are all on this page.
4. Phone: `cd mobile && npx expo start`, scan the QR code with Expo Go. The app finds the laptop on its
   own; enter a name and keep the app open.
5. Fall in front of the webcam. Or use **Simulate fall** / **Report fire on map** on the dashboard.

| Piece | Where |
|---|---|
| Fall and fire detection, annotated feed on :8001 | `vision/` (YOLOv8-pose on COCO keypoints; YOLO-World prompted for fire/flame/smoke) |
| Nearest-first alerts, accept/decline, plans, websockets | `agent/sos/hub.py`, `agent/sos/api.py` |
| AEDs and extinguishers anywhere | OpenStreetMap via Overpass (`agent/sos/places.py`), plus pins added on the dashboard |
| Walking routes that avoid the fire | Valhalla pedestrian routing on OpenStreetMap (`agent/sos/routing.py`) |
| Simulated 911 agent | `agent/sos/call911.py` (Claude when configured, else a fact template) |
| Responder app | `mobile/` (Expo): alert, map, compass, CPR and AED help |
| Live console | `dashboard/components/live/` |

## Safety notes

- This project never calls 911. The 911 agent talks to a scripted, simulated dispatcher.
- The phone must have the app open to be alerted (no background push in Expo Go).
- GPS indoors is only accurate to several meters; inside a building the compass and distance are a
  guide, not room-level directions.
- AED and extinguisher locations are whatever OpenStreetMap has mapped, plus pins added by hand.
