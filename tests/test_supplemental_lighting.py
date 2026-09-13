"""Tests for Supplemental Lighting (independent second light system):
Synced mode mirroring the main light's exact schedule, Targeted mode's own
independent stage-gated schedule (actively held off outside target stages,
not just unmanaged), the supplemental HID/ballast hot-restrike lockout using
its own independent state, and DLI estimation's deliberate, permanent
exclusion of the supplemental light's contribution.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_DLI_SENSOR,
    CONF_GROWTH_MODE,
    CONF_LIGHT_EFFICACY_UMOL_PER_J,
    CONF_LIGHT_WATTAGE_W,
    CONF_PP_VEG_HOURS,
    CONF_PP_VEG_LIGHTS_ON_TIME,
    CONF_RAMP_ENABLED,
    CONF_SUPPLEMENTAL_DURATION_HOURS,
    CONF_SUPPLEMENTAL_LIGHT_TYPE,
    CONF_SUPPLEMENTAL_MODE,
    CONF_SUPPLEMENTAL_ON_TIME,
    CONF_SUPPLEMENTAL_TARGET_STAGES,
    CONF_ZONE2_GROW_LIGHT,
    CONF_ZONE2_LIGHT_TYPE,
    CONF_ZONE2_SUPPLEMENTAL_LIGHT,
    DEFAULT_HID_RESTRIKE_LOCKOUT_MIN,
    GROWTH_MODE_PHOTOPERIOD,
    LIGHT_HID,
    LIGHT_LED,
    NS_ENERGY,
    STAGE_EARLY_VEG,
    STAGE_LATE_VEG,
    STAGE_PEAK_FLOWER,
    SUPPLEMENTAL_MODE_SYNCED,
    SUPPLEMENTAL_MODE_TARGETED,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_coord(monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: FIXED_NOW)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: FIXED_NOW)

    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_EARLY_VEG
    coord.light_intensity_pct = 100.0

    coord._light_applied_pct = 0.0
    coord._light_off_since = None
    coord._hid_restrike_delay_logged = False

    coord._supplemental_applied_pct = 0.0
    coord._supplemental_light_off_since = None
    coord._supplemental_hid_restrike_delay_logged = False

    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.states.get = MagicMock(return_value=None)

    coord._light_schedule_params = lambda: HelixCoordinator._light_schedule_params(coord)
    coord._light_schedule_params_for_stage = lambda stage: HelixCoordinator._light_schedule_params_for_stage(coord, stage)
    coord._light_schedule_multiplier = lambda light_id: HelixCoordinator._light_schedule_multiplier(coord, light_id)
    coord._effective_ramp_minutes = lambda light_id: HelixCoordinator._effective_ramp_minutes(coord, light_id)
    coord._supplemental_targeted_pct = lambda: HelixCoordinator._supplemental_targeted_pct(coord)
    coord._apply_supplemental_light_schedule = lambda light_id, pct: HelixCoordinator._apply_supplemental_light_schedule(coord, light_id, pct)
    coord._control_supplemental_light = lambda: HelixCoordinator._control_supplemental_light(coord)
    coord._estimate_ppfd = lambda: HelixCoordinator._estimate_ppfd(coord)
    coord._accumulate_dli = lambda interval_sec: HelixCoordinator._accumulate_dli(coord, interval_sec)
    coord._lights_on = lambda: HelixCoordinator._lights_on(coord)
    return coord


# ── Synced mode ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_synced_mode_mirrors_main_light_exact_schedule(fake_coord):
    """Synced mode must produce the identical applied % as the main light's
    own schedule at the same instant — achieved by routing through the same,
    untouched _light_schedule_multiplier with the supplemental entity id."""
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord._config[CONF_PP_VEG_HOURS] = 18.0
    fake_coord._config[CONF_PP_VEG_LIGHTS_ON_TIME] = "06:00"
    fake_coord._config[CONF_RAMP_ENABLED] = False
    fake_coord._config[CONF_ZONE2_SUPPLEMENTAL_LIGHT] = "light.supplemental"
    fake_coord._config[CONF_SUPPLEMENTAL_MODE] = SUPPLEMENTAL_MODE_SYNCED

    await fake_coord._control_supplemental_light()

    fake_coord.hass.services.async_call.assert_awaited_once()
    assert fake_coord._supplemental_applied_pct == 100.0  # fully within 18h window from 06:00


@pytest.mark.asyncio
async def test_synced_mode_off_when_main_schedule_off(fake_coord):
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord._config[CONF_PP_VEG_HOURS] = 2.0
    fake_coord._config[CONF_PP_VEG_LIGHTS_ON_TIME] = "04:00"  # off at 06:00, well before noon
    fake_coord._config[CONF_RAMP_ENABLED] = False
    fake_coord._config[CONF_ZONE2_SUPPLEMENTAL_LIGHT] = "light.supplemental"
    fake_coord._config[CONF_SUPPLEMENTAL_MODE] = SUPPLEMENTAL_MODE_SYNCED

    await fake_coord._control_supplemental_light()

    fake_coord.hass.services.async_call.assert_awaited_once_with(
        "light", "turn_off", {"entity_id": "light.supplemental"}
    )


# ── Targeted mode ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_targeted_mode_on_during_target_stage_and_window(fake_coord):
    fake_coord._config[CONF_ZONE2_SUPPLEMENTAL_LIGHT] = "light.supplemental"
    fake_coord._config[CONF_SUPPLEMENTAL_MODE] = SUPPLEMENTAL_MODE_TARGETED
    fake_coord._config[CONF_SUPPLEMENTAL_TARGET_STAGES] = [STAGE_PEAK_FLOWER]
    fake_coord._config[CONF_SUPPLEMENTAL_ON_TIME] = "06:00"
    fake_coord._config[CONF_SUPPLEMENTAL_DURATION_HOURS] = 12.0
    fake_coord.stage_manager.current_stage = STAGE_PEAK_FLOWER

    await fake_coord._control_supplemental_light()

    fake_coord.hass.services.async_call.assert_awaited_once()
    assert fake_coord._supplemental_applied_pct == 100.0


@pytest.mark.asyncio
async def test_targeted_mode_actively_held_off_outside_target_stages(fake_coord):
    """Not merely "unmanaged" — must actively command the light off when the
    current stage isn't in the configured target list, even if the on-time
    window would otherwise be active right now."""
    fake_coord._config[CONF_ZONE2_SUPPLEMENTAL_LIGHT] = "light.supplemental"
    fake_coord._config[CONF_SUPPLEMENTAL_MODE] = SUPPLEMENTAL_MODE_TARGETED
    fake_coord._config[CONF_SUPPLEMENTAL_TARGET_STAGES] = [STAGE_PEAK_FLOWER]
    fake_coord._config[CONF_SUPPLEMENTAL_ON_TIME] = "06:00"
    fake_coord._config[CONF_SUPPLEMENTAL_DURATION_HOURS] = 12.0
    fake_coord.stage_manager.current_stage = STAGE_LATE_VEG  # not in target list
    # Simulate a manual toggle having left the entity physically on.
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="on"))

    await fake_coord._control_supplemental_light()

    fake_coord.hass.services.async_call.assert_awaited_once_with(
        "light", "turn_off", {"entity_id": "light.supplemental"}
    )
    assert fake_coord._supplemental_applied_pct == 0.0


@pytest.mark.asyncio
async def test_targeted_mode_off_outside_its_own_time_window_even_in_target_stage(fake_coord):
    fake_coord._config[CONF_ZONE2_SUPPLEMENTAL_LIGHT] = "light.supplemental"
    fake_coord._config[CONF_SUPPLEMENTAL_MODE] = SUPPLEMENTAL_MODE_TARGETED
    fake_coord._config[CONF_SUPPLEMENTAL_TARGET_STAGES] = [STAGE_PEAK_FLOWER]
    fake_coord._config[CONF_SUPPLEMENTAL_ON_TIME] = "13:00"  # starts after FIXED_NOW (noon)
    fake_coord._config[CONF_SUPPLEMENTAL_DURATION_HOURS] = 2.0
    fake_coord.stage_manager.current_stage = STAGE_PEAK_FLOWER

    await fake_coord._control_supplemental_light()

    fake_coord.hass.services.async_call.assert_awaited_once_with(
        "light", "turn_off", {"entity_id": "light.supplemental"}
    )


# ── Supplemental HID hot-restrike lockout (independent state) ──────────────

@pytest.mark.asyncio
async def test_supplemental_hid_lockout_delays_restrike_independently_of_main(fake_coord):
    fake_coord._config[CONF_SUPPLEMENTAL_LIGHT_TYPE] = LIGHT_HID
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="off"))
    fake_coord._supplemental_light_off_since = FIXED_NOW  # just turned off
    # Main light's own lockout state must be irrelevant to this call.
    fake_coord._light_off_since = FIXED_NOW - timedelta(
        minutes=DEFAULT_HID_RESTRIKE_LOCKOUT_MIN + 100
    )

    await fake_coord._apply_supplemental_light_schedule("light.supplemental", 100.0)

    fake_coord.hass.services.async_call.assert_not_called()
    assert fake_coord._supplemental_hid_restrike_delay_logged is True


@pytest.mark.asyncio
async def test_supplemental_hid_lockout_clears_after_window(fake_coord):
    fake_coord._config[CONF_SUPPLEMENTAL_LIGHT_TYPE] = LIGHT_HID
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="off"))
    fake_coord._supplemental_light_off_since = FIXED_NOW - timedelta(
        minutes=DEFAULT_HID_RESTRIKE_LOCKOUT_MIN + 1
    )

    await fake_coord._apply_supplemental_light_schedule("light.supplemental", 100.0)

    fake_coord.hass.services.async_call.assert_awaited_once()
    assert fake_coord._supplemental_applied_pct == 100.0


# ── DLI estimation must permanently exclude supplemental ────────────────────

def test_dli_estimation_ignores_supplemental_light_entirely(fake_coord):
    """_estimate_ppfd must be driven only by the main light's own applied %
    and its own CONF_ZONE2_LIGHT_TYPE efficacy — the supplemental light's
    config/state must have zero effect on the DLI estimate, even when the
    supplemental fixture is fully on and the main light is off."""
    fake_coord._config = {
        CONF_LIGHT_WATTAGE_W: 600.0,
        CONF_ZONE2_LIGHT_TYPE: LIGHT_LED,
        "zone2_width_m": 1.2,
        "zone2_depth_m": 1.2,
        # Supplemental fully on with a huge efficacy — must not leak in.
        CONF_SUPPLEMENTAL_LIGHT_TYPE: LIGHT_HID,
    }
    fake_coord._light_applied_pct = 0.0  # main light OFF
    fake_coord._supplemental_applied_pct = 100.0  # supplemental fully ON

    assert fake_coord._estimate_ppfd() == 0.0


def test_dli_accumulation_unaffected_by_supplemental_state(fake_coord):
    from custom_components.helix_cultivate.const import NS_ENERGY as _NS_ENERGY
    fake_coord._config = {
        CONF_LIGHT_WATTAGE_W: 600.0,
        CONF_ZONE2_LIGHT_TYPE: LIGHT_LED,
        "zone2_width_m": 1.2,
        "zone2_depth_m": 1.2,
    }
    fake_coord._light_applied_pct = 100.0
    fake_coord._supplemental_applied_pct = 0.0
    fake_coord.data = {_NS_ENERGY: {"dli_today_mol": 0.0}}
    fake_coord._accumulate_dli(30.0)
    baseline = fake_coord.data[_NS_ENERGY]["dli_today_mol"]
    assert baseline > 0.0

    # Re-run identically except the supplemental light is now also fully on —
    # the accumulated DLI increment for this tick must be unchanged.
    fake_coord.data = {_NS_ENERGY: {"dli_today_mol": 0.0}}
    fake_coord._supplemental_applied_pct = 100.0
    fake_coord._accumulate_dli(30.0)
    assert fake_coord.data[_NS_ENERGY]["dli_today_mol"] == pytest.approx(baseline)
