"""Tests for v1.4.1 Part 1: every Conditioning Room control decision must
be driven exclusively by its own dedicated sensor entities, never by an
actuator's own onboard/built-in temperature or humidity attribute (biased
by that actuator's own motor/compressor/electronics waste heat).

Each test constructs a scenario where an actuator's own onboard attribute
deliberately differs from the zone's dedicated sensor reading and confirms
the control decision follows the dedicated sensor.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.climate_engine import (
    ClimateEngine,
    HVAC_MODE_OFF,
    ZoneInterlock,
)
from custom_components.helix_cultivate.const import FOLLOW_ME_MIN_DELTA_C


@pytest.mark.asyncio
class Test1_1ReverseCycleUsesDeducatedSensor:
    async def test_control_zone_bang_bang_ignores_ac_own_attribute(self, engine, mock_coord):
        """The AC entity's own state reports a wildly different reading
        (15°C — would demand heat if read) than the dedicated sensor
        (30°C, passed as current_temp — should demand cool)."""
        ac_id = "climate.zone1_ac"

        def fake_states_get(entity_id):
            if entity_id == ac_id:
                return MagicMock(state="off", attributes={"current_temperature": 15.0, "hvac_modes": ["off", "heat", "cool"]})
            return None

        mock_coord.hass.states.get.side_effect = fake_states_get
        mock_coord.temp_setpoint = 24.0
        engine._call_service_with_retry = AsyncMock(return_value=True)
        zone = ZoneInterlock("zone1")

        await engine._control_zone(
            zone=zone, zone_label="zone1",
            current_temp=30.0,  # dedicated sensor — hot, should cool
            leaf_vpd=1.0, heater_id=None, ac_id=ac_id,
            humid_id=None, dehumid_id=None,
            is_reverse_cycle=True, enable_heat_cutoff=True,
        )

        assert zone.reverse_cycle_mode != "heat"


@pytest.mark.asyncio
class Test1_2FollowMeWiring:
    async def test_follow_me_called_with_dedicated_sensor_value(self, engine, mock_coord):
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0, current_temp=21.3
        )

        mock_coord.hass.services.async_call.assert_awaited_once_with(
            "midea_ac", "follow_me", {"entity_id": "climate.ac1", "temperature": 21.3}
        )

    async def test_follow_me_not_resent_below_meaningful_delta(self, engine, mock_coord):
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        mock_coord._follow_me_last_sent["climate.ac1"] = 21.3

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0,
            current_temp=21.3 + (FOLLOW_ME_MIN_DELTA_C / 2),
        )

        mock_coord.hass.services.async_call.assert_not_awaited()

    async def test_follow_me_resent_on_meaningful_change(self, engine, mock_coord):
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        mock_coord._follow_me_last_sent["climate.ac1"] = 21.3

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0,
            current_temp=21.3 + FOLLOW_ME_MIN_DELTA_C + 0.1,
        )

        mock_coord.hass.services.async_call.assert_awaited_once()

    async def test_follow_me_failure_is_quiet(self, engine, mock_coord):
        """A missing midea_ac.follow_me service (most installs) must never
        raise or otherwise disrupt the surrounding control tick."""
        state = MagicMock(state=HVAC_MODE_OFF, attributes={"hvac_modes": ["off", "heat_cool"]})
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)
        mock_coord.hass.services.async_call = AsyncMock(side_effect=Exception("unknown service"))

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0, current_temp=21.3
        )
        # No exception propagated — reaching this line is the assertion.

    async def test_follow_me_never_blocks_set_temperature_call(self, engine, mock_coord):
        """follow_me is independent of — never a substitute for —
        climate.set_temperature, which must still be called with the real
        target regardless of follow_me's outcome."""
        state = MagicMock(
            state=HVAC_MODE_OFF,
            attributes={"hvac_modes": ["off", "heat_cool"], "temperature": 20.0},
        )
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0, current_temp=21.3
        )

        calls = engine._call_service_with_retry.call_args_list
        assert any(
            c.args[:2] == ("climate", "set_temperature") and c.args[2]["temperature"] == 24.0
            for c in calls
        )

    async def test_current_temperature_attribute_never_read_for_control(self, engine, mock_coord):
        """Even with a wildly wrong current_temperature attribute on the
        entity, the actual target_temp used for set_temperature must be
        exactly what the caller (the dedicated sensor-derived
        effective_setpoint) passed in — never derived from the attribute."""
        state = MagicMock(
            state=HVAC_MODE_OFF,
            attributes={"hvac_modes": ["off", "heat_cool"], "current_temperature": 999.0},
        )
        mock_coord.hass.states.get = MagicMock(return_value=state)
        engine._call_service_with_retry = AsyncMock(return_value=True)

        await engine._set_reverse_cycle(
            "climate.ac1", None, role="zone1_ac", target_temp=24.0, current_temp=21.3
        )

        calls = engine._call_service_with_retry.call_args_list
        set_temp_calls = [c for c in calls if c.args[:2] == ("climate", "set_temperature")]
        assert len(set_temp_calls) == 1
        assert set_temp_calls[0].args[2]["temperature"] == 24.0


@pytest.mark.asyncio
class Test1_3DehumidifierUsesDedicatedVpdSignal:
    async def test_dehumidify_decision_ignores_dehumidifier_own_humidity_attribute(
        self, engine, mock_coord
    ):
        """want_dehumid derives purely from leaf_vpd (computed upstream
        from dedicated canopy sensors) — an AC-Infinity-style dehumidifier
        entity reporting its own onboard humidity trigger must have zero
        effect on the decision."""
        dehumid_id = "switch.zone1_dehumid"

        def fake_states_get(entity_id):
            if entity_id == dehumid_id:
                # Entity's own attribute claims very wet — would suggest
                # dehumidify is needed if (wrongly) consulted.
                return MagicMock(state="off", attributes={"current_humidity": 95.0})
            return None

        mock_coord.hass.states.get.side_effect = fake_states_get
        zone = ZoneInterlock("zone1")

        await engine._control_zone(
            zone=zone, zone_label="zone1",
            current_temp=24.0,
            leaf_vpd=1.0,  # inside VPD deadband -> no dehumidify demand
            heater_id=None, ac_id=None,
            humid_id=None, dehumid_id=dehumid_id,
        )

        assert zone.dehumid_on is False


@pytest.mark.asyncio
class Test1_4BackupHeaterUsesDedicatedSensor:
    async def test_backup_heater_gap_evaluated_from_dedicated_sensor_not_ac_attribute(
        self, mock_coord
    ):
        engine = ClimateEngine(mock_coord)
        ac_id = "climate.zone1_ac"

        def fake_states_get(entity_id):
            if entity_id == ac_id:
                # AC's own attribute claims comfortably at setpoint — the
                # dedicated sensor (passed explicitly below) says otherwise.
                return MagicMock(state="heat", attributes={"current_temperature": 24.0})
            return None

        mock_coord.hass.states.get.side_effect = fake_states_get
        engine._get = lambda key, default=None: {"zone1_backup_heater": "switch.backup"}.get(key, default)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()
        mock_coord.temp_setpoint = 24.0
        mock_coord._backup_heater_falling_behind_since = None

        from homeassistant.util import dt as dt_util
        from datetime import timedelta
        import custom_components.helix_cultivate.climate_engine as ce_module

        start = dt_util.utcnow()
        ce_module.dt_util.utcnow = lambda: start
        await engine._stage_backup_heater(
            current_temp=None, lung_temp=17.0, primary_heat_on=True, primary_rc_mode=None,
        )
        past_dwell = start + timedelta(minutes=11)
        ce_module.dt_util.utcnow = lambda: past_dwell
        result = await engine._stage_backup_heater(
            current_temp=None, lung_temp=17.0, primary_heat_on=True, primary_rc_mode=None,
        )

        assert result is True
        engine._set_switch.assert_awaited_with("switch.backup", True, role="zone1_backup_heater")
