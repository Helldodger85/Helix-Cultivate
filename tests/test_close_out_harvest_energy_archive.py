"""Tests for close_out_harvest()'s Energy & ROI archiving addition (2.7):
a full harvest close-out counts as "the last reset" for the Previous Cycle
display, same as the dedicated Reset button — and _cycle_cost must be reset
explicitly (a regression risk introduced by switching _accumulate_energy to
incremental cost accumulation, which no longer self-corrects to 0 just
because _cycle_kwh did).
"""
from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import CONF_CYCLE_STATE, CYCLE_STATE_NOT_STARTED, NS_ENERGY
from custom_components.helix_cultivate.coordinator import HelixCoordinator

DOMAIN = "helix_cultivate"


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord.hass = MagicMock()
    coord.hass.config.path = MagicMock(return_value="/tmp/fake")
    coord.hass.bus.async_fire = MagicMock()
    coord._notify_critical = AsyncMock()

    journal = MagicMock()
    journal.async_pop_timelapse_images = AsyncMock(return_value=[])
    journal.archive_cycle = AsyncMock(return_value="harvest_0001")
    journal.async_set_previous_cycle_energy = AsyncMock(
        return_value={"cycle_kwh": 5.0, "cycle_cost_usd": 1.5, "archived_at": "2026-01-15T00:00:00+00:00"}
    )
    coord.hass.data = {DOMAIN: {"journal_store": journal}}
    coord._journal = journal

    coord.stage_manager = MagicMock()
    coord.stage_manager.actual_stage_durations = MagicMock(return_value={})
    coord.stage_manager.return_to_not_started = MagicMock()
    coord.stage_manager.current_stage = "germination"

    coord._entry.options = {}
    coord.hass.config_entries.async_update_entry = MagicMock()

    coord._vpd_history = deque()
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2
    coord._vpd_in_range_pct = lambda: HelixCoordinator._vpd_in_range_pct(coord)

    coord._cycle_kwh = 5.0
    coord._cycle_cost = 1.5
    coord._zone1_cycle_kwh = 2.0
    coord._zone2_cycle_kwh = 3.0
    coord._drying_cycle_kwh = 0.0
    coord._global_cycle_kwh = 0.0
    coord._zone1_cycle_cost = 0.6
    coord._zone2_cycle_cost = 0.9
    coord._drying_cycle_cost = 0.0
    coord._global_cycle_cost = 0.0
    coord._last_energy_tick = object()
    coord.data = {NS_ENERGY: {"cycle_kwh": 5.0, "cycle_cost_usd": 1.5, "dli_today_mol": 12.0}}

    # Part 4.4 extracted the record-building/archiving logic shared with
    # harvest_complete_drying_batch() into this helper — close_out_harvest
    # now calls it internally, so the mock must route through the real
    # implementation too rather than auto-generating a non-awaitable stub.
    coord._finalize_harvest_record = lambda *a, **kw: HelixCoordinator._finalize_harvest_record(coord, *a, **kw)
    coord.close_out_harvest = lambda wet, dry: HelixCoordinator.close_out_harvest(coord, wet, dry)
    return coord


@pytest.mark.asyncio
async def test_close_out_harvest_archives_previous_cycle_energy(fake_coord):
    await fake_coord.close_out_harvest(100.0, 20.0)

    fake_coord._journal.async_set_previous_cycle_energy.assert_awaited_once_with(
        "entry123", 5.0, 1.5
    )


@pytest.mark.asyncio
async def test_close_out_harvest_resets_cycle_cost_not_just_kwh(fake_coord):
    """Regression: previously only _cycle_kwh was reset here, relying on
    _accumulate_energy's old from-scratch recompute to zero _cycle_cost on
    the next tick. That recompute no longer happens (cost accumulates
    incrementally now), so _cycle_cost must be reset explicitly too."""
    await fake_coord.close_out_harvest(100.0, 20.0)

    assert fake_coord._cycle_kwh == 0.0
    assert fake_coord._cycle_cost == 0.0
    assert fake_coord._zone1_cycle_kwh == 0.0
    assert fake_coord._zone2_cycle_kwh == 0.0
    assert fake_coord._zone1_cycle_cost == 0.0
    assert fake_coord._zone2_cycle_cost == 0.0
    assert fake_coord._last_energy_tick is None
    assert fake_coord.data[NS_ENERGY]["cycle_kwh"] == 0.0
    assert fake_coord.data[NS_ENERGY]["cycle_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_close_out_harvest_returns_to_not_started(fake_coord):
    """Part 1.4: a completed harvest must not silently reactivate
    Germination Day 0 — it returns to a genuine not_started state, and the
    next grower action is an explicit Start New Cycle."""
    await fake_coord.close_out_harvest(100.0, 20.0)

    fake_coord.stage_manager.return_to_not_started.assert_called_once()
    fake_coord.hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = fake_coord.hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"][CONF_CYCLE_STATE] == CYCLE_STATE_NOT_STARTED
