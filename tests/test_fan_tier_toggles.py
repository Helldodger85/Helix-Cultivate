"""Tests for the independent mid/lower canopy fan-tier toggle (B3):
_is_fan_tier_enabled/_is_sensor_tier_enabled and the _apply_fan_speed_to_tier
choke point that must never send a command to a disabled fan tier.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_LOWER_CANOPY_FAN_ENABLED,
    CONF_LOWER_CANOPY_SENSOR_ENABLED,
    CONF_MID_CANOPY_FAN_ENABLED,
    CONF_MID_CANOPY_SENSOR_ENABLED,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    # MagicMock auto-generates a mock (always truthy) for any attribute
    # access, including these — bind the real unbound methods so the gate
    # under test runs actual logic, not a MagicMock stand-in.
    coord._is_fan_tier_enabled = lambda tier: HelixCoordinator._is_fan_tier_enabled(coord, tier)
    coord._is_sensor_tier_enabled = lambda tier: HelixCoordinator._is_sensor_tier_enabled(coord, tier)
    coord.hass = MagicMock()
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.states = MagicMock()
    return coord


def test_upper_tier_always_enabled(fake_coord):
    assert HelixCoordinator._is_fan_tier_enabled(fake_coord, FAN_TIER_UPPER) is True
    assert HelixCoordinator._is_sensor_tier_enabled(fake_coord, FAN_TIER_UPPER) is True


def test_mid_lower_default_enabled_for_existing_installs(fake_coord):
    """No key present in config at all (pre-upgrade entry) must default True."""
    assert HelixCoordinator._is_fan_tier_enabled(fake_coord, FAN_TIER_MID) is True
    assert HelixCoordinator._is_fan_tier_enabled(fake_coord, FAN_TIER_LOWER) is True
    assert HelixCoordinator._is_sensor_tier_enabled(fake_coord, FAN_TIER_MID) is True
    assert HelixCoordinator._is_sensor_tier_enabled(fake_coord, FAN_TIER_LOWER) is True


def test_fan_and_sensor_toggles_are_independent(fake_coord):
    """A tier can have its sensor on and fan off simultaneously, or vice versa."""
    fake_coord._config[CONF_MID_CANOPY_SENSOR_ENABLED] = True
    fake_coord._config[CONF_MID_CANOPY_FAN_ENABLED] = False
    assert HelixCoordinator._is_sensor_tier_enabled(fake_coord, FAN_TIER_MID) is True
    assert HelixCoordinator._is_fan_tier_enabled(fake_coord, FAN_TIER_MID) is False

    fake_coord._config[CONF_LOWER_CANOPY_SENSOR_ENABLED] = False
    fake_coord._config[CONF_LOWER_CANOPY_FAN_ENABLED] = True
    assert HelixCoordinator._is_sensor_tier_enabled(fake_coord, FAN_TIER_LOWER) is False
    assert HelixCoordinator._is_fan_tier_enabled(fake_coord, FAN_TIER_LOWER) is True


@pytest.mark.asyncio
async def test_apply_fan_speed_skips_disabled_tier_without_querying_entities(fake_coord):
    """A disabled fan tier must never reach the hardware dispatch — not even
    a lookup of its configured fan entity IDs, let alone a service call."""
    fake_coord._config[CONF_MID_CANOPY_FAN_ENABLED] = False
    fake_coord._get_tier_fans = MagicMock(return_value=["fan.mid_1"])

    await HelixCoordinator._apply_fan_speed_to_tier(fake_coord, FAN_TIER_MID, 75.0)

    fake_coord._get_tier_fans.assert_not_called()
    fake_coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_apply_fan_speed_proceeds_for_enabled_tier(fake_coord):
    fake_coord._config[CONF_MID_CANOPY_FAN_ENABLED] = True
    fake_coord._get_tier_fans = MagicMock(return_value=["fan.mid_1"])
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock())

    await HelixCoordinator._apply_fan_speed_to_tier(fake_coord, FAN_TIER_MID, 75.0)

    fake_coord._get_tier_fans.assert_called_once_with(FAN_TIER_MID)
    fake_coord.hass.services.async_call.assert_awaited_once()
