"""Tests for Part 4.2's coexistence rule: "if Wind Sweep is actively
boosting a tier, that tier's own Breeze variance should be suspended for
the boost duration, then resume." Both mechanisms already existed
(_manage_breeze_tasks — extracted this session from an inline tick block
for testability — and _manage_wind_sweep, from a prior session), but there
was no test exercising them together across ticks to confirm the handoff
actually works both ways: wind sweep suspends breeze while active, and
breeze resumes automatically once wind sweep releases the tier.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_WIND_SWEEP_ENABLED,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    STAGE_PEAK_FLOWER,
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
    coord.breeze_upper_enabled = True
    coord.breeze_mid_enabled = False
    coord.breeze_lower_enabled = False

    # Real breeze-task start/stop, but stub the actual async loop body so
    # "started" just means "a live, not-yet-done task exists" without
    # actually sleeping/looping.
    async def _noop_loop(tier):
        try:
            import asyncio
            await asyncio.Event().wait()
        except Exception:
            raise

    coord._breeze_loop = _noop_loop
    real_hass = MagicMock()
    real_hass.async_create_task = lambda coro: __import__("asyncio").ensure_future(coro)
    coord.hass = real_hass

    coord._manage_breeze_tasks = lambda: HelixCoordinator._manage_breeze_tasks(coord)
    coord._manage_wind_sweep = lambda: HelixCoordinator._manage_wind_sweep(coord)
    coord._start_breeze_task = lambda tier: HelixCoordinator._start_breeze_task(coord, tier)
    coord._stop_breeze_task = lambda tier: HelixCoordinator._stop_breeze_task(coord, tier)
    return coord


@pytest.mark.asyncio
async def test_wind_sweep_suspends_the_tier_it_boosts(fake_coord):
    """Upper has Breeze enabled; once wind sweep activates and starts
    driving Upper (first in rotation), Upper's breeze task must be stopped."""
    fake_coord._manage_breeze_tasks()
    assert FAN_TIER_UPPER in fake_coord._breeze_tasks
    assert not fake_coord._breeze_tasks[FAN_TIER_UPPER].done()

    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    await fake_coord._manage_wind_sweep()

    assert FAN_TIER_UPPER not in fake_coord._breeze_tasks


@pytest.mark.asyncio
async def test_breeze_resumes_once_wind_sweep_is_disabled(fake_coord):
    """After wind sweep releases the tier (toggled off), the very next
    breeze-task-management pass must restart Upper's breeze loop —
    "suspended for the boost duration, then resume", not permanently lost."""
    fake_coord._manage_breeze_tasks()
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True
    await fake_coord._manage_wind_sweep()
    assert FAN_TIER_UPPER not in fake_coord._breeze_tasks

    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = False
    await fake_coord._manage_wind_sweep()
    fake_coord._manage_breeze_tasks()

    assert FAN_TIER_UPPER in fake_coord._breeze_tasks
    assert not fake_coord._breeze_tasks[FAN_TIER_UPPER].done()


@pytest.mark.asyncio
async def test_breeze_and_wind_sweep_do_not_fight_over_multiple_ticks(fake_coord):
    """Simulates several coordinator ticks with wind sweep continuously
    active — breeze must stay suspended the whole time rather than the two
    repeatedly restarting/cancelling each other's task."""
    fake_coord._config[CONF_WIND_SWEEP_ENABLED] = True

    for _ in range(5):
        fake_coord._manage_breeze_tasks()
        await fake_coord._manage_wind_sweep()

    assert FAN_TIER_UPPER not in fake_coord._breeze_tasks
    fake_coord._apply_fan_speed_to_tier.assert_awaited()


@pytest.mark.asyncio
async def test_disabled_tier_breeze_never_starts_even_without_wind_sweep(fake_coord):
    """Mid/Lower have Breeze off — confirms _manage_breeze_tasks only starts
    tasks for tiers actually enabled, independent of wind sweep entirely."""
    fake_coord._manage_breeze_tasks()

    assert FAN_TIER_MID not in fake_coord._breeze_tasks
    assert FAN_TIER_LOWER not in fake_coord._breeze_tasks
