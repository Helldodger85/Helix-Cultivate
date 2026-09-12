"""Tests for Part 1: the Safety tab's five sliders (high/low temp cutoffs,
high/low humidity cutoffs, sensor dropout timeout) were display-only — no
event listener persisted anything anywhere. Fix: each now has its own live
HA number entity (matching the existing, already-working heater_cutoff_c/
thermal_runaway_c pattern) built via the same _persistent_setter factory,
so dragging a slider calls number.set_value on a real entity that writes
straight to the config entry via queue_option_write — not the Save-button/
queue_option_write-only draft-config pattern used for dimension fields.
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
    DOMAIN,
    NUMBER_SAFETY_HIGH_RH,
    NUMBER_SAFETY_HIGH_TEMP,
    NUMBER_SAFETY_LOW_RH,
    NUMBER_SAFETY_LOW_TEMP,
    NUMBER_SENSOR_DROPOUT_MIN,
)
from custom_components.helix_cultivate.number import NUMBER_DESCRIPTIONS, HelixNumber


def _description(key):
    for desc in NUMBER_DESCRIPTIONS:
        if desc.key == key:
            return desc
    raise AssertionError(f"no NUMBER_DESCRIPTIONS entry for key={key!r}")


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord.queue_option_write = MagicMock(
        side_effect=lambda k, v: coord._config.__setitem__(k, v)
    )
    return coord


@pytest.mark.parametrize("key,config_key,default", [
    (NUMBER_SAFETY_HIGH_TEMP, CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C),
    (NUMBER_SAFETY_LOW_TEMP, CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C),
    (NUMBER_SAFETY_HIGH_RH, CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT),
    (NUMBER_SAFETY_LOW_RH, CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT),
    (NUMBER_SENSOR_DROPOUT_MIN, CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG),
])
def test_default_value_matches_existing_config_default(key, config_key, default):
    desc = _description(key)
    coord = MagicMock()
    coord._config = {}
    assert desc.value_fn(coord) == pytest.approx(float(default))


@pytest.mark.parametrize("key,config_key,new_value", [
    (NUMBER_SAFETY_HIGH_TEMP, CONF_SAFETY_HIGH_TEMP_C, 35.0),
    (NUMBER_SAFETY_LOW_TEMP, CONF_SAFETY_LOW_TEMP_C, 10.0),
    (NUMBER_SAFETY_HIGH_RH, CONF_SAFETY_HIGH_RH_PCT, 90.0),
    (NUMBER_SAFETY_LOW_RH, CONF_SAFETY_LOW_RH_PCT, 20.0),
    (NUMBER_SENSOR_DROPOUT_MIN, CONF_SENSOR_DROPOUT_MIN, 45),
])
def test_set_fn_persists_via_queue_option_write(fake_coord, key, config_key, new_value):
    desc = _description(key)

    desc.set_fn(fake_coord, new_value)

    fake_coord.queue_option_write.assert_called_once()
    written_key, written_value = fake_coord.queue_option_write.call_args.args
    assert written_key == config_key
    assert written_value == pytest.approx(float(new_value))
    assert fake_coord._config[config_key] == pytest.approx(float(new_value))


@pytest.mark.parametrize("key,config_key,new_value", [
    (NUMBER_SAFETY_HIGH_TEMP, CONF_SAFETY_HIGH_TEMP_C, 33.5),
    (NUMBER_SAFETY_LOW_TEMP, CONF_SAFETY_LOW_TEMP_C, 8.0),
    (NUMBER_SAFETY_HIGH_RH, CONF_SAFETY_HIGH_RH_PCT, 77.0),
    (NUMBER_SAFETY_LOW_RH, CONF_SAFETY_LOW_RH_PCT, 25.0),
    (NUMBER_SENSOR_DROPOUT_MIN, CONF_SENSOR_DROPOUT_MIN, 60),
])
def test_value_survives_simulated_reload(fake_coord, key, config_key, new_value):
    """Set once, then read back from a *fresh* coordinator-like object built
    from the same persisted config — simulating a page reload / restart."""
    desc = _description(key)
    desc.set_fn(fake_coord, new_value)

    reloaded = MagicMock()
    reloaded._config = dict(fake_coord._config)

    assert desc.value_fn(reloaded) == pytest.approx(float(new_value))


@pytest.mark.parametrize("key", [
    NUMBER_SAFETY_HIGH_TEMP,
    NUMBER_SAFETY_LOW_TEMP,
    NUMBER_SAFETY_HIGH_RH,
    NUMBER_SAFETY_LOW_RH,
    NUMBER_SENSOR_DROPOUT_MIN,
])
def test_entity_id_pinned_to_stable_key(key):
    """HelixNumber must pin entity_id itself (not rely on HA's name-derived
    slug), matching HelixSensor/HelixSelect — otherwise the frontend's
    hardcoded number.helix_cultivate_{key} service calls hit nothing."""
    desc = _description(key)
    coordinator = MagicMock()
    coordinator._entry.entry_id = "entry123"

    entity = HelixNumber(coordinator, desc)

    assert entity.entity_id == f"number.{DOMAIN}_{key}"


def test_ranges_match_existing_frontend_slider_bounds():
    """The number entity's min/max/step must match the JS slider ranges
    already rendered in HelixTabSettings._renderSafety(), or the entity
    would silently clamp values the slider itself allows."""
    expectations = {
        NUMBER_SAFETY_HIGH_TEMP: (26.0, 40.0, 0.5),
        NUMBER_SAFETY_LOW_TEMP: (5.0, 20.0, 0.5),
        NUMBER_SAFETY_HIGH_RH: (60.0, 95.0, 1.0),
        NUMBER_SAFETY_LOW_RH: (15.0, 50.0, 1.0),
        NUMBER_SENSOR_DROPOUT_MIN: (5.0, 120.0, 1.0),
    }
    for key, (lo, hi, step) in expectations.items():
        desc = _description(key)
        assert desc.native_min_value == lo
        assert desc.native_max_value == hi
        assert desc.native_step == step
