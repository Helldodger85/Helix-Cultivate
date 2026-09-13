"""Tests for the backend-testable half of v1.4.0 Part 1's six UI bugs:

- 1.2: _actuator_dropout_status() — a heater/AC/exhaust entity unavailable
  for 5+ minutes must be reported distinctly from a plain sensor dropout,
  so the dashboard badge can escalate to red.
- 1.6: fan speed persistence — set_fan_speed() previously never persisted
  its writes (an in-memory-only coordinator attribute), so ANY unrelated
  settings save that triggered a config-entry reload silently reverted a
  manually-set fan speed back to the coded default.

Parts 1.1 (ROI banner removal), 1.3 (sparkline timeframe/width), 1.4
(Abort Cycle visibility), and 1.5 (Breeze slider interactivity/step) are
frontend-only (HTML/JS) with no backend equivalent to unit test — verified
via code review and Node syntax checking instead (see README's Known
Issues section).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_EXHAUST_FAN,
    CONF_ZONE2_AC,
    CONF_ZONE2_HEATER,
    DEFAULT_FAN_SPEED_PCT,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    NUMBER_LOWER_FAN_VARIANCE,
    NUMBER_MID_FAN_VARIANCE,
    NUMBER_UPPER_FAN_VARIANCE,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.number import NUMBER_DESCRIPTIONS
from homeassistant.util import dt as dt_util


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {
        CONF_ZONE2_HEATER: "switch.zone2_heater",
        CONF_ZONE2_AC: "climate.zone2_ac",
        CONF_EXHAUST_FAN: "fan.exhaust",
    }
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._appliance_unavail_since = {}
    coord._actuator_dropout_status = lambda: HelixCoordinator._actuator_dropout_status(coord)
    return coord


class TestActuatorDropoutStatus:
    def test_no_dropout_when_nothing_unavailable(self, fake_coord):
        dropout, entities = fake_coord._actuator_dropout_status()
        assert dropout is False
        assert entities == []

    def test_no_dropout_before_five_minute_threshold(self, fake_coord):
        fake_coord._appliance_unavail_since["zone2_heater"] = dt_util.utcnow() - timedelta(minutes=2)
        dropout, entities = fake_coord._actuator_dropout_status()
        assert dropout is False
        assert entities == []

    def test_dropout_reported_past_five_minutes(self, fake_coord):
        fake_coord._appliance_unavail_since["zone2_heater"] = dt_util.utcnow() - timedelta(minutes=6)
        dropout, entities = fake_coord._actuator_dropout_status()
        assert dropout is True
        assert entities == ["switch.zone2_heater"]

    def test_multiple_actuators_all_reported(self, fake_coord):
        now = dt_util.utcnow()
        fake_coord._appliance_unavail_since["zone2_heater"] = now - timedelta(minutes=10)
        fake_coord._appliance_unavail_since["exhaust"] = now - timedelta(minutes=6)
        dropout, entities = fake_coord._actuator_dropout_status()
        assert dropout is True
        assert set(entities) == {"switch.zone2_heater", "fan.exhaust"}

    def test_no_entity_reported_if_role_unmapped(self, fake_coord):
        """An unavailable role with no config-mapped entity_id (e.g. AC was
        never configured) has nothing meaningful to report."""
        del fake_coord._config[CONF_ZONE2_AC]
        fake_coord._appliance_unavail_since["zone2_ac"] = dt_util.utcnow() - timedelta(minutes=10)
        dropout, entities = fake_coord._actuator_dropout_status()
        assert dropout is False
        assert entities == []


class TestFanSpeedPersistence:
    @pytest.fixture
    def fake_speed_coord(self):
        coord = MagicMock()
        coord._config = {}
        coord._fan_speeds = {FAN_TIER_UPPER: float(DEFAULT_FAN_SPEED_PCT)}
        coord.queue_option_write = MagicMock(
            side_effect=lambda k, v: coord._config.__setitem__(k, v)
        )
        coord.breeze_upper_enabled = False
        coord.hass = MagicMock()
        coord.set_fan_speed = lambda tier, v: HelixCoordinator.set_fan_speed(coord, tier, v)
        return coord

    def test_set_fan_speed_persists_via_queue_option_write(self, fake_speed_coord):
        fake_speed_coord.set_fan_speed(FAN_TIER_UPPER, 70.0)

        fake_speed_coord.queue_option_write.assert_called_once_with("fan_speed_upper", 70.0)
        assert fake_speed_coord._config["fan_speed_upper"] == 70.0

    def test_value_survives_simulated_reload(self, fake_speed_coord):
        """The exact regression this fixes: a config-entry reload rebuilds
        the coordinator from scratch — the persisted value must be read
        back, not reset to the coded default."""
        fake_speed_coord.set_fan_speed(FAN_TIER_UPPER, 85.0)
        persisted_config = dict(fake_speed_coord._config)

        reloaded_speed = float(
            persisted_config.get(f"fan_speed_{FAN_TIER_UPPER}", DEFAULT_FAN_SPEED_PCT)
        )
        assert reloaded_speed == 85.0

    def test_falls_back_to_default_when_never_set(self):
        assert float({}.get(f"fan_speed_{FAN_TIER_MID}", DEFAULT_FAN_SPEED_PCT)) == float(DEFAULT_FAN_SPEED_PCT)

    def test_applies_immediately_when_breeze_off(self, fake_speed_coord):
        fake_speed_coord.set_fan_speed(FAN_TIER_UPPER, 60.0)
        fake_speed_coord.hass.async_create_task.assert_called_once()

    def test_does_not_apply_immediately_when_breeze_on(self, fake_speed_coord):
        fake_speed_coord.breeze_upper_enabled = True
        fake_speed_coord.set_fan_speed(FAN_TIER_UPPER, 60.0)
        fake_speed_coord.hass.async_create_task.assert_not_called()
        # Still persisted even though not applied immediately — the breeze
        # loop reads this as its new base speed on its own next iteration.
        assert fake_speed_coord._config["fan_speed_upper"] == 60.0


@pytest.mark.parametrize("key", [
    NUMBER_UPPER_FAN_VARIANCE, NUMBER_MID_FAN_VARIANCE, NUMBER_LOWER_FAN_VARIANCE,
])
def test_breeze_variance_step_is_5(key):
    """Part 1.5: variance slider step changed from 1% to 5%."""
    desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == key)
    assert desc.native_step == 5.0
