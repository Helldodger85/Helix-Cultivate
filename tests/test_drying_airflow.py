"""Tests for the Part 2.A Drying Airflow Overhaul in climate_engine.py:
Zone 2's own gentle-cyclic drying strategy (_control_zone2_drying_airflow),
its exact ordering ahead of the lights-off purge branch in _control_exhaust,
the dedicated drying exhaust floor, the hard humidity-ceiling override
(sustained vs. brief), and constant/cyclic airflow mode alternation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.climate_engine as climate_engine_module
from custom_components.helix_cultivate.const import (
    CONF_DRYING_AIRFLOW_MODE,
    CONF_DRYING_CYCLE_OFF_MIN,
    CONF_DRYING_CYCLE_ON_MIN,
    CONF_DRYING_EXHAUST_MIN_PCT,
    CONF_DRYING_HUMIDITY_CEILING_PCT,
    CONF_EXHAUST_FAN,
    CONF_EXHAUST_MIN_PCT,
    DEFAULT_DRYING_EXHAUST_MIN_PCT,
    DEFAULT_EXHAUST_MIN_PCT,
    DRYING_AIRFLOW_CONSTANT,
    DRYING_AIRFLOW_CYCLIC,
    DRYING_CYCLE_EXHAUST_PCT,
    DRYING_HUMIDITY_CEILING_DWELL_MIN,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    NS_CLIMATE,
    STAGE_DRYING,
    STAGE_PEAK_FLOWER,
)

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


def _wire_fan_entity(mock_coord, entity_id="fan.exhaust"):
    """_set_fan_pct no-ops unless hass.states.get returns a real state for
    the given entity — wire it up so applied-% assertions can also confirm
    the actual service call happened."""
    mock_coord.hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(state="on") if eid == entity_id else None
    )


# ── Ordering: STAGE_DRYING check must run before the lights-off purge ──────

@pytest.mark.asyncio
async def test_drying_stage_overrides_lights_off_purge_ordering(engine, mock_coord, frozen_now):
    """The exact scenario called out in the ticket: a grow always transitions
    Flowering (lights on) -> Drying (lights off) simultaneously. Without the
    STAGE_DRYING check running before the purge branch, this tick would
    apply +40% aggressive purge instead of the gentle floor."""
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord._config[CONF_EXHAUST_MIN_PCT] = DEFAULT_EXHAUST_MIN_PCT
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    _wire_fan_entity(mock_coord)

    # Simulate the exact lights-on->off edge that would otherwise start the
    # purge window.
    result = await engine._control_exhaust(
        leaf_vpd=1.0,
        canopy_temp=20.0,
        upper_enthalpy=None,
        lung_enthalpy=None,
        sensor_dropout=False,
        lights_on=False,
        thermal_runaway=False,
    )

    expected_floor = max(DRYING_CYCLE_EXHAUST_PCT, DEFAULT_DRYING_EXHAUST_MIN_PCT)
    assert result == expected_floor
    # Purge would have been min_pct + 40 == 50.0 for a default 10% floor —
    # confirm that value was never applied.
    assert result != DEFAULT_EXHAUST_MIN_PCT + 40.0
    # And the purge timer must never even have been armed by this tick.
    assert mock_coord._lights_off_purge_until is None


@pytest.mark.asyncio
async def test_leaving_drying_stage_clears_dwell_state(engine, mock_coord, frozen_now):
    """So a later drying cycle starts each timer fresh instead of inheriting
    a stale in-progress window from a past cycle."""
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord.stage_manager.current_stage = STAGE_PEAK_FLOWER
    mock_coord._drying_humidity_high_since = FIXED_NOW - timedelta(minutes=5)
    mock_coord._drying_cycle_phase_since = FIXED_NOW - timedelta(minutes=5)
    mock_coord.data = {NS_CLIMATE: {}}
    _wire_fan_entity(mock_coord)

    await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=24.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=True, thermal_runaway=False,
    )

    assert mock_coord._drying_humidity_high_since is None
    assert mock_coord._drying_cycle_phase_since is None


# ── Dedicated exhaust floor ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedicated_drying_floor_used_when_higher_than_grow_floor(engine, mock_coord, frozen_now):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord._config[CONF_DRYING_EXHAUST_MIN_PCT] = 35.0
    mock_coord._config[CONF_DRYING_AIRFLOW_MODE] = DRYING_AIRFLOW_CONSTANT
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    _wire_fan_entity(mock_coord)

    result = await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    assert result == 35.0


@pytest.mark.asyncio
async def test_default_dedicated_floor_used_when_not_configured(engine, mock_coord, frozen_now):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    _wire_fan_entity(mock_coord)

    result = await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    assert result == max(DRYING_CYCLE_EXHAUST_PCT, DEFAULT_DRYING_EXHAUST_MIN_PCT)
    assert DEFAULT_DRYING_EXHAUST_MIN_PCT > DEFAULT_EXHAUST_MIN_PCT  # higher than grow floor


# ── Per-tier gentle drying ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gentle_drying_applied_to_every_enabled_tier(engine, mock_coord, frozen_now):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    mock_coord._is_fan_tier_enabled = MagicMock(return_value=True)
    _wire_fan_entity(mock_coord)

    await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    called_tiers = {c.args[0] for c in mock_coord._apply_fan_speed_to_tier.call_args_list}
    assert called_tiers == {FAN_TIER_UPPER, FAN_TIER_MID, FAN_TIER_LOWER}


@pytest.mark.asyncio
async def test_gentle_drying_skips_disabled_tiers(engine, mock_coord, frozen_now):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    mock_coord._is_fan_tier_enabled = MagicMock(
        side_effect=lambda tier: tier == FAN_TIER_UPPER
    )
    _wire_fan_entity(mock_coord)

    await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    called_tiers = {c.args[0] for c in mock_coord._apply_fan_speed_to_tier.call_args_list}
    assert called_tiers == {FAN_TIER_UPPER}


# ── Humidity ceiling hard override ──────────────────────────────────────────

def test_humidity_ceiling_ignores_brief_spike(engine, mock_coord, monkeypatch):
    mock_coord._config[CONF_DRYING_HUMIDITY_CEILING_PCT] = 68.0
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 75.0}}
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)

    # First reading above ceiling — dwell timer starts, override not yet engaged.
    assert engine._check_drying_humidity_ceiling() is False
    assert mock_coord._drying_humidity_high_since == FIXED_NOW

    # A brief spike that clears before the dwell window elapses resets the timer.
    mock_coord.data[NS_CLIMATE]["upper_rh_pct"] = 60.0
    assert engine._check_drying_humidity_ceiling() is False
    assert mock_coord._drying_humidity_high_since is None


def test_humidity_ceiling_engages_after_sustained_dwell(engine, mock_coord, monkeypatch):
    mock_coord._config[CONF_DRYING_HUMIDITY_CEILING_PCT] = 68.0
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 75.0}}

    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    assert engine._check_drying_humidity_ceiling() is False  # dwell timer starts

    later = FIXED_NOW + timedelta(minutes=DRYING_HUMIDITY_CEILING_DWELL_MIN + 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: later)
    assert engine._check_drying_humidity_ceiling() is True


def test_humidity_ceiling_not_yet_engaged_before_dwell_elapses(engine, mock_coord, monkeypatch):
    mock_coord._config[CONF_DRYING_HUMIDITY_CEILING_PCT] = 68.0
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 75.0}}

    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    engine._check_drying_humidity_ceiling()

    almost = FIXED_NOW + timedelta(minutes=DRYING_HUMIDITY_CEILING_DWELL_MIN - 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: almost)
    assert engine._check_drying_humidity_ceiling() is False


@pytest.mark.asyncio
async def test_humidity_override_always_wins_over_cyclic_off_phase(engine, mock_coord, monkeypatch):
    """The override must force 100% even mid-cycle-off, same "always wins"
    guarantee as thermal runaway."""
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord._config[CONF_DRYING_AIRFLOW_MODE] = DRYING_AIRFLOW_CYCLIC
    mock_coord._config[CONF_DRYING_HUMIDITY_CEILING_PCT] = 68.0
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 80.0}}
    # Sustained override already engaged (dwell satisfied).
    mock_coord._drying_humidity_high_since = FIXED_NOW - timedelta(
        minutes=DRYING_HUMIDITY_CEILING_DWELL_MIN + 5
    )
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    # Force cyclic phase to "off" — override must still beat it.
    mock_coord._drying_cycle_is_on = False
    mock_coord._drying_cycle_phase_since = FIXED_NOW
    _wire_fan_entity(mock_coord)

    result = await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    assert result == 100.0
    assert mock_coord._drying_humidity_override_active is True
    mock_coord._notify_critical.assert_awaited_once()
    assert mock_coord._notify_critical.call_args.kwargs["level"] == "critical"


@pytest.mark.asyncio
async def test_humidity_override_alert_fires_once_per_episode(engine, mock_coord, monkeypatch):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord._config[CONF_DRYING_HUMIDITY_CEILING_PCT] = 68.0
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 80.0}}
    mock_coord._drying_humidity_high_since = FIXED_NOW - timedelta(
        minutes=DRYING_HUMIDITY_CEILING_DWELL_MIN + 5
    )
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    _wire_fan_entity(mock_coord)

    await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )
    await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    mock_coord._notify_critical.assert_awaited_once()


# ── Constant vs. Cyclic airflow mode ────────────────────────────────────────

@pytest.mark.asyncio
async def test_constant_mode_is_default_and_holds_steady_floor(engine, mock_coord, frozen_now):
    mock_coord._config[CONF_EXHAUST_FAN] = "fan.exhaust"
    mock_coord.stage_manager.current_stage = STAGE_DRYING
    mock_coord.data = {NS_CLIMATE: {"upper_rh_pct": 50.0}}
    _wire_fan_entity(mock_coord)
    # CONF_DRYING_AIRFLOW_MODE intentionally left unset — must default to
    # constant for backward compatibility.

    result = await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=20.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=False, thermal_runaway=False,
    )

    expected_floor = max(DRYING_CYCLE_EXHAUST_PCT, DEFAULT_DRYING_EXHAUST_MIN_PCT)
    assert result == expected_floor


def test_cyclic_mode_alternates_on_then_off(engine, mock_coord, monkeypatch):
    mock_coord._config[CONF_DRYING_CYCLE_ON_MIN] = 10.0
    mock_coord._config[CONF_DRYING_CYCLE_OFF_MIN] = 10.0
    floor_pct = 25.0

    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    assert engine._drying_cyclic_pct(floor_pct) == floor_pct  # phase starts "on"

    mid_on = FIXED_NOW + timedelta(minutes=5)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: mid_on)
    assert engine._drying_cyclic_pct(floor_pct) == floor_pct  # still within on-phase

    past_on = FIXED_NOW + timedelta(minutes=11)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: past_on)
    assert engine._drying_cyclic_pct(floor_pct) == 0.0  # flipped to off-phase

    past_off = past_on + timedelta(minutes=11)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: past_off)
    assert engine._drying_cyclic_pct(floor_pct) == floor_pct  # flipped back to on
