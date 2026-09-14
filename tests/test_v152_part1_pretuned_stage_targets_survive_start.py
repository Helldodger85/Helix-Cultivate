"""Test for v1.5.2 Part 1: a stage's targets tuned while cycle_state is
'not_started' (now possible at all, per this release's fix) must be the
values actually in effect once Start New Cycle is pressed and that stage
becomes active — start_cycle() must never reset or clobber any
stage_targets_{stage} the grower already saved.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_ZONE2_CYCLE_ID,
    GROWTH_MODE_PHOTOPERIOD,
    STAGE_GERMINATION,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.stage_manager import StageManager


def _bind(coord, *names):
    for name in names:
        setattr(coord, name, (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name))


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord._entry.options = {}
    coord.hass = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock(
        side_effect=lambda entry, options: setattr(entry, "options", options)
    )
    coord.stage_manager = StageManager(coord.hass, coord._config)
    coord.stage_manager.set_coordinator_ref(coord)
    _bind(coord, "start_cycle")
    return coord


@pytest.mark.asyncio
async def test_start_cycle_never_touches_stage_targets(fake_coord):
    tuned = {"day_temp_c": 27.5, "day_vpd_min": 1.0, "day_vpd_max": 1.3, "duration_days": 6}
    fake_coord._config["stage_targets_germination"] = tuned
    fake_coord._entry.options["stage_targets_germination"] = dict(tuned)

    await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", STAGE_GERMINATION)

    new_options = fake_coord.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert new_options["stage_targets_germination"] == tuned


@pytest.mark.asyncio
async def test_tuned_values_are_what_the_stage_actually_runs_with_once_active(fake_coord):
    """End-to-end through the real StageManager: after start_cycle(), the
    now-active germination stage's resolved profile/duration reflect
    exactly the values tuned before the cycle started — not the coded
    defaults."""
    tuned = {"day_temp_c": 27.5, "duration_days": 6}
    fake_coord._config["stage_targets_germination"] = tuned

    await fake_coord.start_cycle(GROWTH_MODE_PHOTOPERIOD, "2026-01-01", STAGE_GERMINATION)

    assert fake_coord._config[CONF_ZONE2_CYCLE_ID] is not None
    assert fake_coord.stage_manager.current_stage == STAGE_GERMINATION
    profile = fake_coord.stage_manager._profile(STAGE_GERMINATION)
    assert profile["day_temp_c"] == 27.5
    assert fake_coord.stage_manager._duration(STAGE_GERMINATION) == 6
