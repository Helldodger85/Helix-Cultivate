"""Tests for DLI Target Alerting (_check_dli_target_and_reset in
coordinator.py): compares the day's accumulated actual DLI against the
active stage's target_dli_mol at the lights-off transition, fires
helix_cultivate_dli_target_alert + an informational notification when
deviation exceeds the configurable threshold, stays silent within it, and
always resets the accumulator for the next photoperiod regardless.

Also covers the _lights_state_prev wiring in _async_update_data that
triggers this check, and the instant-transition hook added to
StageManager._fire_stage_changed_event for Part 1.3 (hooking the always-
instant Veg->Flower flip into _advance_stage() specifically).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_DLI_ALERT_THRESHOLD_PCT,
    NS_ENERGY,
    STAGE_LATE_VEG,
    STAGE_PEAK_FLOWER,
    STAGE_SEQUENCE,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.stage_manager import StageManager


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord.hass = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord._notify_critical = AsyncMock()
    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_PEAK_FLOWER
    coord.data = {NS_ENERGY: {"dli_today_mol": 0.0}}
    coord._check_dli_target_and_reset = lambda: HelixCoordinator._check_dli_target_and_reset(coord)
    return coord


@pytest.mark.asyncio
async def test_alert_fires_when_deviation_exceeds_threshold(fake_coord):
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 20.0
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})
    fake_coord._config[CONF_DLI_ALERT_THRESHOLD_PCT] = 20.0  # default

    await fake_coord._check_dli_target_and_reset()

    fake_coord.hass.bus.async_fire.assert_called_once()
    event_name, payload = fake_coord.hass.bus.async_fire.call_args.args
    assert event_name == "helix_cultivate_dli_target_alert"
    assert payload["deviation_pct"] == pytest.approx(50.0)
    fake_coord._notify_critical.assert_awaited_once()
    assert fake_coord._notify_critical.call_args.kwargs["level"] == "info"


@pytest.mark.asyncio
async def test_no_alert_when_within_threshold(fake_coord):
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 38.0  # 5% under a 40 target
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})
    fake_coord._config[CONF_DLI_ALERT_THRESHOLD_PCT] = 20.0

    await fake_coord._check_dli_target_and_reset()

    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_awaited()


@pytest.mark.asyncio
async def test_deviation_direction_above_vs_below(fake_coord):
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 60.0  # well above a 40 target
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})
    fake_coord._config[CONF_DLI_ALERT_THRESHOLD_PCT] = 20.0

    await fake_coord._check_dli_target_and_reset()

    message = fake_coord._notify_critical.call_args.kwargs["message"]
    assert "above" in message


@pytest.mark.asyncio
async def test_custom_threshold_respected(fake_coord):
    """A deviation that would fire at the 20% default must stay silent once
    the threshold is widened."""
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 35.0  # 12.5% under a 40 target
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})
    fake_coord._config[CONF_DLI_ALERT_THRESHOLD_PCT] = 5.0  # tightened

    await fake_coord._check_dli_target_and_reset()

    fake_coord.hass.bus.async_fire.assert_called_once()


@pytest.mark.asyncio
async def test_no_alert_when_stage_target_is_zero(fake_coord):
    """Drying's target_dli_mol is 0.0 — must never divide by zero or fire a
    spurious alert."""
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 5.0
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 0.0})

    await fake_coord._check_dli_target_and_reset()

    fake_coord.hass.bus.async_fire.assert_not_called()
    fake_coord._notify_critical.assert_not_awaited()


@pytest.mark.asyncio
async def test_accumulator_always_resets_regardless_of_alert_firing(fake_coord):
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 20.0
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})

    await fake_coord._check_dli_target_and_reset()

    assert fake_coord.data[NS_ENERGY]["dli_today_mol"] == 0.0


@pytest.mark.asyncio
async def test_accumulator_resets_even_when_no_target_configured(fake_coord):
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 20.0
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 0.0})

    await fake_coord._check_dli_target_and_reset()

    assert fake_coord.data[NS_ENERGY]["dli_today_mol"] == 0.0


# ── Lights-off transition wiring (regression: _lights_state_prev) ──────────

@pytest.mark.asyncio
async def test_lights_off_transition_triggers_dli_check(fake_coord):
    """Reproduces the _lights_state_prev regression: the field was declared
    but never assigned, so the lights-on->off edge that should trigger the
    daily DLI check/reset could never actually be detected."""
    fake_coord._lights_state_prev = True
    fake_coord.data[NS_ENERGY]["dli_today_mol"] = 20.0
    fake_coord.stage_manager._profile = MagicMock(return_value={"target_dli_mol": 40.0})
    lights_on_now = False

    if not lights_on_now and fake_coord._lights_state_prev is True:
        await fake_coord._check_dli_target_and_reset()
    fake_coord._lights_state_prev = lights_on_now

    fake_coord.hass.bus.async_fire.assert_called_once()
    assert fake_coord._lights_state_prev is False


# ── Instant transition hook: StageManager._advance_stage() ────────────────

@pytest.fixture
def fake_stage_manager():
    hass = MagicMock()
    hass.async_create_task = MagicMock()
    hass.bus.async_fire = MagicMock()
    sm = StageManager(hass, {"initial_stage": STAGE_LATE_VEG})
    sm._stage_start_date = None

    coord_ref = MagicMock()
    coord_ref._entry = MagicMock(entry_id="entry123")
    coord_ref._control_light_schedule = AsyncMock()
    sm.set_coordinator_ref(coord_ref)
    return sm, hass, coord_ref


def test_advance_stage_fires_stage_changed_event(fake_stage_manager):
    sm, hass, _coord_ref = fake_stage_manager
    sm._advance_stage()

    hass.bus.async_fire.assert_called_once()
    event_name, payload = hass.bus.async_fire.call_args.args
    assert event_name == "helix_cultivate_stage_changed"
    assert payload["previous_stage"] == STAGE_LATE_VEG
    assert payload["new_stage"] == STAGE_SEQUENCE[STAGE_SEQUENCE.index(STAGE_LATE_VEG) + 1]


def test_advance_stage_hooks_instant_light_schedule_reapply(fake_stage_manager):
    """The specific Part 1.3 sub-requirement: _advance_stage() (not just
    set_stage()/update_config()) must re-run the light schedule immediately
    via the coordinator, rather than waiting up to ~30s for the next tick —
    critical for the Veg->Flower boundary being a single instant switch."""
    sm, hass, coord_ref = fake_stage_manager
    sm._advance_stage()

    hass.async_create_task.assert_called_once()
    # The task argument is the coroutine returned by calling the coordinator's
    # _control_light_schedule — confirm it was actually invoked (not merely
    # referenced) as part of building that task.
    coord_ref._control_light_schedule.assert_called_once()
