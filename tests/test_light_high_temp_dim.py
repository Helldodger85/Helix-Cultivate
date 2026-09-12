"""Tests for Part 3.1 — high-temperature graduated light dimming: a soft
50% throttle at CONF_LIGHT_HIGH_TEMP_DIM_C (default 29°C), strictly below
the existing hard 32°C thermal-runaway cutoff (which forces 0%), verifying
both coexist correctly rather than conflicting.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_LIGHT_HIGH_TEMP_DIM_C,
    CONF_ZONE2_GROW_LIGHT,
    LIGHT_HIGH_TEMP_DIM_PCT,
)


@pytest.mark.asyncio
async def test_dims_to_50pct_at_soft_threshold(engine, mock_coord):
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()

    await engine._handle_light_high_temp_dim(29.0)

    mock_coord._apply_grow_light_schedule.assert_awaited_once_with(
        "light.grow", LIGHT_HIGH_TEMP_DIM_PCT
    )


@pytest.mark.asyncio
async def test_no_dim_below_soft_threshold(engine, mock_coord):
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()

    await engine._handle_light_high_temp_dim(28.9)

    mock_coord._apply_grow_light_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_custom_threshold_respected(engine, mock_coord):
    mock_coord._config[CONF_LIGHT_HIGH_TEMP_DIM_C] = 27.0
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()

    await engine._handle_light_high_temp_dim(27.5)

    mock_coord._apply_grow_light_schedule.assert_awaited_once_with(
        "light.grow", LIGHT_HIGH_TEMP_DIM_PCT
    )


@pytest.mark.asyncio
async def test_no_redundant_call_when_already_at_or_below_dim_pct(engine, mock_coord):
    """If the schedule already applied <=50% this tick (e.g. near the end
    of a sunset ramp), there's nothing to throttle further."""
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._light_applied_pct = 30.0
    mock_coord._apply_grow_light_schedule = AsyncMock()

    await engine._handle_light_high_temp_dim(29.0)

    mock_coord._apply_grow_light_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_dim_when_no_grow_light_mapped(engine, mock_coord):
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()

    await engine._handle_light_high_temp_dim(30.0)

    mock_coord._apply_grow_light_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_hard_cutoff_supersedes_soft_dim_in_run(engine, mock_coord):
    """The 32°C hard cutoff (_handle_thermal_runaway, forces 0%) must win
    outright over the 29°C soft dim (50%) — run() must never call the soft
    dim once the hard cutoff has already fired this tick."""
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._config["thermal_runaway_c"] = 32.0
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()
    mock_coord.hass.states.get.return_value = None  # entity lookups no-op safely

    thermal_runaway = await engine._handle_thermal_runaway(33.0)
    assert thermal_runaway is True

    # Mirrors run()'s own guard: soft dim only ever called when NOT already
    # in thermal runaway.
    if not thermal_runaway:
        await engine._handle_light_high_temp_dim(33.0)

    # The 0%-forcing hard-cutoff call happened (via _set_light_intensity ->
    # the retry wrapper -> hass.services.async_call), but the soft-dim path
    # into _apply_grow_light_schedule must never have been invoked.
    mock_coord._apply_grow_light_schedule.assert_not_awaited()
    assert mock_coord.light_intensity_pct == 0.0


@pytest.mark.asyncio
async def test_soft_dim_engages_once_hard_cutoff_clears(engine, mock_coord):
    """Once temperature drops back below 32°C but is still >= 29°C, the
    soft dim should engage on its own (run()'s guard re-evaluates fresh
    every tick)."""
    mock_coord._config[CONF_ZONE2_GROW_LIGHT] = "light.grow"
    mock_coord._config["thermal_runaway_c"] = 32.0
    mock_coord._light_applied_pct = 100.0
    mock_coord._apply_grow_light_schedule = AsyncMock()
    mock_coord.hass.states.get.return_value = None

    thermal_runaway = await engine._handle_thermal_runaway(30.0)
    assert thermal_runaway is False

    if not thermal_runaway:
        await engine._handle_light_high_temp_dim(30.0)

    mock_coord._apply_grow_light_schedule.assert_awaited_once_with(
        "light.grow", LIGHT_HIGH_TEMP_DIM_PCT
    )
