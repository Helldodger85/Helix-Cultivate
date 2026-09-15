"""Tests for Part 3.3 — dew point / condensation prediction: a hard
"always wins" override forcing exhaust + lung-room heat on when the gap
between leaf temperature and the calculated dew point narrows below
CONF_DEW_POINT_MARGIN_C for a sustained dwell, and NOT firing on a brief,
non-sustained narrowing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate.climate_engine as climate_engine_module
from custom_components.helix_cultivate.const import (
    CONF_HEATER_CUTOFF_C,
    CONF_ZONE1_AC,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE1_REVERSE_CYCLE,
    DEW_POINT_OVERRIDE_DWELL_MIN,
)

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def _wire_heater_entity(mock_coord, entity_id="switch.zone1_heater"):
    mock_coord.hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(state="off") if eid == entity_id else None
    )


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: FIXED_NOW)
    return FIXED_NOW


@pytest.mark.asyncio
async def test_no_risk_when_gap_comfortable(engine, mock_coord):
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=18.0)  # leaf 21.5, gap 3.5 >= 2.0
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False

    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is False
    assert mock_coord._dew_point_risk_since is None


@pytest.mark.asyncio
async def test_narrow_gap_starts_dwell_without_engaging_yet(engine, mock_coord):
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)  # leaf 21.5, gap 1.5 < 2.0
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    _wire_heater_entity(mock_coord)

    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is False
    assert mock_coord._dew_point_risk_since == FIXED_NOW
    mock_coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_brief_narrowing_does_not_engage_override(engine, mock_coord, monkeypatch):
    """Gap narrows, then clears before the dwell elapses — must not fire."""
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    _wire_heater_entity(mock_coord)

    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)  # narrow: gap 1.5
    await engine._handle_dew_point_risk(24.0, 60.0)
    assert mock_coord._dew_point_risk_since == FIXED_NOW

    # Clears before dwell elapses.
    brief_later = FIXED_NOW + timedelta(minutes=DEW_POINT_OVERRIDE_DWELL_MIN - 2)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: brief_later)
    mock_coord._calc_dew_point_c = MagicMock(return_value=18.0)  # comfortable again: gap 3.5
    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is False
    assert mock_coord._dew_point_risk_since is None
    mock_coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_sustained_narrow_gap_engages_hard_override(engine, mock_coord, monkeypatch):
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)  # gap 1.5 < 2.0 margin
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    mock_coord._config[CONF_ZONE1_HEATER] = "switch.zone1_heater"
    _wire_heater_entity(mock_coord)

    await engine._handle_dew_point_risk(24.0, 60.0)  # starts dwell

    sustained = FIXED_NOW + timedelta(minutes=DEW_POINT_OVERRIDE_DWELL_MIN + 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: sustained)
    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is True
    mock_coord.hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {"entity_id": "switch.zone1_heater"}
    )
    mock_coord._notify_critical.assert_awaited_once()
    assert mock_coord._notify_critical.call_args.kwargs["level"] == "critical"
    assert mock_coord._dew_point_alerted is True


@pytest.mark.asyncio
async def test_reverse_cycle_zone1_heats_via_hvac_mode(engine, mock_coord, monkeypatch):
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    mock_coord._config[CONF_ZONE1_IS_REVERSE_CYCLE] = True
    mock_coord._config[CONF_ZONE1_REVERSE_CYCLE] = "climate.zone1_hp"
    mock_coord.hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(state="cool") if eid == "climate.zone1_hp" else None
    )

    await engine._handle_dew_point_risk(24.0, 60.0)
    sustained = FIXED_NOW + timedelta(minutes=DEW_POINT_OVERRIDE_DWELL_MIN + 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: sustained)
    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is True
    mock_coord.hass.services.async_call.assert_awaited_once_with(
        "climate", "set_hvac_mode", {"entity_id": "climate.zone1_hp", "hvac_mode": "heat"}
    )


@pytest.mark.asyncio
async def test_alert_fires_once_per_episode(engine, mock_coord, monkeypatch):
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    mock_coord._config[CONF_ZONE1_HEATER] = "switch.zone1_heater"
    _wire_heater_entity(mock_coord)

    await engine._handle_dew_point_risk(24.0, 60.0)
    sustained = FIXED_NOW + timedelta(minutes=DEW_POINT_OVERRIDE_DWELL_MIN + 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: sustained)
    await engine._handle_dew_point_risk(24.0, 60.0)
    await engine._handle_dew_point_risk(24.0, 60.0)

    mock_coord._notify_critical.assert_awaited_once()


@pytest.mark.asyncio
async def test_exhaust_forced_100_when_dew_point_risk_true(engine, mock_coord):
    """_control_exhaust must treat dew_point_risk with the same "always
    wins" precedence tier as thermal_runaway."""
    mock_coord.hass.states.get = MagicMock(return_value=MagicMock(state="on"))

    result = await engine._control_exhaust(
        leaf_vpd=1.0, canopy_temp=24.0, upper_enthalpy=None, lung_enthalpy=None,
        sensor_dropout=False, lights_on=True, thermal_runaway=False, dew_point_risk=True,
    )

    assert result == 100.0


@pytest.mark.asyncio
async def test_zone1_heater_cutoff_does_not_undo_dew_point_override(engine, mock_coord, monkeypatch):
    """Regression coverage for a real conflict found while wiring this in:
    _check_zone1_heater_cutoff runs on canopy_temp (Zone 2) right after the
    dew point check and would otherwise immediately kill the Zone 1 heater
    _handle_dew_point_risk just forced on, if canopy_temp also happens to
    be over the (unrelated) heater cutoff threshold — defeating "always
    wins" the same tick it was supposed to engage. run() must skip the
    cutoff check while dew_point_risk is active, mirroring the guard it
    already has around the normal zone1 bang-bang control.

    Drives both real methods in the exact sequence run() uses (dew point
    check, producing a real dew_point_risk value, then the cutoff check
    gated on it) rather than re-asserting the guard in the test itself.
    """
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    # canopy_temp (used as both upper_temp and heater-cutoff input) is 27.0
    # below -> leaf 24.5; dew point 23.0 -> gap 1.5, narrower than the 2.0
    # default margin.
    mock_coord._calc_dew_point_c = MagicMock(return_value=23.0)
    mock_coord._dew_point_risk_since = FIXED_NOW - timedelta(
        minutes=DEW_POINT_OVERRIDE_DWELL_MIN + 1
    )
    mock_coord._dew_point_alerted = False
    mock_coord._config[CONF_HEATER_CUTOFF_C] = 26.0
    mock_coord._config[CONF_ZONE1_HEATER] = "switch.zone1_heater"
    _wire_heater_entity(mock_coord)

    canopy_temp = 27.0  # over the 26°C heater cutoff
    dew_point_risk = await engine._handle_dew_point_risk(canopy_temp, 60.0)
    assert dew_point_risk is True
    mock_coord.hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {"entity_id": "switch.zone1_heater"}
    )

    # run()'s guard: skip the cutoff check entirely while dew_point_risk is
    # active, so it can't immediately undo the call just made above.
    if not dew_point_risk:
        await engine._check_zone1_heater_cutoff(canopy_temp)

    # Still exactly the one "turn_on" call from the override — no follow-up
    # "turn_off" from the cutoff undoing it.
    mock_coord.hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {"entity_id": "switch.zone1_heater"}
    )


@pytest.mark.asyncio
async def test_sustained_override_also_turns_off_stale_ac(engine, mock_coord, monkeypatch):
    """Regression test: Zone 1's AC can legitimately already be running when
    a dew point risk develops (Zone 1 was simply too warm a moment ago).
    run() skips Zone 1's normal _control_zone bang-bang entirely while the
    override is active (see _handle_dew_point_risk's docstring) — that is
    also the only code path that would otherwise turn the AC off, so
    without an explicit AC-off here the heater this override forces on
    would run alongside a stale, still-on AC indefinitely, until whenever
    _control_zone next happens to resume. The override must turn the AC
    off itself.
    """
    mock_coord.effective_leaf_temp_offset_c = MagicMock(return_value=-2.5)
    mock_coord._calc_dew_point_c = MagicMock(return_value=20.0)  # gap 1.5 < 2.0 margin
    mock_coord._dew_point_risk_since = None
    mock_coord._dew_point_alerted = False
    mock_coord._config[CONF_ZONE1_HEATER] = "switch.zone1_heater"
    mock_coord._config[CONF_ZONE1_AC] = "switch.zone1_ac"
    mock_coord.hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(state="off") if eid == "switch.zone1_heater"
        else MagicMock(state="on") if eid == "switch.zone1_ac"
        else None
    )

    await engine._handle_dew_point_risk(24.0, 60.0)  # starts dwell

    sustained = FIXED_NOW + timedelta(minutes=DEW_POINT_OVERRIDE_DWELL_MIN + 1)
    monkeypatch.setattr(climate_engine_module.dt_util, "utcnow", lambda: sustained)
    risk = await engine._handle_dew_point_risk(24.0, 60.0)

    assert risk is True
    calls = mock_coord.hass.services.async_call.await_args_list
    assert (
        "switch", "turn_off", {"entity_id": "switch.zone1_ac"}
    ) in [(c.args[0], c.args[1], c.args[2]) for c in calls]
    assert (
        "switch", "turn_on", {"entity_id": "switch.zone1_heater"}
    ) in [(c.args[0], c.args[1], c.args[2]) for c in calls]
    # AC must be turned off before (or at worst alongside) the heater turning
    # on — never only after, which would still allow one control tick with
    # both running.
    ac_off_index = next(i for i, c in enumerate(calls) if c.args[:2] == ("switch", "turn_off"))
    heater_on_index = next(i for i, c in enumerate(calls) if c.args[:2] == ("switch", "turn_on"))
    assert ac_off_index < heater_on_index
