"""Tests for Part 1's cycle lifecycle actions:
- StageManager.start_new_cycle()/return_to_not_started() (the state-machine
  primitives).
- HelixCoordinator.start_cycle()/abort_cycle() (the WS-facing actions that
  validate input, delegate to the state machine, and persist everything to
  the config entry in one write).
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_CYCLE_STATE,
    CONF_GROWTH_MODE,
    CONF_STAGE_START_DATE,
    CYCLE_STATE_ACTIVE,
    CYCLE_STATE_NOT_STARTED,
    GROWTH_MODE_AUTOFLOWER,
    GROWTH_MODE_PHOTOPERIOD,
    STAGE_EARLY_VEG,
    STAGE_GERMINATION,
    STAGE_SEQUENCE,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.stage_manager import StageManager


# ── StageManager primitives ─────────────────────────────────────────────────

def test_start_new_cycle_sets_stage_date_and_active_state():
    sm = StageManager(MagicMock(), {})
    assert sm.cycle_state == CYCLE_STATE_NOT_STARTED

    backdated = date(2026, 1, 1)
    sm.start_new_cycle(STAGE_EARLY_VEG, backdated)

    assert sm.current_stage == STAGE_EARLY_VEG
    assert sm.cycle_state == CYCLE_STATE_ACTIVE
    assert sm.is_cycle_active is True
    assert sm.elapsed_days >= 0  # anchored to the backdated date, not today


def test_start_new_cycle_rejects_invalid_stage():
    sm = StageManager(MagicMock(), {})
    with pytest.raises(ValueError):
        sm.start_new_cycle("not_a_real_stage", date.today())


def test_start_new_cycle_fires_stage_changed_event():
    hass = MagicMock()
    sm = StageManager(hass, {})
    coord_ref = MagicMock()
    coord_ref._entry = MagicMock(entry_id="entry123")
    sm.set_coordinator_ref(coord_ref)

    sm.start_new_cycle(STAGE_EARLY_VEG, date.today())

    hass.bus.async_fire.assert_called_once()
    event_name, payload = hass.bus.async_fire.call_args.args
    assert event_name == "helix_cultivate_stage_changed"
    assert payload["new_stage"] == STAGE_EARLY_VEG


def test_return_to_not_started_clears_stage_start_date():
    sm = StageManager(MagicMock(), {})
    sm.start_new_cycle(STAGE_EARLY_VEG, date(2026, 1, 1))

    sm.return_to_not_started()

    assert sm.cycle_state == CYCLE_STATE_NOT_STARTED
    assert sm.is_cycle_active is False
    assert sm.current_stage == STAGE_SEQUENCE[0]
    assert sm._stage_start_date is None
    assert sm.elapsed_days == 0


def test_return_to_not_started_distinct_from_old_reset_cycle_behavior():
    """Regression guard: the replaced reset_cycle() used to set
    stage_start_date to today, implying an active cycle. return_to_not_started
    must leave no start date at all, since nothing has actually started."""
    sm = StageManager(MagicMock(), {})
    sm.return_to_not_started()
    assert sm._stage_start_date is None


# ── HelixCoordinator.start_cycle() / abort_cycle() ──────────────────────────

@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._entry = MagicMock(entry_id="entry123")
    coord._entry.options = {}
    coord.hass = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord.stage_manager = StageManager(coord.hass, coord._config)

    coord.start_cycle = lambda gm, sd, ss: HelixCoordinator.start_cycle(coord, gm, sd, ss)
    coord.abort_cycle = lambda: HelixCoordinator.abort_cycle(coord)
    return coord


@pytest.mark.asyncio
async def test_start_cycle_sets_growth_mode_stage_and_date(fake_coord):
    await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", STAGE_EARLY_VEG)

    assert fake_coord._config[CONF_GROWTH_MODE] == GROWTH_MODE_PHOTOPERIOD
    assert fake_coord.stage_manager.current_stage == STAGE_EARLY_VEG
    assert fake_coord.stage_manager.cycle_state == CYCLE_STATE_ACTIVE

    call_kwargs = fake_coord.hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"][CONF_GROWTH_MODE] == GROWTH_MODE_PHOTOPERIOD
    assert call_kwargs["options"]["current_stage"] == STAGE_EARLY_VEG
    assert call_kwargs["options"][CONF_STAGE_START_DATE] == "2026-01-01"
    assert call_kwargs["options"][CONF_CYCLE_STATE] == CYCLE_STATE_ACTIVE


@pytest.mark.asyncio
async def test_start_cycle_accepts_backdated_date(fake_coord):
    await fake_coord.start_cycle(GROWTH_MODE_AUTOFLOWER, "2025-12-20", STAGE_GERMINATION)

    assert fake_coord.stage_manager._stage_start_date == date(2025, 12, 20)
    assert fake_coord.stage_manager.elapsed_days > 0


@pytest.mark.asyncio
async def test_start_cycle_defaults_to_today_on_missing_or_bad_date(fake_coord):
    await fake_coord.start_cycle(GROWTH_MODE_AUTOFLOWER, "", STAGE_GERMINATION)
    assert fake_coord.stage_manager._stage_start_date == date.today()

    await fake_coord.start_cycle(GROWTH_MODE_AUTOFLOWER, "not-a-date", STAGE_GERMINATION)
    assert fake_coord.stage_manager._stage_start_date == date.today()


@pytest.mark.asyncio
async def test_start_cycle_accepts_non_default_starting_stage(fake_coord):
    """E.g. clones purchased already in Early Veg."""
    await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", STAGE_EARLY_VEG)
    assert fake_coord.stage_manager.current_stage == STAGE_EARLY_VEG


@pytest.mark.asyncio
async def test_start_cycle_rejects_invalid_stage(fake_coord):
    with pytest.raises(ValueError):
        await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", "not_a_real_stage")


@pytest.mark.asyncio
async def test_start_cycle_rejects_invalid_growth_mode(fake_coord):
    with pytest.raises(ValueError):
        await fake_coord.start_cycle("not_a_real_mode", "2026-01-01", STAGE_GERMINATION)


@pytest.mark.asyncio
async def test_abort_cycle_returns_to_not_started_without_harvest_flow(fake_coord):
    await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", STAGE_EARLY_VEG)

    await fake_coord.abort_cycle()

    assert fake_coord.stage_manager.cycle_state == CYCLE_STATE_NOT_STARTED
    assert fake_coord.stage_manager.is_cycle_active is False
    call_kwargs = fake_coord.hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"][CONF_CYCLE_STATE] == CYCLE_STATE_NOT_STARTED
    fake_coord.hass.bus.async_fire.assert_called_with(
        "helix_cultivate_cycle_aborted", {"entry_id": "entry123"}
    )
