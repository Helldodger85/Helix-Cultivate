"""Tests for Part 3.2 — canopy wind sweep: rotating a boosted speed among
currently-enabled circulation tiers during growing stages, and confirming
it is inactive during Drying regardless of its own toggle state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_WIND_SWEEP_ENABLED,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    STAGE_DRYING,
    STAGE_PEAK_FLOWER,
    WIND_SWEEP_BOOST_PCT,
    WIND_SWEEP_INTERVAL_MIN,
    WIND_SWEEP_REST_PCT,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_coord(monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: FIXED_NOW)

    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_PEAK_FLOWER
    coord._breeze_tasks = {}
    coord._is_fan_tier_enabled = MagicMock(return_value=True)
    coord._apply_fan_speed_to_tier = AsyncMock()
    coord._wind_sweep_phase_since = None
    coord._wind_sweep_current_tier = None

    coord._manage_wind_sweep = lambda: HelixCoordinator._manage_wind_sweep(coord)
    coord._stop_breeze_task = lambda tier: HelixCoordinator._stop_breeze_task(coord, tier)
    return coord


@pytest.mark.asyncio
async def test_disabled_by_default_does_nothing(fake_coord):
    await fake_coord._manage_wind_sweep()

    fake_coord._apply_fan_speed_to_tier.assert_not_called()
    assert fake_coord._wind_sweep_current_tier is None


@pytest.mark.asyncio
async def test_never_activates_during_drying_even_when_enabled(fake_coord):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    fake_coord.stage_manager.current_stage = STAGE_DRYING

    await fake_coord._manage_wind_sweep()

    fake_coord._apply_fan_speed_to_tier.assert_not_called()
    assert fake_coord._wind_sweep_current_tier is None


@pytest.mark.asyncio
async def test_boosts_first_enabled_tier_and_rests_others(fake_coord):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True

    await fake_coord._manage_wind_sweep()

    calls = {c.args[0]: c.args[1] for c in fake_coord._apply_fan_speed_to_tier.call_args_list}
    assert calls[FAN_TIER_UPPER] == WIND_SWEEP_BOOST_PCT
    assert calls[FAN_TIER_MID] == WIND_SWEEP_REST_PCT
    assert calls[FAN_TIER_LOWER] == WIND_SWEEP_REST_PCT
    assert fake_coord._wind_sweep_current_tier == FAN_TIER_UPPER


@pytest.mark.asyncio
async def test_skips_disabled_tiers_in_rotation(fake_coord):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    fake_coord._is_fan_tier_enabled = MagicMock(
        side_effect=lambda tier: tier in (FAN_TIER_UPPER, FAN_TIER_LOWER)
    )

    await fake_coord._manage_wind_sweep()

    called_tiers = {c.args[0] for c in fake_coord._apply_fan_speed_to_tier.call_args_list}
    assert called_tiers == {FAN_TIER_UPPER, FAN_TIER_LOWER}
    assert fake_coord._wind_sweep_current_tier in (FAN_TIER_UPPER, FAN_TIER_LOWER)


@pytest.mark.asyncio
async def test_rotates_to_next_tier_after_interval_elapses(fake_coord, monkeypatch):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True

    await fake_coord._manage_wind_sweep()
    assert fake_coord._wind_sweep_current_tier == FAN_TIER_UPPER

    # Still within the interval — stays on the same tier.
    mid_interval = FIXED_NOW + timedelta(minutes=WIND_SWEEP_INTERVAL_MIN - 1)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: mid_interval)
    await fake_coord._manage_wind_sweep()
    assert fake_coord._wind_sweep_current_tier == FAN_TIER_UPPER

    # Past the interval — rotates to the next enabled tier.
    past_interval = FIXED_NOW + timedelta(minutes=WIND_SWEEP_INTERVAL_MIN + 1)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: past_interval)
    await fake_coord._manage_wind_sweep()
    assert fake_coord._wind_sweep_current_tier == FAN_TIER_MID


@pytest.mark.asyncio
async def test_stops_breeze_task_for_swept_tiers(fake_coord):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    fake_task = MagicMock()
    fake_task.done.return_value = False
    fake_coord._breeze_tasks[FAN_TIER_UPPER] = fake_task

    await fake_coord._manage_wind_sweep()

    fake_task.cancel.assert_called_once()
    assert FAN_TIER_UPPER not in fake_coord._breeze_tasks


@pytest.mark.asyncio
async def test_disabling_mid_cycle_resets_rotation_state(fake_coord):
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    await fake_coord._manage_wind_sweep()
    assert fake_coord._wind_sweep_current_tier is not None

    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = False
    await fake_coord._manage_wind_sweep()
    assert fake_coord._wind_sweep_current_tier is None
    assert fake_coord._wind_sweep_phase_since is None
