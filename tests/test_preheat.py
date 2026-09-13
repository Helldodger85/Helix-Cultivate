"""Tests for Part 3.4 — predictive pre-heating: biasing Zone 1's effective
setpoint upward starting CONF_PREHEAT_LEAD_MIN before the scheduled
lights-off transition, computed from the known light schedule rather than
reactively waiting for temperature to actually start falling.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_AF_LIGHT_HOURS,
    CONF_AF_LIGHTS_ON_TIME,
    CONF_GROWTH_MODE,
    CONF_PREHEAT_LEAD_MIN,
    GROWTH_MODE_AUTOFLOWER,
    PREHEAT_BIAS_C,
    STAGE_EARLY_VEG,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_light_sched_coord(monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: FIXED_NOW)

    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_EARLY_VEG
    coord._light_schedule_params = lambda: HelixCoordinator._light_schedule_params(coord)
    coord._light_schedule_params_for_stage = lambda stage: HelixCoordinator._light_schedule_params_for_stage(coord, stage)
    coord._minutes_until_lights_off = lambda: HelixCoordinator._minutes_until_lights_off(coord)
    return coord


def test_minutes_until_lights_off_within_same_day(fake_light_sched_coord):
    c = fake_light_sched_coord
    c._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    c._config[CONF_AF_LIGHT_HOURS] = 18.0
    c._config[CONF_AF_LIGHTS_ON_TIME] = "06:00"  # off at 24:00 -> 00:00 next day

    # FIXED_NOW is 12:00 -> off at 00:00 -> 12 hours away.
    assert c._minutes_until_lights_off() == pytest.approx(12 * 60)


def test_minutes_until_lights_off_wraps_past_midnight(fake_light_sched_coord):
    c = fake_light_sched_coord
    c._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    c._config[CONF_AF_LIGHT_HOURS] = 6.0
    c._config[CONF_AF_LIGHTS_ON_TIME] = "10:00"  # off at 16:00 today

    # FIXED_NOW is 12:00 -> off at 16:00 -> 4 hours away.
    assert c._minutes_until_lights_off() == pytest.approx(4 * 60)


def test_minutes_until_lights_off_none_when_always_on(fake_light_sched_coord):
    c = fake_light_sched_coord
    c._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    c._config[CONF_AF_LIGHT_HOURS] = 24.0
    c._config[CONF_AF_LIGHTS_ON_TIME] = "06:00"

    assert c._minutes_until_lights_off() is None


def test_minutes_until_lights_off_none_when_never_on(fake_light_sched_coord):
    c = fake_light_sched_coord
    c._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
    c._config[CONF_AF_LIGHT_HOURS] = 0.0
    c._config[CONF_AF_LIGHTS_ON_TIME] = "06:00"

    assert c._minutes_until_lights_off() is None


def test_no_bias_outside_lead_window(engine, mock_coord):
    mock_coord._minutes_until_lights_off = MagicMock(return_value=45.0)

    assert engine._preheat_bias_c() == 0.0


def test_bias_applied_at_exact_lead_time(engine, mock_coord):
    mock_coord._minutes_until_lights_off = MagicMock(return_value=15.0)  # default lead

    assert engine._preheat_bias_c() == PREHEAT_BIAS_C


def test_bias_applied_inside_lead_window(engine, mock_coord):
    mock_coord._minutes_until_lights_off = MagicMock(return_value=5.0)

    assert engine._preheat_bias_c() == PREHEAT_BIAS_C


def test_custom_lead_time_respected(engine, mock_coord):
    mock_coord._config[CONF_PREHEAT_LEAD_MIN] = 30.0
    mock_coord._minutes_until_lights_off = MagicMock(return_value=25.0)

    assert engine._preheat_bias_c() == PREHEAT_BIAS_C


def test_no_bias_when_preheat_disabled(engine, mock_coord):
    mock_coord._config[CONF_PREHEAT_LEAD_MIN] = 0.0
    mock_coord._minutes_until_lights_off = MagicMock(return_value=1.0)

    assert engine._preheat_bias_c() == 0.0


def test_no_bias_when_no_scheduled_off_transition(engine, mock_coord):
    """Light never on, or always on — _minutes_until_lights_off returns None."""
    mock_coord._minutes_until_lights_off = MagicMock(return_value=None)

    assert engine._preheat_bias_c() == 0.0


@pytest.mark.asyncio
async def test_control_zone_effective_setpoint_includes_preheat_bias(engine, mock_coord):
    """The bias must actually reach _control_zone's effective_setpoint
    calculation via extra_setpoint_bias_c, on top of the existing VPD-assist
    bias — not a separate, parallel override path."""
    from custom_components.helix_cultivate.climate_engine import ZoneInterlock

    mock_coord.temp_setpoint = 20.0
    mock_coord.hass.states.get = MagicMock(return_value=None)  # no appliances mapped
    zone = ZoneInterlock("test-zone")

    # current_temp comfortably above the plain 20.0 setpoint but BELOW the
    # preheat-biased 22.0 (20.0 + PREHEAT_BIAS_C=2.0) — only with the bias
    # applied should heat demand turn on.
    await engine._control_zone(
        zone=zone,
        zone_label="zone1",
        current_temp=21.0,
        leaf_vpd=None,
        heater_id="switch.zone1_heater",
        ac_id=None,
        humid_id=None,
        dehumid_id=None,
        extra_setpoint_bias_c=PREHEAT_BIAS_C,
    )

    assert zone.heater_on is True
