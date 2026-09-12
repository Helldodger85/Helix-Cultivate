"""Tests for a Part 1 audit finding: _check_sensor_dropout() hardcoded the
DEFAULT_SENSOR_DROPOUT_MIN constant instead of reading the actual persisted
CONF_SENSOR_DROPOUT_MIN config value — so the Dropout Timeout setting
(whether set via the Options Flow at setup, or now the live Sensor Dropout
Timeout number entity) was silently never consulted by the detection logic
it was supposed to control. Worse than the Safety-tab-slider symptom this
session set out to fix: even a value that DID persist correctly had no
effect at all.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_SENSOR_DROPOUT_MIN,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from homeassistant.util import dt as dt_util


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {CONF_PRIMARY_TEMP_SENSOR: "sensor.canopy_temp"}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._primary_last_seen = dt_util.utcnow() - timedelta(minutes=10)
    coord.hass = MagicMock()

    coord._check_sensor_dropout = lambda: HelixCoordinator._check_sensor_dropout(coord)
    return coord


def test_uses_configured_dropout_minutes_not_hardcoded_default(fake_coord):
    """A stale sensor at 10 minutes must NOT trip dropout when the grower
    has configured a 30-minute timeout (the hardcoded-default bug would
    have used a fixed value regardless of this config)."""
    fake_coord._config[CONF_SENSOR_DROPOUT_MIN] = 30
    fake_coord.hass.states.get.return_value = MagicMock(state="unavailable")

    assert fake_coord._check_sensor_dropout() is False


def test_trips_once_stale_duration_exceeds_configured_minutes(fake_coord):
    """The same 10-minute-stale sensor DOES trip once the grower configures
    a shorter timeout than the staleness duration."""
    fake_coord._config[CONF_SENSOR_DROPOUT_MIN] = 5
    fake_coord.hass.states.get.return_value = MagicMock(state="unavailable")

    assert fake_coord._check_sensor_dropout() is True


def test_falls_back_to_default_when_unconfigured(fake_coord):
    """No CONF_SENSOR_DROPOUT_MIN in config (never configured) — falls back
    to the coded default rather than raising or misbehaving."""
    fake_coord._config.pop(CONF_SENSOR_DROPOUT_MIN, None)
    fake_coord.hass.states.get.return_value = MagicMock(state="unavailable")

    # 10 minutes stale, default is 30 — should not have tripped yet.
    assert fake_coord._check_sensor_dropout() is False
