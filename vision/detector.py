"""Per-track state machines that turn pose features into vision events (vision/DESIGN.md).

```
UPRIGHT -> DOWN_PENDING (down pose seen) -> DOWN (held DOWN_SECONDS) => person_down {witnessed}
DOWN: victim wrist above shoulder held   => responsive        (once)
DOWN: 1 to 5 Hz limb oscillation         => possible_seizure  (once)
DOWN: another track near the victim      => responder_arrived (once)
DOWN -> standing for a while             => clear the victim, allow a new incident
```

Rules this module enforces:

* One victim at a time: the first track to reach DOWN. Its original track id is used in every
  later event, even after the tracker switches IDs (re-association by position).
* Each event kind is emitted at most once per incident.
* Sitting never triggers: an upright torso vetoes the down pose, and once a track has been seen
  standing its hips must have dropped toward the floor.
* ``responsive`` counts only the victim's track, only a continuous hold, and never while the limbs
  are oscillating: movement alone never counts (spec section 3).

The detector is pure: the caller passes the clock (``t`` in seconds) and the tracks for each
frame, so tests drive it with synthetic keypoints and a fake clock.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from vision.config import DetectorConfig
from vision.features import (
    LIMBS,
    BBox,
    Oscillation,
    PoseFeatures,
    TrackObs,
    box_gap,
    center_distance,
    compute_features,
    iou,
    limb_oscillation,
)

PERSON_DOWN = "person_down"
RESPONSIVE = "responsive"
POSSIBLE_SEIZURE = "possible_seizure"
RESPONDER_ARRIVED = "responder_arrived"
EVENT_KINDS = (PERSON_DOWN, RESPONSIVE, POSSIBLE_SEIZURE, RESPONDER_ARRIVED)

UPRIGHT = "upright"
DOWN_PENDING = "down_pending"
DOWN = "down"


@dataclass
class VisionEvent:
    kind: str
    victim_track_id: int
    t: float  # detector clock, seconds
    witnessed: bool | None = None  # person_down only


@dataclass
class _Sample:
    t: float
    f: PoseFeatures
    down: bool


@dataclass
class StandingRef:
    height: float  # bbox height while standing, pixels
    hip_y: float  # hip image y while standing
    t: float  # time of the latest standing sample used


@dataclass
class TrackState:
    track_id: int
    first_seen: float
    last_seen: float
    last_bbox: BBox
    last_features: PoseFeatures
    down_now: bool = False
    phase: str = UPRIGHT
    down_since: float | None = None
    last_down_t: float | None = None
    ref: StandingRef | None = None
    history: deque[_Sample] = field(default_factory=deque)
    standing: deque[tuple[float, float, float]] = field(default_factory=deque)  # (t, bbox_h, hip_y)


@dataclass
class Victim:
    track_id: int  # original id, used in every event of this incident
    current_id: int  # id the tracker uses for the victim right now
    down_since: float
    witnessed: bool
    last_seen: float
    last_bbox: BBox
    body_len: float
    sent: set[str] = field(default_factory=set)
    raise_since: float | None = None
    standup_since: float | None = None
    near_since: dict[int, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pose classification
# ---------------------------------------------------------------------------


def is_upright(f: PoseFeatures, cfg: DetectorConfig) -> bool:
    return f.torso_angle is not None and f.torso_angle <= cfg.torso_upright_deg


def is_standing(f: PoseFeatures, cfg: DetectorConfig) -> bool:
    """Upright torso and, when the knees are visible, near-vertical thighs (not sitting)."""
    if not is_upright(f, cfg):
        return False
    return f.thigh_angle is None or f.thigh_angle <= cfg.thigh_standing_deg


def is_down_pose(f: PoseFeatures, ref: StandingRef | None, cfg: DetectorConfig) -> bool:
    """Spec 9.9 down pose: torso near horizontal or bbox w/h > 1.3, with the sitting guards."""
    if is_upright(f, cfg):
        return False  # standing, sitting on a chair or the floor, kneeling upright
    horizontal = f.torso_angle is not None and f.torso_angle >= cfg.torso_down_deg
    wide = f.aspect > cfg.down_aspect_ratio
    if not (horizontal or wide):
        return False
    # Seen standing before: the hips must also have dropped toward the floor. This rejects
    # bending over and leaning forward on a chair.
    hips_high = (
        ref is not None
        and f.hip_y is not None
        and ref.height > 0
        and (f.hip_y - ref.hip_y) / ref.height < cfg.hip_down_min_drop
    )
    return not hips_high


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class Detector:
    def __init__(self, cfg: DetectorConfig | None = None):
        self.cfg = cfg or DetectorConfig()
        self.tracks: dict[int, TrackState] = {}
        self.victim: Victim | None = None
        self._t = -math.inf
        c = self.cfg
        self._history_seconds = (
            max(c.down_seconds + 2 * c.witnessed_window_seconds, c.oscillation_window_seconds) + 1.0
        )

    # -- public -------------------------------------------------------------------------------

    def reset(self) -> None:
        self.tracks.clear()
        self.victim = None

    @property
    def victim_track_id(self) -> int | None:
        return None if self.victim is None else self.victim.track_id

    def phase_of(self, track_id: int) -> str | None:
        st = self.tracks.get(track_id)
        return None if st is None else st.phase

    def is_victim(self, track_id: int) -> bool:
        return self.victim is not None and self.victim.current_id == track_id

    def update(self, t: float, observations: list[TrackObs]) -> list[VisionEvent]:
        """Feed one frame. Returns the events to send, in order."""
        if t < self._t:
            raise ValueError("detector clock went backwards")
        self._t = t
        events: list[VisionEvent] = []

        present = self._ingest(t, observations)
        if self.victim is None:
            self._maybe_start_incident(t, present, events)
        if self.victim is not None:
            self._victim_signals(t, present, events)
        self._prune(t)
        return events

    # -- frame ingestion ----------------------------------------------------------------------

    def _ingest(self, t: float, observations: list[TrackObs]) -> list[TrackState]:
        cfg = self.cfg
        feats = [(o, compute_features(o, cfg.keypoint_min_conf)) for o in observations]
        seen_ids = {o.track_id for o in observations}
        new = [(o, f) for o, f in feats if o.track_id not in self.tracks]
        adopted: set[int] = set()
        for o, f in new:
            prev = self._find_predecessor(t, o, f, seen_ids, adopted)
            if prev is not None:
                adopted.add(prev.track_id)
                self._rename(prev, o.track_id)

        present: list[TrackState] = []
        for o, f in feats:
            st = self.tracks.get(o.track_id)
            if st is None:
                st = TrackState(
                    track_id=o.track_id, first_seen=t, last_seen=t, last_bbox=o.bbox, last_features=f
                )
                self.tracks[o.track_id] = st
            self._observe(st, t, o, f)
            present.append(st)
        return present

    def _find_predecessor(
        self, t: float, o: TrackObs, f: PoseFeatures, seen_ids: set[int], adopted: set[int]
    ) -> TrackState | None:
        """A recently lost track this new track ID most likely continues (tracker ID switch)."""
        cfg = self.cfg
        best: tuple[float, TrackState] | None = None
        for st in self.tracks.values():
            if st.track_id in seen_ids or st.track_id in adopted:
                continue
            gap = t - st.last_seen
            is_victim = self.victim is not None and self.victim.current_id == st.track_id
            if is_victim:
                # The victim may be hidden for a while (a helper kneeling in front). Only take it
                # over with a track that is itself lying down, so a helper never becomes the victim.
                if gap > cfg.victim_lost_clear_seconds or not is_down_pose(f, None, cfg):
                    continue
            elif gap > cfg.reassociate_max_gap_seconds:
                continue
            scale = max(st.last_features.body_len, 1.0)
            dist = center_distance(o.bbox, st.last_bbox) / scale
            if (
                iou(o.bbox, st.last_bbox) < cfg.reassociate_min_iou
                and dist > cfg.reassociate_max_center_fraction
            ):
                continue
            if best is None or dist < best[0]:
                best = (dist, st)
        return None if best is None else best[1]

    def _rename(self, st: TrackState, new_id: int) -> None:
        del self.tracks[st.track_id]
        if self.victim is not None and self.victim.current_id == st.track_id:
            self.victim.current_id = new_id
        st.track_id = new_id
        self.tracks[new_id] = st

    def _observe(self, st: TrackState, t: float, o: TrackObs, f: PoseFeatures) -> None:
        cfg = self.cfg
        st.last_seen = t
        st.last_bbox = o.bbox
        st.last_features = f

        if is_standing(f, cfg) and f.hip_y is not None and f.bbox_h > 0:
            st.standing.append((t, f.bbox_h, f.hip_y))
            while st.standing and st.standing[0][0] < t - cfg.standing_ref_seconds:
                st.standing.popleft()
            st.ref = StandingRef(
                height=float(np.median([s[1] for s in st.standing])),
                hip_y=float(np.median([s[2] for s in st.standing])),
                t=t,
            )

        down = is_down_pose(f, st.ref, cfg)
        st.down_now = down
        st.history.append(_Sample(t, f, down))
        while st.history and st.history[0].t < t - self._history_seconds:
            st.history.popleft()

        if st.phase == DOWN:
            return  # the victim's track: handled in _victim_signals
        if down:
            if st.phase == UPRIGHT:
                st.phase = DOWN_PENDING
                st.down_since = t
            st.last_down_t = t
        elif (
            st.phase == DOWN_PENDING
            and st.last_down_t is not None
            and t - st.last_down_t > cfg.down_grace_seconds
        ):
            st.phase = UPRIGHT
            st.down_since = None

    # -- incident start -----------------------------------------------------------------------

    def _maybe_start_incident(self, t: float, present: list[TrackState], events: list[VisionEvent]) -> None:
        ready = [
            st
            for st in present
            if st.phase == DOWN_PENDING
            and st.down_now
            and st.down_since is not None
            and t - st.down_since >= self.cfg.down_seconds
        ]
        if not ready:
            return
        st = min(ready, key=lambda s: (s.down_since, s.track_id))
        assert st.down_since is not None
        st.phase = DOWN
        witnessed = self._witnessed(st)
        self.victim = Victim(
            track_id=st.track_id,
            current_id=st.track_id,
            down_since=st.down_since,
            witnessed=witnessed,
            last_seen=t,
            last_bbox=st.last_bbox,
            body_len=st.last_features.body_len,
        )
        self.victim.sent.add(PERSON_DOWN)
        events.append(VisionEvent(PERSON_DOWN, st.track_id, t, witnessed=witnessed))

    def _witnessed(self, st: TrackState) -> bool:
        """Hip-y drop of more than 40% of standing height within 2 s, around going down (spec 9.9).

        Needs a standing reference from before the fall; a track first seen down is found_down.
        """
        cfg = self.cfg
        if st.ref is None or st.down_since is None or st.ref.height <= 0:
            return False
        w = cfg.witnessed_window_seconds
        samples = [(s.t, s.f.hip_y) for s in st.history if s.f.hip_y is not None]
        best = 0.0
        for ti, yi in samples:
            if not (st.down_since - w <= ti <= st.down_since + w):
                continue
            earlier = [y for tj, y in samples if ti - w <= tj <= ti]
            best = max(best, yi - min(earlier))
        return best / st.ref.height > cfg.witnessed_drop_fraction

    # -- incident signals ---------------------------------------------------------------------

    def _victim_signals(self, t: float, present: list[TrackState], events: list[VisionEvent]) -> None:
        cfg = self.cfg
        v = self.victim
        assert v is not None
        vst = self.tracks.get(v.current_id)
        visible = vst is not None and vst.last_seen == t

        if visible:
            assert vst is not None
            f = vst.last_features
            v.last_seen = t
            v.last_bbox = vst.last_bbox
            if vst.down_now:
                v.body_len = f.body_len

            if is_standing(f, cfg) and not vst.down_now:
                v.standup_since = t if v.standup_since is None else v.standup_since
                if t - v.standup_since >= cfg.standup_clear_seconds:
                    self._clear_victim(vst)
                    return
            else:
                v.standup_since = None

            osc = self.oscillation(vst, since=v.down_since, now=t)
            if osc is not None and POSSIBLE_SEIZURE not in v.sent:
                v.sent.add(POSSIBLE_SEIZURE)
                events.append(VisionEvent(POSSIBLE_SEIZURE, v.track_id, t))

            raised = f.wrist_rise is not None and f.wrist_rise >= cfg.wrist_raise_margin
            if raised and osc is None:
                v.raise_since = t if v.raise_since is None else v.raise_since
                if t - v.raise_since >= cfg.responsive_hold_seconds and RESPONSIVE not in v.sent:
                    v.sent.add(RESPONSIVE)
                    events.append(VisionEvent(RESPONSIVE, v.track_id, t))
            else:
                v.raise_since = None
        else:
            # A hold must be continuous and seen: losing the victim restarts it.
            v.raise_since = None
            v.standup_since = None
            if t - v.last_seen >= cfg.victim_lost_clear_seconds:
                self._clear_victim(vst)
                return

        self._responders(t, present, events)

    def _responders(self, t: float, present: list[TrackState], events: list[VisionEvent]) -> None:
        cfg = self.cfg
        v = self.victim
        assert v is not None
        scale = max(v.body_len, 1.0)
        here = set()
        for st in present:
            if st.track_id == v.current_id:
                continue
            duplicate = st.down_now and iou(st.last_bbox, v.last_bbox) >= cfg.duplicate_min_iou
            near = box_gap(st.last_bbox, v.last_bbox) / scale <= cfg.responder_near_fraction
            if near and not duplicate:
                here.add(st.track_id)
                since = v.near_since.setdefault(st.track_id, t)
                if t - since >= cfg.responder_hold_seconds and RESPONDER_ARRIVED not in v.sent:
                    v.sent.add(RESPONDER_ARRIVED)
                    events.append(VisionEvent(RESPONDER_ARRIVED, v.track_id, t))
        for tid in list(v.near_since):
            if tid not in here:
                del v.near_since[tid]

    def oscillation(self, st: TrackState, since: float, now: float) -> Oscillation | None:
        """Strongest rhythmic limb movement (1 to 5 Hz) in the trailing window while down."""
        cfg = self.cfg
        w = cfg.oscillation_window_seconds
        if now - since < w:
            return None
        samples = [s for s in st.history if s.t >= now - w and s.t >= since]
        if len(samples) < cfg.oscillation_min_samples:
            return None
        t = np.array([s.t for s in samples])
        body = float(np.median([s.f.body_len for s in samples]))
        if body <= 0:
            return None
        limb_xy = {
            name: np.array(
                [s.f.limbs[name] if s.f.limbs[name] is not None else (np.nan, np.nan) for s in samples]
            )
            for name in LIMBS
        }
        found = [
            o
            for o in limb_oscillation(
                t, limb_xy, cfg.seizure_min_hz, cfg.seizure_max_hz, min_samples=cfg.oscillation_min_samples
            )
            if o.amplitude / body >= cfg.oscillation_min_amplitude
            and o.peak_ratio >= cfg.oscillation_min_peak_ratio
        ]
        return max(found, key=lambda o: o.amplitude) if found else None

    def _clear_victim(self, vst: TrackState | None) -> None:
        self.victim = None
        if vst is not None:
            vst.phase = UPRIGHT
            vst.down_since = None
            vst.last_down_t = None

    def _prune(self, t: float) -> None:
        keep = None if self.victim is None else self.victim.current_id
        for tid in [
            tid for tid, st in self.tracks.items() if t - st.last_seen > self.cfg.track_forget_seconds
        ]:
            if tid != keep:
                del self.tracks[tid]
