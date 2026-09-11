"""Tests for the Phase 1.5 light schedule engine in coordinator.py:
growth mode switching, the fixed Stretch->Flowering stage-group mapping, the
always-instant Veg->Flower transition, sunrise/sunset ramp behaviour
(including auto-disable for switch-domain fixtures), the HID/ballast
hot-restrike lockout, and DLI estimation with/without a physical sensor.
"""
from __future__ import annotations

from datetime import datetime, time as dtime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_AF_LIGHT_HOURS,
    CONF_AF_LIGHTS_ON_TIME,
    CONF_DLI_SENSOR,
    CONF_GROWTH_MODE,
    CONF_LIGHT_WATTAGE_W,
    CONF_PP_FLOWER_HOURS,
    CONF_PP_FLOWER_LIGHTS_ON_TIME,
    CONF_PP_VEG_HOURS,
    CONF_PP_VEG_LIGHTS_ON_TIME,
    CONF_RAMP_ENABLED,
    CONF_RAMP_PRESET,
    CONF_ZONE2_GROW_LIGHT,
    CONF_ZONE2_LIGHT_TYPE,
    DEFAULT_HID_RESTRIKE_LOCKOUT_MIN,
    GROWTH_MODE_AUTOFLOWER,
    GROWTH_MODE_PHOTOPERIOD,
    LIGHT_HID,
    LIGHT_LED,
    RAMP_PRESET_CUSTOM,
    RAMP_PRESET_FAST,
    RAMP_PRESET_GENTLE,
    RAMP_PRESET_STANDARD,
    STAGE_DRYING,
    STAGE_EARLY_VEG,
    STAGE_GERMINATION,
    STAGE_LATE_VEG,
    STAGE_PEAK_FLOWER,
    STAGE_RIPENING,
    STAGE_SEEDLING,
    STAGE_STRETCH,
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
    coord.hass = MagicMock()
    coord.hass.services.async_call = AsyncMock()
    coord.hass.states.get = MagicMock(return_value=None)

    # MagicMock auto-generates a (always-truthy, wrong-return-type) mock for
    # any attribute access — bind the real unbound methods so that when the
    # implementation under test calls another coordinator method via
    # `self.foo()`, it runs the actual logic against this same fake, not a
    # meaningless auto-mock.
    coord._light_schedule_params = lambda: HelixCoordinator._light_schedule_params(coord)
    coord._effective_ramp_minutes = lambda light_id: HelixCoordinator._effective_ramp_minutes(coord, light_id)
    coord._estimate_ppfd = lambda: HelixCoordinator._estimate_ppfd(coord)
    coord._lights_on = lambda: HelixCoordinator._lights_on(coord)
    return coord


def _params(coord):
    return HelixCoordinator._light_schedule_params(coord)


def _multiplier(coord, light_id="light.grow"):
    return HelixCoordinator._light_schedule_multiplier(coord, light_id)


# ── Growth mode + stage-group mapping ───────────────────────────────────────

def test_autoflower_ignores_stage_entirely(fake_coord):
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    fake_coord._config[CONF_AF_LIGHT_HOURS] = 20.0
    fake_coord._config[CONF_AF_LIGHTS_ON_TIME] = "05:00"

    for stage in (STAGE_GERMINATION, STAGE_STRETCH, STAGE_PEAK_FLOWER, STAGE_RIPENING):
        fake_coord.stage_manager.current_stage = stage
        hours, on_time, key = _params(fake_coord)
        assert hours == 20.0
        assert on_time == dtime(5, 0)
        assert key == "af"


@pytest.mark.parametrize(
    "stage", [STAGE_GERMINATION, STAGE_SEEDLING, STAGE_EARLY_VEG, STAGE_LATE_VEG]
)
def test_photoperiod_veg_group_uses_veg_schedule(fake_coord, stage):
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord.stage_manager.current_stage = stage
    hours, _on_time, key = _params(fake_coord)
    assert key == "pp_veg"
    assert hours == 18.0  # DEFAULT_PP_VEG_HOURS


@pytest.mark.parametrize("stage", [STAGE_STRETCH, STAGE_PEAK_FLOWER, STAGE_RIPENING])
def test_photoperiod_flower_group_uses_flower_schedule(fake_coord, stage):
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord.stage_manager.current_stage = stage
    hours, _on_time, key = _params(fake_coord)
    assert key == "pp_flower"
    assert hours == 12.0  # DEFAULT_PP_FLOWER_HOURS


def test_stretch_specifically_is_always_flowering_group(fake_coord):
    """Explicit acceptance-checklist item: Stretch is the plant's response
    *after* the light flip, not a pre-flip phase."""
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord.stage_manager.current_stage = STAGE_STRETCH
    _hours, _on_time, key = _params(fake_coord)
    assert key == "pp_flower"


def test_drying_stage_is_always_dark_regardless_of_growth_mode(fake_coord):
    fake_coord.stage_manager.current_stage = STAGE_DRYING
    for mode in (GROWTH_MODE_AUTOFLOWER, GROWTH_MODE_PHOTOPERIOD):
        fake_coord._config[CONF_GROWTH_MODE] = mode
        hours, _on_time, _key = _params(fake_coord)
        assert hours == 0.0
        assert _multiplier(fake_coord) == 0.0


# ── Instant Veg->Flower transition ──────────────────────────────────────────

def test_veg_to_flower_transition_is_instant_not_gradual(fake_coord):
    """The moment current_stage crosses into the Flowering group, the very
    next schedule computation must reflect the new schedule outright — no
    interpolation step, regardless of Smooth Glide being enabled elsewhere.
    """
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
    fake_coord._config[CONF_PP_VEG_HOURS] = 18.0
    fake_coord._config[CONF_PP_VEG_LIGHTS_ON_TIME] = "06:00"
    fake_coord._config[CONF_PP_FLOWER_HOURS] = 12.0
    fake_coord._config[CONF_PP_FLOWER_LIGHTS_ON_TIME] = "20:00"

    fake_coord.stage_manager.current_stage = STAGE_LATE_VEG
    veg_hours, veg_on, veg_key = _params(fake_coord)
    assert (veg_hours, veg_on, veg_key) == (18.0, dtime(6, 0), "pp_veg")

    # Auto-Advance (or a manual override) flips current_stage — simulate it
    # exactly as the stage manager would, mid-tick, with no transition state.
    fake_coord.stage_manager.current_stage = STAGE_STRETCH
    flower_hours, flower_on, flower_key = _params(fake_coord)
    assert (flower_hours, flower_on, flower_key) == (12.0, dtime(20, 0), "pp_flower")

    # No intermediate/blended value was ever produced — the two computations
    # above are the only two states this can ever be in for these stages.


# ── Ramp behaviour ───────────────────────────────────────────────────────────

def test_ramp_auto_disabled_for_switch_domain(fake_coord):
    fake_coord._config[CONF_RAMP_ENABLED] = True
    fake_coord._config[CONF_RAMP_PRESET] = RAMP_PRESET_STANDARD
    assert HelixCoordinator._effective_ramp_minutes(fake_coord, "switch.grow_light") == 0.0


def test_ramp_disabled_toggle_overrides_dimmable_light(fake_coord):
    fake_coord._config[CONF_RAMP_ENABLED] = False
    fake_coord._config[CONF_RAMP_PRESET] = RAMP_PRESET_STANDARD
    assert HelixCoordinator._effective_ramp_minutes(fake_coord, "light.grow_light") == 0.0


@pytest.mark.parametrize(
    "preset,expected", [
        (RAMP_PRESET_GENTLE, 30.0),
        (RAMP_PRESET_STANDARD, 15.0),
        (RAMP_PRESET_FAST, 5.0),
    ],
)
def test_ramp_named_presets(fake_coord, preset, expected):
    fake_coord._config[CONF_RAMP_ENABLED] = True
    fake_coord._config[CONF_RAMP_PRESET] = preset
    assert HelixCoordinator._effective_ramp_minutes(fake_coord, "light.grow_light") == expected


def test_ramp_custom_uses_sunrise_ramp_min(fake_coord):
    fake_coord._config[CONF_RAMP_ENABLED] = True
    fake_coord._config[CONF_RAMP_PRESET] = RAMP_PRESET_CUSTOM
    fake_coord._config["sunrise_ramp_min"] = 42.0
    assert HelixCoordinator._effective_ramp_minutes(fake_coord, "light.grow_light") == 42.0


def test_multiplier_ramps_up_at_start_of_window(fake_coord):
    # FIXED_NOW is 12:00. On-time 11:50, 10-minute ramp -> 10 min elapsed ==
    # exactly the ramp duration -> fully ramped in (100%).
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    fake_coord._config[CONF_AF_LIGHT_HOURS] = 18.0
    fake_coord._config[CONF_AF_LIGHTS_ON_TIME] = "11:50"
    fake_coord._config[CONF_RAMP_ENABLED] = True
    fake_coord._config[CONF_RAMP_PRESET] = RAMP_PRESET_CUSTOM
    fake_coord._config["sunrise_ramp_min"] = 10.0
    assert _multiplier(fake_coord, "light.grow") == 100.0


def test_multiplier_mid_ramp(fake_coord):
    # On-time 11:55, 10-min ramp -> 5 min elapsed at FIXED_NOW (12:00) -> 50%.
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    fake_coord._config[CONF_AF_LIGHT_HOURS] = 18.0
    fake_coord._config[CONF_AF_LIGHTS_ON_TIME] = "11:55"
    fake_coord._config[CONF_RAMP_ENABLED] = True
    fake_coord._config[CONF_RAMP_PRESET] = RAMP_PRESET_CUSTOM
    fake_coord._config["sunrise_ramp_min"] = 10.0
    assert _multiplier(fake_coord, "light.grow") == 50.0


def test_multiplier_handles_midnight_crossing_schedule(fake_coord):
    # On-time 20:00, 18h duration -> off at 14:00 next day. At FIXED_NOW
    # (12:00) that's still well within the on-window (16h elapsed < 18h).
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    fake_coord._config[CONF_AF_LIGHT_HOURS] = 18.0
    fake_coord._config[CONF_AF_LIGHTS_ON_TIME] = "20:00"
    fake_coord._config[CONF_RAMP_ENABLED] = False
    assert _multiplier(fake_coord, "light.grow") == 100.0


def test_multiplier_off_outside_window(fake_coord):
    # On-time 06:00, 12h duration -> off at 18:00. FIXED_NOW is 12:00 noon,
    # so still on; push on-time later so "now" falls after the off boundary.
    fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    fake_coord._config[CONF_AF_LIGHT_HOURS] = 6.0
    fake_coord._config[CONF_AF_LIGHTS_ON_TIME] = "04:00"  # off at 10:00, before noon
    fake_coord._config[CONF_RAMP_ENABLED] = False
    assert _multiplier(fake_coord, "light.grow") == 0.0


# ── HID/ballast hot-restrike lockout ────────────────────────────────────────

@pytest.mark.asyncio
async def test_hid_lockout_delays_restrike_and_logs_once(fake_coord):
    fake_coord._config[CONF_ZONE2_LIGHT_TYPE] = LIGHT_HID
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="off"))
    fake_coord._light_off_since = FIXED_NOW  # just turned off this instant

    await HelixCoordinator._apply_grow_light_schedule(fake_coord, "light.grow", 100.0)

    fake_coord.hass.services.async_call.assert_not_called()
    assert fake_coord._hid_restrike_delay_logged is True


@pytest.mark.asyncio
async def test_hid_lockout_clears_and_applies_after_window(fake_coord, monkeypatch):
    fake_coord._config[CONF_ZONE2_LIGHT_TYPE] = LIGHT_HID
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="off"))
    from datetime import timedelta
    fake_coord._light_off_since = FIXED_NOW - timedelta(
        minutes=DEFAULT_HID_RESTRIKE_LOCKOUT_MIN + 1
    )

    await HelixCoordinator._apply_grow_light_schedule(fake_coord, "light.grow", 100.0)

    fake_coord.hass.services.async_call.assert_awaited_once()
    assert fake_coord._light_applied_pct == 100.0


@pytest.mark.asyncio
async def test_non_hid_fixture_never_locked_out(fake_coord):
    fake_coord._config[CONF_ZONE2_LIGHT_TYPE] = LIGHT_LED
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="off"))
    fake_coord._light_off_since = FIXED_NOW  # just turned off — irrelevant for LED

    await HelixCoordinator._apply_grow_light_schedule(fake_coord, "light.grow", 100.0)

    fake_coord.hass.services.async_call.assert_awaited_once()


# ── DLI estimation (must work fully with zero DLI sensor mapped) ───────────

def test_dli_estimation_used_when_no_sensor_mapped(fake_coord):
    fake_coord._config = {
        CONF_LIGHT_WATTAGE_W: 600.0,
        CONF_ZONE2_LIGHT_TYPE: LIGHT_LED,
        "zone2_width_m": 1.2,
        "zone2_depth_m": 1.2,
    }
    fake_coord._light_applied_pct = 100.0
    fake_coord.data = {"energy": {"dli_today_mol": 0.0}}
    from custom_components.helix_cultivate.const import NS_ENERGY
    fake_coord.data = {NS_ENERGY: {"dli_today_mol": 0.0}}

    HelixCoordinator._accumulate_dli(fake_coord, 30.0)

    assert fake_coord.data[NS_ENERGY]["dli_today_mol"] > 0.0


def test_dli_real_sensor_always_preferred_over_estimate(fake_coord):
    from custom_components.helix_cultivate.const import NS_ENERGY
    fake_coord._config = {
        CONF_DLI_SENSOR: "sensor.real_par",
        CONF_LIGHT_WATTAGE_W: 99999.0,  # would dominate if estimate were used
    }
    fake_coord.data = {NS_ENERGY: {"dli_today_mol": 0.0}}
    fake_coord._lights_on = MagicMock(return_value=True)
    fake_coord._read_sensor = MagicMock(return_value=500.0)  # real PPFD reading

    HelixCoordinator._accumulate_dli(fake_coord, 30.0)

    expected = 500.0 * 30.0 / 1_000_000.0
    assert fake_coord.data[NS_ENERGY]["dli_today_mol"] == pytest.approx(expected)


def test_dli_estimation_zero_while_light_is_off(fake_coord):
    """No sensor mapped, and the schedule has the light at 0% right now —
    the estimate must be 0, not the fixture's full-brightness wattage-based
    value (would otherwise keep accumulating "phantom" DLI while dark)."""
    from custom_components.helix_cultivate.const import NS_ENERGY
    fake_coord._config = {CONF_LIGHT_WATTAGE_W: 600.0}  # no DLI sensor mapped
    fake_coord.data = {NS_ENERGY: {"dli_today_mol": 0.0}}
    fake_coord._light_applied_pct = 0.0

    HelixCoordinator._accumulate_dli(fake_coord, 30.0)

    assert fake_coord.data[NS_ENERGY]["dli_today_mol"] == 0.0
