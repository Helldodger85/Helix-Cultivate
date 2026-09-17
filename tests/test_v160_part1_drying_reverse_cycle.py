"""Tests for v1.6.0 Part 1: Drying Room's Reverse Cycle upgrade, mirroring
what Conditioning Room and Primary Grow Space already have —

1.1: real thermostat control (climate.set_hvac_mode to heat_cool/auto +
     climate.set_temperature) via the existing _set_reverse_cycle machinery,
     with the original discrete on/off fallback left unchanged when the RC
     toggle is off.
1.2: midea_ac.follow_me wired the same way, fed Drying's own dedicated
     sensor reading (drying_temp) — never an actuator's own attribute.
1.3: Backup Heater staging (previously nonexistent for Drying) driven
     exclusively by Drying's own dedicated sensor, matching the same
     instantaneous check Zone 1/Zone 2 already use in their own
     is_reverse_cycle path.

Before this change, _control_drying_zone never passed target_temp to
_set_reverse_cycle at all, so it always fell back to discrete dispatch
(no thermostat mode, no follow_me) and never staged a backup heater.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.climate_engine import (
    HVAC_MODE_HEAT,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    ClimateEngine,
)


def _make_engine(mock_coord, *, is_rc: bool, ac_id="climate.drying_ac", heater_id="switch.drying_heater"):
    mock_coord._config.update({
        "drying_ac": ac_id,
        "drying_heater": heater_id,
        "drying_is_reverse_cycle": is_rc,
    })
    return ClimateEngine(mock_coord)


@pytest.mark.asyncio
class TestDryingReverseCycleThermostatMode:
    async def test_thermostat_capable_unit_gets_heat_cool_and_set_temperature(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        # drying_temp well below the 15.5C fixed target -> want_heat
        await engine._control_drying_zone(drying_temp=10.0, drying_rh=60.0)

        calls = engine._call_service_with_retry.call_args_list
        assert any(
            c.args[:2] == ("climate", "set_hvac_mode") and c.args[2]["hvac_mode"] == HVAC_MODE_HEAT_COOL
            for c in calls
        )
        assert any(
            c.args[:2] == ("climate", "set_temperature") and c.args[2]["temperature"] == pytest.approx(15.5)
            for c in calls
        )

    async def test_non_thermostat_capable_unit_falls_back_to_discrete_dispatch(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat", "cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._control_drying_zone(drying_temp=10.0, drying_rh=60.0)

        calls = engine._call_service_with_retry.call_args_list
        assert any(
            c.args[:2] == ("climate", "set_hvac_mode") and c.args[2]["hvac_mode"] == HVAC_MODE_HEAT
            for c in calls
        )
        assert not any(c.args[:2] == ("climate", "set_temperature") for c in calls)

    async def test_rc_toggle_off_uses_unchanged_discrete_switch_dispatch(self, mock_coord):
        """Bang-bang path is untouched when the RC toggle itself is off —
        never routed through _set_reverse_cycle's thermostat logic at all."""
        engine = _make_engine(mock_coord, is_rc=False)
        engine._set_switch = AsyncMock()
        engine._set_reverse_cycle = AsyncMock()

        await engine._control_drying_zone(drying_temp=10.0, drying_rh=60.0)

        engine._set_reverse_cycle.assert_not_called()
        engine._set_switch.assert_any_await("switch.drying_heater", True, role="drying_heater")
        engine._set_switch.assert_any_await("climate.drying_ac", False, role="drying_ac")


@pytest.mark.asyncio
class TestDryingFollowMeWiring:
    async def test_follow_me_fed_dryings_own_dedicated_sensor(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._control_drying_zone(drying_temp=11.25, drying_rh=60.0)

        mock_coord.hass.services.async_call.assert_awaited_once_with(
            "midea_ac", "follow_me",
            {"entity_id": "climate.drying_ac", "temperature": 11.25},
        )

    async def test_follow_me_silently_no_ops_when_service_missing(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        mock_coord.hass.services.async_call = AsyncMock(side_effect=Exception("no such service"))

        # Must not raise.
        await engine._control_drying_zone(drying_temp=11.25, drying_rh=60.0)


@pytest.mark.asyncio
class TestDryingBackupHeaterStaging:
    def _thermostat_state(self):
        return MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})

    async def test_stages_on_when_cold_outdoors_and_falling_behind(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        mock_coord.hass.states.get = MagicMock(return_value=self._thermostat_state())
        engine._call_service_with_retry = AsyncMock(return_value=True)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()

        # Fixed drying target is 15.5C; well below target + cold outside.
        await engine._control_drying_zone(drying_temp=5.0, drying_rh=60.0)

        engine._set_switch.assert_any_await("switch.drying_heater", True, role="drying_backup_heater")

    async def test_does_not_stage_when_outdoor_temp_above_threshold(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        mock_coord.hass.states.get = MagicMock(return_value=self._thermostat_state())
        engine._call_service_with_retry = AsyncMock(return_value=True)
        engine._outdoor_temp_c = MagicMock(return_value=15.0)  # mild outdoors
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()

        await engine._control_drying_zone(drying_temp=5.0, drying_rh=60.0)

        engine._set_switch.assert_any_await("switch.drying_heater", False, role="drying_backup_heater")

    async def test_does_not_stage_when_not_actually_falling_behind(self, mock_coord):
        engine = _make_engine(mock_coord, is_rc=True)
        mock_coord.hass.states.get = MagicMock(return_value=self._thermostat_state())
        engine._call_service_with_retry = AsyncMock(return_value=True)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()

        # Right at the fixed 15.5C target -> not falling behind.
        await engine._control_drying_zone(drying_temp=15.5, drying_rh=60.0)

        engine._set_switch.assert_any_await("switch.drying_heater", False, role="drying_backup_heater")

    async def test_never_staged_when_rc_toggle_off(self, mock_coord):
        """No backup-heater concept at all outside the RC path — matches
        Zone 1/Zone 2, where only the RC branch has this staging block."""
        engine = _make_engine(mock_coord, is_rc=False)
        engine._set_switch = AsyncMock()
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)

        await engine._control_drying_zone(drying_temp=5.0, drying_rh=60.0)

        roles = [c.kwargs.get("role") for c in engine._set_switch.await_args_list]
        assert "drying_backup_heater" not in roles

    async def test_uses_dryings_own_sensor_never_actuator_attribute(self, mock_coord):
        """The AC's own onboard current_temperature attribute must never be
        consulted for the backup-heater decision — only drying_temp."""
        engine = _make_engine(mock_coord, is_rc=True)
        # Actuator reports a warm onboard reading that would NOT trigger the
        # backup heater if it were (wrongly) consulted instead of drying_temp.
        state = MagicMock(
            state=HVAC_MODE_OFF,
            attributes={"hvac_modes": ["off", "heat_cool"], "current_temperature": 20.0},
        )
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()

        # Drying's own dedicated sensor says it's cold -> must still stage on.
        await engine._control_drying_zone(drying_temp=5.0, drying_rh=60.0)

        engine._set_switch.assert_any_await("switch.drying_heater", True, role="drying_backup_heater")
