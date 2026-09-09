"""Tests for HelixCoordinator._check_chronic_vpd_drift (chronic VPD drift
alert — distinct from instant threshold breaches, see coordinator.py).

Exercises the unbound method against a minimal stand-in object exposing only
the attributes/methods it touches, rather than constructing a full
HelixCoordinator (which requires a running Home Assistant core).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate.const import CHRONIC_VPD_DRIFT_DWELL_MIN
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
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2
    coord._vpd_drift_since = None
    coord._chronic_drift_alert_fired = False
    coord._notify_critical = AsyncMock()
    return coord


async def _check(coord, leaf_vpd):
    await HelixCoordinator._check_chronic_vpd_drift(coord, leaf_vpd)


@pytest.mark.asyncio
async def test_no_alert_when_in_range(fake_coord):
    await _check(fake_coord, 1.0)
    assert fake_coord._vpd_drift_since is None
    fake_coord.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_starts_dwell_timer_on_first_excursion(fake_coord):
    await _check(fake_coord, 1.5)  # > vpd_target_max
    assert fake_coord._vpd_drift_since is not None
    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_called()


@pytest.mark.asyncio
async def test_no_alert_before_dwell_threshold(fake_coord):
    now = dt_util.utcnow()
    fake_coord._vpd_drift_since = now - timedelta(
        minutes=CHRONIC_VPD_DRIFT_DWELL_MIN - 5
    )
    await _check(fake_coord, 1.5)
    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_called()


@pytest.mark.asyncio
async def test_fires_once_after_dwell_threshold_exceeded(fake_coord):
    now = dt_util.utcnow()
    fake_coord._vpd_drift_since = now - timedelta(
        minutes=CHRONIC_VPD_DRIFT_DWELL_MIN + 5
    )
    await _check(fake_coord, 1.5)
    fake_coord.hass.bus.async_fire.assert_called_once()
    event_name, payload = fake_coord.hass.bus.async_fire.call_args[0]
    assert event_name == "helix_cultivate_chronic_drift_detected"
    assert payload["entry_id"] == "test_entry_id"
    assert payload["leaf_vpd_kpa"] == 1.5
    fake_coord._notify_critical.assert_awaited_once()
    assert fake_coord._chronic_drift_alert_fired is True

    # A subsequent tick, still out of range, must NOT fire again for the
    # same continuous episode.
    fake_coord.hass.bus.async_fire.reset_mock()
    fake_coord._notify_critical.reset_mock()
    await _check(fake_coord, 1.55)
    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_called()


@pytest.mark.asyncio
async def test_returning_in_range_resets_episode_for_next_excursion(fake_coord):
    now = dt_util.utcnow()
    fake_coord._vpd_drift_since = now - timedelta(
        minutes=CHRONIC_VPD_DRIFT_DWELL_MIN + 5
    )
    fake_coord._chronic_drift_alert_fired = True

    # VPD returns to normal — episode ends, state clears.
    await _check(fake_coord, 1.0)
    assert fake_coord._vpd_drift_since is None
    assert fake_coord._chronic_drift_alert_fired is False

    # A fresh excursion that again exceeds the dwell threshold must be able
    # to fire again — it's a new episode, not a duplicate of the first.
    fake_coord._vpd_drift_since = dt_util.utcnow() - timedelta(
        minutes=CHRONIC_VPD_DRIFT_DWELL_MIN + 1
    )
    await _check(fake_coord, 0.3)  # < vpd_target_min
    fake_coord.hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_none_leaf_vpd_does_not_reset_or_advance(fake_coord):
    now = dt_util.utcnow()
    started = now - timedelta(minutes=10)
    fake_coord._vpd_drift_since = started
    await _check(fake_coord, None)
    assert fake_coord._vpd_drift_since == started
    fake_coord.hass.bus.async_fire.assert_not_called()
