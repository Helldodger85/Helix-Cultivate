"""Tests for a Part 1 gap found while wiring the Safety tab sliders to their
new live number entities: the dashboard panel reads its *displayed* values
from the exhaust_speed sensor's extra_state_attributes (not the number
entity states directly — see helix-panel.js's this._attr('exhaust_speed',
...) calls), matching the existing pattern for dew_point_margin_c and the
v1.2.8 settings. Without exposing safety_high_temp_c/safety_low_temp_c/
safety_high_rh_pct/safety_low_rh_pct/sensor_dropout_min here too, a slider
would persist correctly under the hood (Part 1's number-entity fix) but
still visually reset to the coded default on every reload — the exact
symptom this session set out to fix, just moved one layer down.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_SAFETY_HIGH_RH_PCT,
    CONF_SAFETY_HIGH_TEMP_C,
    CONF_SAFETY_LOW_RH_PCT,
    CONF_SAFETY_LOW_TEMP_C,
    CONF_SENSOR_DROPOUT_MIN,
    DEFAULT_SAFETY_HIGH_RH_PCT,
    DEFAULT_SAFETY_HIGH_TEMP_C,
    DEFAULT_SAFETY_LOW_RH_PCT,
    DEFAULT_SAFETY_LOW_TEMP_C,
    DEFAULT_SENSOR_DROPOUT_MIN_CFG,
    SENSOR_EXHAUST_SPEED,
)
from custom_components.helix_cultivate.sensor import SENSOR_DESCRIPTIONS, HelixSensor


def _description(key):
    for desc in SENSOR_DESCRIPTIONS:
        if desc.key == key:
            return desc
    raise AssertionError(f"no SENSOR_DESCRIPTIONS entry for key={key!r}")


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.data = {}
    coord._entry.entry_id = "entry123"
    return coord


def _make_exhaust_entity(coord):
    desc = _description(SENSOR_EXHAUST_SPEED)
    return HelixSensor(coord, desc)


@pytest.mark.parametrize("config_key,default", [
    (CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C),
    (CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C),
    (CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT),
    (CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT),
    (CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG),
])
def test_default_exposed_when_unconfigured(fake_coord, config_key, default):
    entity = _make_exhaust_entity(fake_coord)
    assert entity.extra_state_attributes[config_key] == default


@pytest.mark.parametrize("config_key,persisted_value", [
    (CONF_SAFETY_HIGH_TEMP_C, 35.5),
    (CONF_SAFETY_LOW_TEMP_C, 9.0),
    (CONF_SAFETY_HIGH_RH_PCT, 91.0),
    (CONF_SAFETY_LOW_RH_PCT, 22.0),
    (CONF_SENSOR_DROPOUT_MIN, 60),
])
def test_persisted_value_is_reflected_after_simulated_reload(fake_coord, config_key, persisted_value):
    """The exact reload-survival check the ticket asks for, one layer down
    from the number entity itself: once a value is persisted to the config
    entry, a *freshly built* sensor entity reading from that same config
    must expose the real value, not the coded default."""
    fake_coord._config[config_key] = persisted_value

    reloaded = MagicMock()
    reloaded._config = dict(fake_coord._config)
    reloaded._get = lambda key, default=None: reloaded._config.get(key, default)
    reloaded.data = {}
    reloaded._entry.entry_id = "entry123"
    entity = _make_exhaust_entity(reloaded)

    assert entity.extra_state_attributes[config_key] == persisted_value
