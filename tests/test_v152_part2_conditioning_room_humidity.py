"""Tests for v1.5.2 Part 2: Conditioning Room now has a genuine, adjustable
Humidity Setpoint (CONF_ZONE1_RH_SETPOINT), and its dehumidifier/humidifier
decision is driven exclusively by its own dedicated RH sensor against that
setpoint — never by Primary Grow Space's leaf_vpd, which the shared
_control_zone()/_bang_bang_vpd() path previously used for both zones.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.climate_engine import ZoneInterlock
from custom_components.helix_cultivate.const import ZONE1_RH_DEADBAND_PCT


class TestBangBangRh:
    def test_none_when_reading_missing(self, engine):
        assert engine._bang_bang_rh(None, 55.0) == (False, False)

    def test_wants_dehumidify_above_deadband(self, engine):
        result = engine._bang_bang_rh(55.0 + ZONE1_RH_DEADBAND_PCT + 1, 55.0)
        assert result == (False, True)

    def test_wants_humidify_below_deadband(self, engine):
        result = engine._bang_bang_rh(55.0 - ZONE1_RH_DEADBAND_PCT - 1, 55.0)
        assert result == (True, False)

    def test_no_action_within_deadband(self, engine):
        assert engine._bang_bang_rh(55.0, 55.0) == (False, False)
        assert engine._bang_bang_rh(55.0 + ZONE1_RH_DEADBAND_PCT, 55.0) == (False, False)
        assert engine._bang_bang_rh(55.0 - ZONE1_RH_DEADBAND_PCT, 55.0) == (False, False)


@pytest.mark.asyncio
class TestControlZoneHumidityDemandOverride:
    async def test_humidity_demand_overrides_leaf_vpd_driven_bang_bang(self, engine, mock_coord):
        """The actual proof this fix requires: leaf_vpd alone would want
        dehumidify (VPD very low = air too wet), but an explicit
        humidity_demand of (want_humid=True, want_dehumid=False) — as
        Conditioning Room's own _bang_bang_rh would produce from its own
        dedicated RH sensor — must be what the zone actually does."""
        mock_coord.temp_setpoint = 24.0
        mock_coord.hass.states.get = MagicMock(return_value=None)

        zone = ZoneInterlock("zone1")
        humid_id = "switch.zone1_humid"
        dehumid_id = "switch.zone1_dehumid"

        await engine._control_zone(
            zone=zone,
            zone_label="zone1",
            current_temp=24.0,
            leaf_vpd=0.3,  # very low VPD -> _bang_bang_vpd alone would dehumidify
            heater_id=None,
            ac_id=None,
            humid_id=humid_id,
            dehumid_id=dehumid_id,
            humidity_demand=(True, False),  # Conditioning Room's own RH says humidify
        )

        assert zone.humid_on is True
        assert zone.dehumid_on is False

    async def test_zone2_still_uses_leaf_vpd_when_no_humidity_demand_supplied(self, engine, mock_coord):
        """Confirms Part 2's explicit requirement that Zone 2 is unaffected
        — omitting humidity_demand (as Zone 2's real call site does) keeps
        the original leaf_vpd-driven decision."""
        mock_coord.temp_setpoint = 24.0
        mock_coord.hass.states.get = MagicMock(return_value=None)

        zone = ZoneInterlock("zone2")
        humid_id = "switch.zone2_humid"
        dehumid_id = "switch.zone2_dehumid"

        await engine._control_zone(
            zone=zone,
            zone_label="zone2",
            current_temp=24.0,
            leaf_vpd=0.3,  # very low VPD -> too wet -> dehumidify
            heater_id=None,
            ac_id=None,
            humid_id=humid_id,
            dehumid_id=dehumid_id,
            # humidity_demand intentionally omitted
        )

        assert zone.dehumid_on is True
        assert zone.humid_on is False

    async def test_opposite_signals_scenario_zone1_follows_its_own_rh_not_tent_vpd(
        self, engine, mock_coord
    ):
        """Direct scenario from the ticket: Primary Grow Space's leaf_vpd
        and Conditioning Room's own dedicated RH disagree — Conditioning
        Room must follow its own reading."""
        mock_coord.temp_setpoint = 24.0
        mock_coord.hass.states.get = MagicMock(return_value=None)

        # Tent's own VPD says "too dry, air needs humidifying" —
        leaf_vpd_says_humidify = 2.0  # very high VPD -> _bang_bang_vpd would humidify
        # ...but Conditioning Room's own dedicated RH sensor is well above
        # its own setpoint, genuinely needing dehumidification.
        lung_rh = 75.0
        zone1_rh_setpoint = 55.0
        humidity_demand = engine._bang_bang_rh(lung_rh, zone1_rh_setpoint)
        assert humidity_demand == (False, True)  # sanity-check the fixture itself

        zone = ZoneInterlock("zone1")
        await engine._control_zone(
            zone=zone,
            zone_label="zone1",
            current_temp=24.0,
            leaf_vpd=leaf_vpd_says_humidify,
            heater_id=None,
            ac_id=None,
            humid_id="switch.zone1_humid",
            dehumid_id="switch.zone1_dehumid",
            humidity_demand=humidity_demand,
        )

        # Conditioning Room dehumidifies (its own real need), not
        # humidifies (what the tent's VPD alone would have produced).
        assert zone.dehumid_on is True
        assert zone.humid_on is False
