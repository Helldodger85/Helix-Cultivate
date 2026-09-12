"""Tests for Part 3: multi-fan-per-tier entity mapping.

_get_tier_fans() and _apply_fan_speed_to_tier() already existed and already
handled a *list* of fan entities per tier (CONF_UPPER_FANS/MID_FANS/
LOWER_FANS, written by the native Options Flow's Fan Matrix step) — the
ticket's premise that this needed building "from scratch" was only true for
the custom dashboard panel's own gear-icon hardware form, which had no way
to write these keys at all (they were missing from
ALL_VALID_ZONE_DEVICE_KEYS, the ws_update_zone_devices whitelist). This
file covers: the whitelist addition, _get_tier_fans' filtering of unset
slots, and _apply_fan_speed_to_tier driving every entity in a tier's list
simultaneously (not just the first).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    ALL_VALID_ZONE_DEVICE_KEYS,
    CONF_LOWER_FANS,
    CONF_MID_FANS,
    CONF_UPPER_FANS,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.number import NUMBER_DESCRIPTIONS
from custom_components.helix_cultivate.const import (
    NUMBER_LOWER_FAN_SPEED,
    NUMBER_MID_FAN_SPEED,
    NUMBER_UPPER_FAN_SPEED,
)


@pytest.mark.parametrize("key", [
    NUMBER_UPPER_FAN_SPEED, NUMBER_MID_FAN_SPEED, NUMBER_LOWER_FAN_SPEED,
])
def test_fan_speed_step_is_10_matching_hardware_resolution(key):
    """Part 3.4: fans are driven via Template Fan wrappers with 0-10
    discrete power levels (10% increments) — a step of 1 let the number
    entity claim precision the hardware can't actually apply."""
    desc = next(d for d in NUMBER_DESCRIPTIONS if d.key == key)
    assert desc.native_step == 10.0


@pytest.mark.parametrize("conf_key", [CONF_UPPER_FANS, CONF_MID_FANS, CONF_LOWER_FANS])
def test_canopy_fan_keys_are_whitelisted_for_gear_icon_form(conf_key):
    """Without this, the gear-icon hardware form's update_zone_devices call
    would silently drop the canopy fan list — the exact "no config surface"
    gap the ticket describes."""
    assert conf_key in ALL_VALID_ZONE_DEVICE_KEYS


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._is_fan_tier_enabled = MagicMock(return_value=True)
    coord.hass = MagicMock()
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.states = MagicMock()
    coord.hass.states.get = MagicMock(return_value=MagicMock())
    coord._get_tier_fans = lambda tier: HelixCoordinator._get_tier_fans(coord, tier)
    return coord


class TestGetTierFans:
    def test_filters_out_none_slots(self, fake_coord):
        fake_coord._config[CONF_UPPER_FANS] = ["fan.a", None, "fan.b", None]
        assert HelixCoordinator._get_tier_fans(fake_coord, FAN_TIER_UPPER) == ["fan.a", "fan.b"]

    def test_empty_when_unconfigured(self, fake_coord):
        assert HelixCoordinator._get_tier_fans(fake_coord, FAN_TIER_MID) == []

    def test_each_tier_reads_its_own_key(self, fake_coord):
        fake_coord._config[CONF_UPPER_FANS] = ["fan.up"]
        fake_coord._config[CONF_MID_FANS] = ["fan.mid"]
        fake_coord._config[CONF_LOWER_FANS] = ["fan.low"]
        assert HelixCoordinator._get_tier_fans(fake_coord, FAN_TIER_UPPER) == ["fan.up"]
        assert HelixCoordinator._get_tier_fans(fake_coord, FAN_TIER_MID) == ["fan.mid"]
        assert HelixCoordinator._get_tier_fans(fake_coord, FAN_TIER_LOWER) == ["fan.low"]


class TestApplyFanSpeedDrivesEveryFanInTier:
    @pytest.mark.asyncio
    async def test_commands_every_configured_fan_simultaneously(self, fake_coord):
        fake_coord._config[CONF_UPPER_FANS] = ["fan.upper_1", "fan.upper_2", "fan.upper_3"]

        await HelixCoordinator._apply_fan_speed_to_tier(fake_coord, FAN_TIER_UPPER, 60.0)

        called_entities = {
            c.args[2]["entity_id"]
            for c in fake_coord.hass.services.async_call.call_args_list
        }
        assert called_entities == {"fan.upper_1", "fan.upper_2", "fan.upper_3"}
        assert fake_coord.hass.services.async_call.await_count == 3

    @pytest.mark.asyncio
    async def test_single_fan_tier_still_works(self, fake_coord):
        fake_coord._config[CONF_MID_FANS] = ["fan.mid_only"]

        await HelixCoordinator._apply_fan_speed_to_tier(fake_coord, FAN_TIER_MID, 40.0)

        fake_coord.hass.services.async_call.assert_awaited_once()
        call = fake_coord.hass.services.async_call.call_args
        assert call.args[2]["entity_id"] == "fan.mid_only"

    @pytest.mark.asyncio
    async def test_zero_fans_makes_no_service_calls(self, fake_coord):
        fake_coord._config[CONF_LOWER_FANS] = []

        await HelixCoordinator._apply_fan_speed_to_tier(fake_coord, FAN_TIER_LOWER, 50.0)

        fake_coord.hass.services.async_call.assert_not_called()
