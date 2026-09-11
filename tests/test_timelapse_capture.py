"""Tests for HelixCoordinator._maybe_trigger_snapshot (B5 — daily time-lapse
still capture at a fixed configurable clock time, default solar noon).

Freezes dt_util.now()/utcnow() to a fixed instant for the duration of each
test rather than relying on real wall-clock proximity between statements —
the wall clock actually moving between two nearby dt_util.now() calls (e.g.
right at a day boundary) previously made this suite flaky.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_GROW_CAMERA,
    CONF_TIMELAPSE_CAPTURE_TIME,
    DOMAIN,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

FIXED_NOW = datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc)


class _FakeEntry:
    entry_id = "test_entry_id"


@pytest.fixture
def fake_coord(monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: FIXED_NOW)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr(coordinator_module.dt_util, "as_utc", lambda dt: dt)

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
    fake_coord._last_snapshot_date = FIXED_NOW.date()
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_fixed_time_before_target_skips(fake_coord):
    # FIXED_NOW is 14:30 — a fixed capture time later today must not have
    # triggered yet.
    fake_coord._config[CONF_TIMELAPSE_CAPTURE_TIME] = "23:59"
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()
    assert fake_coord._last_snapshot_date is None


@pytest.mark.asyncio
async def test_fixed_time_at_or_after_target_captures_once(fake_coord):
    # FIXED_NOW is 14:30 — a fixed capture time earlier today must fire.
    fake_coord._config[CONF_TIMELAPSE_CAPTURE_TIME] = "14:00"

    journal = MagicMock()
    journal.async_add_timelapse_image = AsyncMock()
    fake_coord.hass.data[DOMAIN]["journal_store"] = journal

    await _run(fake_coord)

    fake_coord.hass.services.async_call.assert_awaited_once()
    call_args = fake_coord.hass.services.async_call.call_args
    assert call_args[0][0] == "camera"
    assert call_args[0][1] == "snapshot"
    assert call_args[0][2]["entity_id"] == "camera.grow_tent"
    assert fake_coord._last_snapshot_date == FIXED_NOW.date()
    journal.async_add_timelapse_image.assert_awaited_once()

    # A second call the same day (target time still in the past) must not
    # capture again — already done for today.
    fake_coord.hass.services.async_call.reset_mock()
    await _run(fake_coord)
    fake_coord.hass.services.async_call.assert_not_called()
