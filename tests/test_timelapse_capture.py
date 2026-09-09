"""Tests for HelixCoordinator._maybe_trigger_snapshot (B5 — daily time-lapse
still capture at a fixed configurable clock time, default solar noon).
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate.const import (
    CONF_GROW_CAMERA,
    CONF_TIMELAPSE_CAPTURE_TIME,
    DOMAIN,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator


class _FakeEntry:
    entry_id = "test_entry_id"


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {CONF_GROW_CAMERA: "camera.grow_tent"}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = _FakeEntry()
    coord._last_snapshot_date = None
    coord.hass = MagicMock()
    coord.hass.config.path = MagicMock(
        side_effect=lambda *parts: "/config/" + "/".join(parts)
    )
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.data = {DOMAIN: {}}
    return coord


async def _run(coord):
    await HelixCoordinator._maybe_trigger_snapshot(coord)


@pytest.mark.asyncio
async def test_no_camera_mapped_is_a_complete_noop(fake_coord):
    fake_coord._config = {}
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()
    assert fake_coord._last_snapshot_date is None


@pytest.mark.asyncio
async def test_already_captured_today_skips(fake_coord):
    fake_coord._last_snapshot_date = dt_util.now().date()
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_fixed_time_before_target_skips(fake_coord):
    # A fixed capture time far in the future today (23:59) should not have
    # triggered yet on a fresh run.
    fake_coord._config[CONF_TIMELAPSE_CAPTURE_TIME] = "23:59"
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()
    assert fake_coord._last_snapshot_date is None


@pytest.mark.asyncio
async def test_fixed_time_at_or_after_target_captures_once(fake_coord):
    now = dt_util.now()
    past_time = (now - timedelta(minutes=1)).strftime("%H:%M")
    if now.hour == 0 and now.minute <= 1:
        pytest.skip("flaky only at local midnight boundary")
    fake_coord._config[CONF_TIMELAPSE_CAPTURE_TIME] = past_time

    journal = MagicMock()
    journal.async_add_timelapse_image = AsyncMock()
    fake_coord.hass.data[DOMAIN]["journal_store"] = journal

    await _run(fake_coord)

    fake_coord.hass.services.async_call.assert_awaited_once()
    call_args = fake_coord.hass.services.async_call.call_args
    assert call_args[0][0] == "camera"
    assert call_args[0][1] == "snapshot"
    assert call_args[0][2]["entity_id"] == "camera.grow_tent"
    assert fake_coord._last_snapshot_date == date.today()
    journal.async_add_timelapse_image.assert_awaited_once()

    # A second call the same day (target time still in the past) must not
    # capture again — already done for today.
    fake_coord.hass.services.async_call.reset_mock()
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()
