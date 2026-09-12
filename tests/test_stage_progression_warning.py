"""Tests for Part 3.5 — stage-progression heads-up warnings: an
informational (not safety-critical) reminder firing at a configurable lead
time before the active stage's expected duration elapses, with correct
per-transition messaging, and explicitly NOT performing anything
automatically.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_STAGE_WARNING_LEAD_DAYS,
    STAGE_DRYING,
    STAGE_LATE_VEG,
    STAGE_PEAK_FLOWER,
    STAGE_RIPENING,
    STAGE_SEQUENCE,
    STAGE_STRETCH,
    STAGE_TRANSITION_TIPS,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord.hass = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord._notify_critical = AsyncMock()
    coord._stage_warning_alerted = {}

    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_LATE_VEG
    coord.stage_manager._duration = MagicMock(return_value=14)
    coord.stage_manager._elapsed_days = MagicMock(return_value=0)

    coord._check_stage_progression_warning = lambda: HelixCoordinator._check_stage_progression_warning(coord)
    return coord


@pytest.mark.asyncio
async def test_no_warning_outside_lead_window(fake_coord):
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 0  # 14 days remaining

    await fake_coord._check_stage_progression_warning()

    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_awaited()


@pytest.mark.asyncio
async def test_warning_fires_at_default_3_day_lead(fake_coord):
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 11  # 3 days remaining

    await fake_coord._check_stage_progression_warning()

    fake_coord.hass.bus.async_fire.assert_called_once()
    event_name, payload = fake_coord.hass.bus.async_fire.call_args.args
    assert event_name == "helix_cultivate_stage_progression_warning"
    assert payload["current_stage"] == STAGE_LATE_VEG
    assert payload["next_stage"] == STAGE_STRETCH
    assert payload["days_remaining"] == 3
    fake_coord._notify_critical.assert_awaited_once()
    assert fake_coord._notify_critical.call_args.kwargs["level"] == "info"


@pytest.mark.asyncio
async def test_correct_tip_included_for_late_veg_to_stretch(fake_coord):
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 12  # 2 days remaining

    await fake_coord._check_stage_progression_warning()

    message = fake_coord._notify_critical.call_args.kwargs["message"]
    assert STAGE_TRANSITION_TIPS[STAGE_STRETCH] in message
    assert "does not perform this automatically" in message


@pytest.mark.asyncio
async def test_correct_tip_for_different_transition(fake_coord):
    fake_coord.stage_manager.current_stage = STAGE_PEAK_FLOWER
    fake_coord.stage_manager._duration.return_value = 56
    fake_coord.stage_manager._elapsed_days.return_value = 54  # 2 days remaining

    await fake_coord._check_stage_progression_warning()

    event_name, payload = fake_coord.hass.bus.async_fire.call_args.args
    assert payload["next_stage"] == STAGE_RIPENING
    message = fake_coord._notify_critical.call_args.kwargs["message"]
    assert STAGE_TRANSITION_TIPS[STAGE_RIPENING] in message


@pytest.mark.asyncio
async def test_custom_lead_time_respected(fake_coord):
    fake_coord._config[CONF_STAGE_WARNING_LEAD_DAYS] = 5
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 9  # 5 days remaining

    await fake_coord._check_stage_progression_warning()

    fake_coord.hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_fires_only_once_per_approaching_transition(fake_coord):
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 11  # 3 days remaining

    await fake_coord._check_stage_progression_warning()
    await fake_coord._check_stage_progression_warning()
    await fake_coord._check_stage_progression_warning()

    fake_coord._notify_critical.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_warning_for_drying_the_last_stage(fake_coord):
    fake_coord.stage_manager.current_stage = STAGE_DRYING

    await fake_coord._check_stage_progression_warning()

    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_awaited()


@pytest.mark.asyncio
async def test_resets_and_can_refire_if_countdown_leaves_then_reenters_window(fake_coord):
    """E.g. a manual stage-duration edit pushes days_remaining back out."""
    fake_coord.stage_manager._duration.return_value = 14
    fake_coord.stage_manager._elapsed_days.return_value = 11  # 3 days remaining
    await fake_coord._check_stage_progression_warning()
    fake_coord._notify_critical.assert_awaited_once()

    # Duration extended — back outside the lead window.
    fake_coord.stage_manager._duration.return_value = 20
    await fake_coord._check_stage_progression_warning()
    assert fake_coord._notify_critical.await_count == 1

    # Re-enters the window later — must fire again.
    fake_coord.stage_manager._elapsed_days.return_value = 17  # 3 days remaining again
    await fake_coord._check_stage_progression_warning()
    assert fake_coord._notify_critical.await_count == 2
