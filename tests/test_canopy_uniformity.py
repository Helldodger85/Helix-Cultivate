"""Tests for HelixCoordinator._check_canopy_uniformity (canopy uniformity
diagnostic — keyed off sensor-layer toggles, independent of fan toggles).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate.const import CANOPY_UNIFORMITY_DWELL_MIN
from custom_components.helix_cultivate.coordinator import HelixCoordinator


class _FakeEntry:
    entry_id = "test_entry_id"


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord.hass = MagicMock()
    coord.hass.bus = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord._entry = _FakeEntry()
    coord._notify_critical = AsyncMock()
    coord._canopy_temp_spread = None
    coord._canopy_rh_spread = None
    coord._canopy_uniformity_insight = None
    coord._uniformity_drift_since = None
    coord._uniformity_alert_fired = False
    # Both sensor tiers enabled by default for these tests.
    coord._is_sensor_tier_enabled = MagicMock(return_value=True)
    return coord


async def _check(coord, upper_temp, upper_rh, mid_temp, mid_rh, lower_temp, lower_rh):
    await HelixCoordinator._check_canopy_uniformity(
        coord, upper_temp, upper_rh, mid_temp, mid_rh, lower_temp, lower_rh
    )


@pytest.mark.asyncio
async def test_skips_entirely_with_only_upper_layer(fake_coord):
    fake_coord._is_sensor_tier_enabled = MagicMock(return_value=False)
    await _check(fake_coord, 24.0, 60.0, None, None, None, None)
    assert fake_coord._canopy_temp_spread is None
    fake_coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_uniform_canopy_no_insight(fake_coord):
    await _check(fake_coord, 24.0, 60.0, 24.2, 61.0, 23.9, 59.5)
    assert fake_coord._canopy_uniformity_insight is None
    fake_coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_gradient_present_updates_live_spread_immediately(fake_coord):
    # 5C spread, well over the 2C threshold — insight should populate on the
    # very first tick even though the dwell timer hasn't elapsed yet.
    await _check(fake_coord, 28.0, 60.0, 25.0, 60.0, 23.0, 60.0)
    assert fake_coord._canopy_temp_spread == 5.0
    assert "temperature gradient" in fake_coord._canopy_uniformity_insight
    fake_coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_fires_once_after_dwell_threshold(fake_coord):
    now = dt_util.utcnow()
    fake_coord._uniformity_drift_since = now - timedelta(
        minutes=CANOPY_UNIFORMITY_DWELL_MIN + 1
    )
    await _check(fake_coord, 28.0, 70.0, 25.0, 60.0, 23.0, 55.0)
    fake_coord.hass.bus.async_fire.assert_called_once()
    event_name, payload = fake_coord.hass.bus.async_fire.call_args[0]
    assert event_name == "helix_cultivate_canopy_uniformity_alert"
    assert payload["entry_id"] == "test_entry_id"
    assert "humidity gradient" in payload["insight"]
    assert "temperature gradient" in payload["insight"]
    fake_coord._notify_critical.assert_awaited_once()

    # Same sustained excursion on the next tick must not fire again.
    fake_coord.hass.bus.async_fire.reset_mock()
    await _check(fake_coord, 28.0, 70.0, 25.0, 60.0, 23.0, 55.0)
    fake_coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_returning_uniform_resets_for_next_episode(fake_coord):
    now = dt_util.utcnow()
    fake_coord._uniformity_drift_since = now - timedelta(
        minutes=CANOPY_UNIFORMITY_DWELL_MIN + 1
    )
    fake_coord._uniformity_alert_fired = True

    await _check(fake_coord, 24.0, 60.0, 24.0, 60.0, 24.0, 60.0)
    assert fake_coord._uniformity_drift_since is None
    assert fake_coord._uniformity_alert_fired is False
    assert fake_coord._canopy_uniformity_insight is None
