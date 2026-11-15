"""Fire and smoke detection on the same webcam frames as the pose tracker.

Model: Ultralytics YOLO-World (``yolov8s-worldv2.pt``), an open-vocabulary detector trained on
large public detection datasets (Objects365, GoldG), prompted with the words in ``FIRE_CLASSES``.
The first run downloads the official Ultralytics weights and the CLIP text encoder once, then saves
a copy with the vocabulary baked in (``VISION_FIRE_MODEL``), so later starts need neither.

A model trained only on fire (for example on the D-Fire dataset) can be dropped in through
``VISION_FIRE_MODEL``: any Ultralytics detector whose class names include fire, flame or smoke works.

Detections flicker, so a fire is only reported after it is seen in ``min_hits`` of the last
``window`` checks, and cleared after ``clear_seconds`` without a sighting.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger("vision.fire")

FIRE_CLASSES = ["fire", "flame", "smoke"]
FIRE_WORDS = ("fire", "flame", "smoke")
BASE_WORLD_MODEL = "yolov8s-worldv2.pt"

FIRE_DETECTED = "fire_detected"
FIRE_CLEARED = "fire_cleared"


@dataclass(frozen=True)
class FireBox:
    label: str
    conf: float
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels


@dataclass
class FireEvent:
    kind: str  # FIRE_DETECTED or FIRE_CLEARED
    t: float
    label: str | None = None
    conf: float | None = None
    bbox_frac: tuple[float, float, float, float] | None = None  # box as fractions of the frame


class FireTracker:
    """Pure debounce over per-check detections. ``update`` returns events to send."""

    def __init__(self, *, min_hits: int = 3, window: int = 5, clear_seconds: float = 4.0):
        self.min_hits = min_hits
        self.clear_seconds = clear_seconds
        self._hits: deque[bool] = deque(maxlen=window)
        self.active = False
        self.last_seen: float | None = None
        self.best: FireBox | None = None

    def update(self, t: float, boxes: list[FireBox], shape: tuple[int, ...]) -> list[FireEvent]:
        seen = bool(boxes)
        self._hits.append(seen)
        if seen:
            self.last_seen = t
            self.best = max(boxes, key=lambda b: b.conf)
        events: list[FireEvent] = []
        if not self.active and sum(self._hits) >= self.min_hits and self.best is not None:
            self.active = True
            h, w = float(shape[0]), float(shape[1])
            x1, y1, x2, y2 = self.best.bbox
            events.append(FireEvent(FIRE_DETECTED, t, self.best.label, round(self.best.conf, 3),
                                    (x1 / w, y1 / h, x2 / w, y2 / h)))
        elif self.active and self.last_seen is not None and t - self.last_seen >= self.clear_seconds:
            self.active = False
            self.best = None
            self._hits.clear()
            events.append(FireEvent(FIRE_CLEARED, t))
        return events

    def reset(self) -> None:
        self._hits.clear()
        self.active = False
        self.last_seen = None
        self.best = None


class FireDetector:
    """Callable: BGR frame in, fire/smoke boxes out."""

    def __init__(self, model_path: str, *, conf: float = 0.25, imgsz: int = 640, device: str | None = None):
        from ultralytics import YOLO

        from vision.tracker import disable_ultralytics_telemetry

        disable_ultralytics_telemetry()
        path = Path(model_path)
        if path.exists():
            self.model = YOLO(str(path))
        else:
            # First run: official YOLO-World weights, prompt with our words, save with them baked in.
            path.parent.mkdir(parents=True, exist_ok=True)
            base = path.parent / BASE_WORLD_MODEL
            log.info("building the fire model from %s (one-time download)", BASE_WORLD_MODEL)
            self.model = YOLO(str(base) if base.exists() else BASE_WORLD_MODEL)
            self.model.set_classes(FIRE_CLASSES)
            try:
                self.model.save(str(path))
            except Exception as exc:  # noqa: BLE001 - saving is only a start-up speed-up
                log.warning("could not save the fire model to %s: %s", path, exc)
        names = self.model.names
        self.names: dict[int, str] = dict(names) if isinstance(names, dict) else dict(enumerate(names))
        self.keep = {i for i, n in self.names.items() if any(w in str(n).lower() for w in FIRE_WORDS)}
        if not self.keep:
            raise ValueError(f"{model_path}: no fire, flame or smoke class in {sorted(self.names.values())}")
        self.conf = conf
        self.imgsz = imgsz
        self.device = device

    def __call__(self, frame: np.ndarray) -> list[FireBox]:
        kwargs: dict[str, Any] = {"conf": self.conf, "imgsz": self.imgsz, "verbose": False, "save": False,
                                  "classes": sorted(self.keep)}
        if self.device:
            kwargs["device"] = self.device
        results = self.model.predict(frame, **kwargs)
        if not results or results[0].boxes is None:
            return []
        b = results[0].boxes
        out = []
        for xyxy, c, cls in zip(_np(b.xyxy), _np(b.conf), _np(b.cls).astype(int), strict=False):
            if int(cls) in self.keep:
                out.append(FireBox(str(self.names[int(cls)]), float(c), tuple(float(v) for v in xyxy)))  # type: ignore[arg-type]
        return out

    def warm_up(self, shape: tuple[int, int, int] = (480, 640, 3)) -> None:
        self(np.zeros(shape, dtype=np.uint8))


def _np(x: Any) -> np.ndarray:
    if hasattr(x, "cpu"):
        x = x.cpu()
    if hasattr(x, "numpy"):
        x = x.numpy()
    return np.asarray(x)
