"""Pose tracking with Ultralytics YOLOv8n-pose and ``model.track(persist=True)``.

API checked against the installed ultralytics 8.4.x:
``model.track(source, persist=True, ...)`` returns a list of ``Results``; ``result.boxes.id`` is
``None`` until the tracker has confirmed tracks, ``result.boxes.xyxy`` is (N, 4) and
``result.keypoints.data`` is (N, 17, 3) with x, y, confidence in original-image pixels.

Nothing is saved: ``save=False`` and no frame ever leaves this function.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from vision.features import NUM_KEYPOINTS, TrackObs

PERSON_CLASS = 0  # COCO "person"


def _np(x: Any) -> np.ndarray:
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        x = x.numpy()
    return np.asarray(x)


def tracks_from_result(result: Any) -> list[TrackObs]:
    """Convert one Ultralytics ``Results`` into ``TrackObs`` (only boxes with a track id)."""
    boxes = getattr(result, "boxes", None)
    kps = getattr(result, "keypoints", None)
    if boxes is None or kps is None or boxes.id is None or len(boxes) == 0:
        return []
    ids = _np(boxes.id).astype(int)
    xyxy = _np(boxes.xyxy).astype(float)
    data = _np(kps.data).astype(float)
    if data.ndim != 3 or data.shape[1] != NUM_KEYPOINTS:
        return []
    out = []
    for i, tid in enumerate(ids):
        conf = data[i, :, 2] if data.shape[2] >= 3 else None
        out.append(
            TrackObs(
                track_id=int(tid),
                bbox=tuple(float(v) for v in xyxy[i]),  # type: ignore[arg-type]
                keypoints=data[i, :, :2].copy(),
                kp_conf=None if conf is None else conf.copy(),
            )
        )
    return out


def disable_ultralytics_telemetry() -> None:
    """Turn off Ultralytics' anonymous usage analytics for this process (no settings file change)."""
    try:
        from ultralytics.utils import events as ul_events

        ul_events.events.enabled = False
    except (ImportError, AttributeError):  # internal API; never fail the camera loop over it
        return


class PoseTracker:
    """Callable: BGR frame in, tracked people out. Keeps tracker state between calls."""

    def __init__(
        self,
        model_path: str,
        tracker: str = "bytetrack.yaml",
        imgsz: int = 640,
        device: str | None = None,
    ):
        from ultralytics import YOLO

        disable_ultralytics_telemetry()
        self.model = YOLO(model_path)
        self.tracker = tracker
        self.imgsz = imgsz
        self.device = device

    def __call__(self, frame: np.ndarray) -> list[TrackObs]:
        kwargs: dict[str, Any] = {
            "persist": True,
            "tracker": self.tracker,
            "classes": [PERSON_CLASS],
            "imgsz": self.imgsz,
            "verbose": False,
            "save": False,
        }
        if self.device:
            kwargs["device"] = self.device
        results = self.model.track(frame, **kwargs)
        return tracks_from_result(results[0]) if results else []

    def warm_up(self, shape: tuple[int, int, int] = (480, 640, 3)) -> None:
        """Run once on a blank frame so the first real frame is not slow (spec 9.8 warm-up)."""
        self(np.zeros(shape, dtype=np.uint8))
