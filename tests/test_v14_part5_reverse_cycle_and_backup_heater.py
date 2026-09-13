"""Tests for v1.4.0 Part 5: real thermostat-mode control for a Reverse
Cycle AirCon unit (climate.set_hvac_mode to heat_cool/auto + climate.
set_temperature, only when the entity's own reported hvac_modes actually
supports it — never assumed), and the backup heater's new sustained-dwell
trigger condition (previously instantaneous, so a brief demand blip could
stage it on immediately).
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.climate_engine import (
    BACKUP_HEATER_DWELL_MIN,
    HVAC_MODE_AUTO,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    ClimateEngine,
)
from homeassistant.util import dt as dt_util


def _make_engine(mock_coord):
    return ClimateEngine(mock_coord)


@pytest.mark.asyncio
class TestReverseCycleThermostatMode:
    async def test_uses_heat_cool_and_set_temperature_when_supported(self, mock_coord):
        engine = _make_engine(mock_coord)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", HVAC_MODE_HEAT, role="zone2_ac", target_temp=24.0)

        calls = engine._call_service_with_retry.call_args_list
        assert any(
            c.args[:2] == ("climate", "set_hvac_mode") and c.args[2]["hvac_mode"] == HVAC_MODE_HEAT_COOL
            for c in calls
        )
        assert any(
            c.args[:2] == ("climate", "set_temperature") and c.args[2]["temperature"] == 24.0
            for c in calls
        )

    async def test_falls_back_to_auto_mode_name_when_heat_cool_absent(self, mock_coord):
        engine = _make_engine(mock_coord)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "auto", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", HVAC_MODE_HEAT, role="zone2_ac", target_temp=24.0)

        calls = engine._call_service_with_retry.call_args_list
        assert any(
            c.args[:2] == ("climate", "set_hvac_mode") and c.args[2]["hvac_mode"] == HVAC_MODE_AUTO
            for c in calls
        )

    async def test_falls_back_to_discrete_mode_when_not_thermostat_capable(self, mock_coord):
        """Never assume — an entity that only reports heat/cool/off must
        keep using the existing discrete hvac_mode switching."""
        engine = _make_engine(mock_coord)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", HVAC_MODE_HEAT, role="zone2_ac", target_temp=24.0)

        calls = engine._call_service_with_retry.call_args_list
        assert calls == [
            (("climate", "set_hvac_mode", {"entity_id": "climate.ac1", "hvac_mode": HVAC_MODE_HEAT}),
             {"role": "zone2_ac"}),
        ]

    async def test_no_target_temp_preserves_original_discrete_behavior(self, mock_coord):
        """Toggle off (no target_temp passed at all) — behavior must be
        byte-for-byte unchanged from the pre-Part-5.3 implementation."""
        engine = _make_engine(mock_coord)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", HVAC_MODE_COOL, role="zone2_ac")

        engine._call_service_with_retry.assert_called_once_with(
            "climate", "set_hvac_mode",
            {"entity_id": "climate.ac1", "hvac_mode": HVAC_MODE_COOL},
            role="zone2_ac",
        )

    async def test_skips_set_temperature_when_already_at_target(self, mock_coord):
        engine = _make_engine(mock_coord)
        state = MagicMock(
            state=HVAC_MODE_HEAT_COOL,
            attributes={"hvac_modes": ["off", "heat_cool"], "temperature": 24.0},
        )
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", HVAC_MODE_HEAT, role="zone2_ac", target_temp=24.0)

        # Already in heat_cool at the right target — no service calls at all.
        engine._call_service_with_retry.assert_not_called()

    async def test_thermostat_capable_unit_left_running_when_no_demand(self, mock_coord):
        """A thermostat-capable unit must NOT be turned off when neither
        heat nor cool is currently wanted — it idles at its own setpoint
        internally, unlike a discrete on/off appliance."""
        engine = _make_engine(mock_coord)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle("climate.ac1", None, role="zone2_ac", target_temp=22.0)

        calls = engine._call_service_with_retry.call_args_list
        assert not any(c.args[2].get("hvac_mode") == HVAC_MODE_OFF for c in calls if len(c.args) > 2)
        assert any(c.args[:2] == ("climate", "set_hvac_mode") and c.args[2]["hvac_mode"] == HVAC_MODE_HEAT_COOL for c in calls)


@pytest.mark.asyncio
class TestControlReverseCycleBypassesDiscreteDispatchWhenThermostatCapable:
    async def test_thermostat_capable_short_circuits_before_anti_short_cycle_checks(self, mock_coord):
        engine = _make_engine(mock_coord)
        zone = MagicMock()
        zone.request_reverse_cycle_mode = MagicMock(side_effect=lambda m: m)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        engine._compressor_allowed = MagicMock(return_value=False)  # would block discrete dispatch

        result = await engine._control_reverse_cycle(
            zone=zone, zone_label="zone2", entity_id="climate.ac1",
            want_heat=True, want_cool=False, target_temp=23.5,
        )

        assert result == HVAC_MODE_HEAT_COOL
        zone.request_reverse_cycle_mode.assert_called_once_with(HVAC_MODE_HEAT_COOL)
        # Anti-short-cycle gating was never even consulted for the
        # thermostat-mode path — it exists specifically for discrete flips.
        engine._compressor_allowed.assert_not_called()


@pytest.mark.asyncio
class TestBackupHeaterDwellTimer:
    def _make_engine_for_backup(self, mock_coord):
        engine = ClimateEngine(mock_coord)
        engine._get = lambda key, default=None: {"zone1_backup_heater": "switch.backup"}.get(key, default)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()
        mock_coord.temp_setpoint = 24.0
        mock_coord._backup_heater_falling_behind_since = None
        return engine

    async def test_does_not_engage_immediately_on_first_falling_behind_tick(self, mock_coord, monkeypatch):
        engine = self._make_engine_for_backup(mock_coord)
        fixed_now = dt_util.utcnow()
        import custom_components.helix_cultivate.climate_engine as ce_module
        monkeypatch.setattr(ce_module.dt_util, "utcnow", lambda: fixed_now)

        result = await engine._stage_backup_heater(
            current_temp=None, lung_temp=18.0, primary_heat_on=True, primary_rc_mode=None,
        )

        assert result is False
        engine._set_switch.assert_awaited_with("switch.backup", False, role="zone1_backup_heater")
        assert mock_coord._backup_heater_falling_behind_since == fixed_now

    async def test_engages_after_sustained_dwell(self, mock_coord, monkeypatch):
        engine = self._make_engine_for_backup(mock_coord)
        import custom_components.helix_cultivate.climate_engine as ce_module

        start = dt_util.utcnow()
        monkeypatch.setattr(ce_module.dt_util, "utcnow", lambda: start)
        await engine._stage_backup_heater(None, 18.0, True, None)

        past_dwell = start + timedelta(minutes=BACKUP_HEATER_DWELL_MIN + 1)
        monkeypatch.setattr(ce_module.dt_util, "utcnow", lambda: past_dwell)
        result = await engine._stage_backup_heater(None, 18.0, True, None)

        assert result is True
        engine._set_switch.assert_awaited_with("switch.backup", True, role="zone1_backup_heater")

    async def test_dwell_resets_when_condition_clears(self, mock_coord, monkeypatch):
        engine = self._make_engine_for_backup(mock_coord)
        import custom_components.helix_cultivate.climate_engine as ce_module

        start = dt_util.utcnow()
        monkeypatch.setattr(ce_module.dt_util, "utcnow", lambda: start)
        await engine._stage_backup_heater(None, 18.0, True, None)
        assert mock_coord._backup_heater_falling_behind_since is not None

        # Primary heat source catches up — condition clears.
        await engine._stage_backup_heater(None, 23.9, True, None)
        assert mock_coord._backup_heater_falling_behind_since is None

    async def test_outdoor_temperature_floor_still_gates_immediately(self, mock_coord):
        """The outdoor-temp confirming floor is independent of the dwell
        timer — mild outdoor conditions veto the backup heater outright,
        no dwell needed either way."""
        engine = self._make_engine_for_backup(mock_coord)
        engine._outdoor_temp_c = MagicMock(return_value=15.0)  # above threshold

        result = await engine._stage_backup_heater(None, 18.0, True, None)

        assert result is False
        assert mock_coord._backup_heater_falling_behind_since is None
