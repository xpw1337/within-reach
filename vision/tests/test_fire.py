from vision.client import build_payload
from vision.fire import FIRE_CLEARED, FIRE_DETECTED, FireBox, FireEvent, FireTracker

SHAPE = (100, 200, 3)
BOX = FireBox("fire", 0.8, (20.0, 10.0, 60.0, 50.0))


def test_fire_needs_repeated_sightings_then_clears():
    ft = FireTracker(min_hits=3, window=5, clear_seconds=2.0)
    assert ft.update(0.0, [BOX], SHAPE) == []
    assert ft.update(0.1, [], SHAPE) == []
    assert ft.update(0.2, [BOX], SHAPE) == []
    ev = ft.update(0.3, [BOX], SHAPE)
    assert [e.kind for e in ev] == [FIRE_DETECTED]
    assert ev[0].bbox_frac == (0.1, 0.1, 0.3, 0.5)
    assert ft.update(1.0, [], SHAPE) == []  # still within clear_seconds
    assert [e.kind for e in ft.update(2.4, [], SHAPE)] == [FIRE_CLEARED]


def test_single_flicker_never_reports():
    ft = FireTracker(min_hits=3, window=5)
    for i in range(20):
        assert ft.update(i * 0.1, [BOX] if i % 4 == 0 else [], SHAPE) == []


def test_fire_payload_has_no_track_or_frame():
    p = build_payload("cam", FireEvent(FIRE_DETECTED, 0.0, "fire", 0.8, (0.1, 0.1, 0.3, 0.5)), 1.7e9)
    assert p["kind"] == FIRE_DETECTED and "victim_track_id" not in p and "frame_jpeg_b64" not in p
    assert p["fire"]["label"] == "fire"
