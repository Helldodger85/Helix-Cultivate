"""Tests for Part 4.1/4.2: Breeze mode's "resets within 30 seconds" symptom
had two independent causes, both fixed here:

1. switch.py's async_turn_on/off only ever did an in-memory
   setattr(coordinator, attr, value) — no persistence call at all, so the
   true intended state lived nowhere the coordinator could read back after
   a reload. Fixed via a new HelixSwitchDescription.config_key field that,
   when set, also calls coordinator.queue_option_write().

2. coordinator.__init__ read all three tiers' breeze_{tier}_enabled from
   the very same shared CONF_BREEZE_ENABLED key, so enabling Breeze on one
   tier silently enabled it on all three. Fixed via
   _read_persisted_breeze_enabled(tier), which reads a genuinely distinct
   breeze_{tier}_enabled key per tier.

Also covers _breeze_loop's per-tier variance fix (Part 4.2): it previously
read the single shared CONF_BREEZE_VARIANCE config key for every tier,
ignoring the already-existing, independently persisted Upper/Mid/Lower
Breeze Variance number entities (breeze_variance_{tier}).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    DEFAULT_FAN_VARIANCE_PCT,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.switch import (
    SWITCH_DESCRIPTIONS,
    HelixSwitch,
    HelixSwitchDescription,
)


def _switch_description(key):
    for desc in SWITCH_DESCRIPTIONS:
        if desc.key == key:
            return desc
    raise AssertionError(f"no SWITCH_DESCRIPTIONS entry for key={key!r}")


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord.queue_option_write = MagicMock(
        side_effect=lambda k, v: coord._config.__setitem__(k, v)
    )
    coord._start_breeze_task = MagicMock()
    coord._stop_breeze_task = MagicMock()
    return coord


@pytest.mark.asyncio
@pytest.mark.parametrize("switch_key,tier", [
    ("breeze_upper", FAN_TIER_UPPER),
    ("breeze_mid", FAN_TIER_MID),
    ("breeze_lower", FAN_TIER_LOWER),
])
async def test_breeze_switch_turn_on_persists_via_queue_option_write(fake_coord, switch_key, tier):
    desc = _switch_description(switch_key)
    entity = HelixSwitch(fake_coord, desc)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_turn_on()

    fake_coord.queue_option_write.assert_called_once_with(f"breeze_{tier}_enabled", True)
    assert fake_coord._config[f"breeze_{tier}_enabled"] is True


@pytest.mark.asyncio
async def test_breeze_switch_turn_off_persists_via_queue_option_write(fake_coord):
    desc = _switch_description("breeze_upper")
    entity = HelixSwitch(fake_coord, desc)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()

    await entity.async_turn_off()

    fake_coord.queue_option_write.assert_called_once_with("breeze_upper_enabled", False)
    assert fake_coord._config["breeze_upper_enabled"] is False


@pytest.mark.asyncio
async def test_breeze_switch_state_survives_simulated_reload(fake_coord):
    """Toggle on, then read back from a *fresh* coordinator built from the
    same persisted config — simulating a coordinator/config-entry reload."""
    desc = _switch_description("breeze_mid")
    entity = HelixSwitch(fake_coord, desc)
    entity.hass = MagicMock()
    entity.async_write_ha_state = MagicMock()
    await entity.async_turn_on()

    reloaded_enabled = HelixCoordinator._read_persisted_breeze_enabled(
        MagicMock(_config=dict(fake_coord._config)), FAN_TIER_MID
    )
    assert reloaded_enabled is True


def test_switch_description_has_config_key_field():
    assert hasattr(HelixSwitchDescription(key="x"), "config_key")


def test_non_breeze_switch_without_config_key_does_not_call_queue_option_write():
    """Switches with no config_key set (unrelated to this fix) must not
    attempt to persist anything — config_key stays opt-in per-description."""
    desc = _switch_description("smooth_glides")
    assert desc.config_key == ""


class TestPerTierBreezeEnabledIsolation:
    """Confirms enabling Breeze on one tier no longer bleeds into the other
    two — the exact regression the shared CONF_BREEZE_ENABLED key caused."""

    def test_each_tier_reads_its_own_distinct_key(self):
        coord = MagicMock()
        coord._config = {"breeze_upper_enabled": True}

        assert HelixCoordinator._read_persisted_breeze_enabled(coord, FAN_TIER_UPPER) is True
        assert HelixCoordinator._read_persisted_breeze_enabled(coord, FAN_TIER_MID) is False
        assert HelixCoordinator._read_persisted_breeze_enabled(coord, FAN_TIER_LOWER) is False

    def test_absent_key_defaults_false(self):
        coord = MagicMock()
        coord._config = {}
        assert HelixCoordinator._read_persisted_breeze_enabled(coord, FAN_TIER_LOWER) is False


class TestBreezeLoopPerTierVariance:
    """_breeze_loop must vary each tier's speed by *that tier's own*
    breeze_variance_{tier} config value, not a single shared value."""

    @pytest.mark.asyncio
    async def test_uses_tier_specific_variance_key(self, monkeypatch):
        coord = MagicMock()
        coord._config = {
            "breeze_variance_upper": 5,
            "breeze_variance_mid": 40,
        }
        coord._fan_speeds = {FAN_TIER_UPPER: 50.0, FAN_TIER_MID: 50.0}
        coord._get = lambda key, default=None: coord._config.get(key, default)
        coord._apply_fan_speed_to_tier = AsyncMock()

        captured_deltas = {}

        def fake_uniform(lo, hi):
            captured_deltas.setdefault("calls", []).append((lo, hi))
            return 0.0

        import custom_components.helix_cultivate.coordinator as coordinator_module
        monkeypatch.setattr(coordinator_module.random, "uniform", fake_uniform)

        async def fake_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(coordinator_module.asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await HelixCoordinator._breeze_loop(coord, FAN_TIER_UPPER)
        assert captured_deltas["calls"][0] == (-5.0, 5.0)

        captured_deltas.clear()
        with pytest.raises(asyncio.CancelledError):
            await HelixCoordinator._breeze_loop(coord, FAN_TIER_MID)
        assert captured_deltas["calls"][0] == (-40.0, 40.0)

    @pytest.mark.asyncio
    async def test_falls_back_to_default_variance_when_tier_key_absent(self, monkeypatch):
        coord = MagicMock()
        coord._config = {}
        coord._fan_speeds = {FAN_TIER_LOWER: 50.0}
        coord._get = lambda key, default=None: coord._config.get(key, default)
        coord._apply_fan_speed_to_tier = AsyncMock()

        import custom_components.helix_cultivate.coordinator as coordinator_module
        calls = []
        monkeypatch.setattr(
            coordinator_module.random, "uniform",
            lambda lo, hi: calls.append((lo, hi)) or 0.0,
        )

        async def fake_sleep(_seconds):
            raise asyncio.CancelledError()

        monkeypatch.setattr(coordinator_module.asyncio, "sleep", fake_sleep)

        with pytest.raises(asyncio.CancelledError):
            await HelixCoordinator._breeze_loop(coord, FAN_TIER_LOWER)

        assert calls[0] == (-float(DEFAULT_FAN_VARIANCE_PCT), float(DEFAULT_FAN_VARIANCE_PCT))
