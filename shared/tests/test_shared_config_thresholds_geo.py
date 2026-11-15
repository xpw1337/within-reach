import math

import pytest

from shared import thresholds
from shared.config import MissingSettingError, Settings, get_settings
from shared.fakes import isolate_settings
from shared.geo import haversine_m, nearest, within_geofence

# ---------------------------------------------------------------- config


def test_defaults_match_spec():
    s = get_settings()
    assert s.claude_model_reasoning == "claude-sonnet-5-5"
    assert s.claude_model_fast == "claude-haiku-5-5"
    assert s.use_bedrock is True
    assert s.aws_region == "us-east-1"
    assert s.census_budget_usd == 150
    assert s.detect_min_conf == 0.35
    assert s.walk_speed_mps == 1.4
    assert s.aed_roundtrip_target_s == 180
    assert s.ext_max_travel_m == 22.9
    assert s.exit_max_travel_m == 61
    assert s.witnessed_down_seconds == 0.8
    assert s.accept_timeout_seconds == 20
    assert s.responsive_hold_seconds == 1.5
    assert s.camera_id == "webcam-1"
    assert s.anthropic_api_key is None


def test_every_env_example_variable_is_a_setting():
    from shared.config import REPO_ROOT

    names = []
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            names.append(line.split("=", 1)[0].strip().lower())
    missing = [n for n in names if n not in Settings.model_fields]
    assert not missing, missing


def test_env_overrides_and_empty_values(monkeypatch):
    s = isolate_settings(monkeypatch, WALK_SPEED_MPS="1.2", USE_BEDROCK="false", ANTHROPIC_API_KEY="")
    assert s.walk_speed_mps == 1.2
    assert s.use_bedrock is False
    assert s.anthropic_api_key is None  # empty counts as unset


def test_get_settings_is_cached():
    assert get_settings() is get_settings()


def test_require_names_missing_variables():
    with pytest.raises(MissingSettingError) as e:
        get_settings().require("supabase_url", "supabase_service_role_key", "aws_region")
    assert "SUPABASE_URL" in str(e.value) and "SUPABASE_SERVICE_ROLE_KEY" in str(e.value)
    assert "AWS_REGION" not in str(e.value)


# ---------------------------------------------------------------- thresholds


def test_limit_seconds_defaults():
    assert thresholds.limit_seconds("aed") == 90.0  # 180 s round trip -> 90 s one way
    assert thresholds.limit_seconds("extinguisher") == pytest.approx(22.9 / 1.4)
    assert thresholds.limit_seconds("exit") == pytest.approx(61 / 1.4)


@pytest.mark.parametrize("asset_type", ["aed", "extinguisher", "exit"])
def test_zone_boundaries(asset_type):
    limit = thresholds.limit_seconds(asset_type)
    yellow = thresholds.YELLOW_FRACTION * limit
    assert thresholds.zone(asset_type, None) == "unknown"
    assert thresholds.zone(asset_type, 0.0) == "green"
    assert thresholds.zone(asset_type, yellow) == "green"  # at the yellow edge: still green
    assert thresholds.zone(asset_type, math.nextafter(yellow, math.inf)) == "yellow"
    assert thresholds.zone(asset_type, limit) == "yellow"  # at the limit: not yet red
    assert thresholds.zone(asset_type, math.nextafter(limit, math.inf)) == "red"
    assert thresholds.zone(asset_type, limit * 10) == "red"


def test_aed_zone_examples():
    # One-way seconds. 60 s one way is a 120 s round trip: exactly the yellow edge (2/3 of 180).
    assert thresholds.zone("aed", 60.0) == "green"
    assert thresholds.zone("aed", 60.5) == "yellow"
    assert thresholds.zone("aed", 90.0) == "yellow"
    assert thresholds.zone("aed", 90.5) == "red"


def test_zone_follows_settings(monkeypatch):
    isolate_settings(monkeypatch, AED_ROUNDTRIP_TARGET_S="240")
    assert thresholds.limit_seconds("aed") == 120.0
    assert thresholds.zone("aed", 100.0) == "yellow"


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        thresholds.zone("sprinkler", 3.0)


def test_display_conversions():
    assert thresholds.aed_display_seconds(70.0) == 140.0
    assert thresholds.aed_display_seconds(None) is None
    assert thresholds.display_seconds("aed", 30.0) == 60.0
    assert thresholds.display_seconds("exit", 30.0) == 30.0
    assert thresholds.travel_m(10.0) == pytest.approx(14.0)
    assert thresholds.seconds_for_distance(14.0) == pytest.approx(10.0)


def test_thresholds_payload_shape():
    p = thresholds.thresholds_payload()
    assert set(p) == {
        "walk_speed_mps",
        "aed_roundtrip_target_s",
        "ext_max_travel_m",
        "exit_max_travel_m",
        "yellow_fraction",
    }
    assert p["yellow_fraction"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------- geo


def test_haversine_known_values():
    assert haversine_m(29.76, -95.37, 29.76, -95.37) == 0.0
    # One degree of latitude on the mean-radius sphere: pi * R / 180.
    assert haversine_m(0, 0, 1, 0) == pytest.approx(math.pi * 6_371_008.8 / 180, rel=1e-9)
    # Symmetric
    a = haversine_m(29.7604, -95.3698, 34.0522, -118.2437)
    b = haversine_m(34.0522, -118.2437, 29.7604, -95.3698)
    assert a == pytest.approx(b)
    assert 2.1e6 < a < 2.3e6  # Houston to Los Angeles is roughly 2,200 km


def test_geofence_and_nearest():
    center = (29.7604, -95.3698)
    north_50m = (29.7604 + 50 / 111_195, -95.3698)
    assert within_geofence(*north_50m, *center, 60)
    assert not within_geofence(*north_50m, *center, 40)
    assert not within_geofence(None, None, *center, 60)
    pts = [
        {"lat": 29.0, "lng": -95.0, "n": 1},
        {"lat": 29.76, "lng": -95.37, "n": 2},
        {"lat": None, "lng": 1},
    ]
    best, d = nearest(*center, pts)
    assert best["n"] == 2 and d < 100
    assert nearest(*center, []) is None
