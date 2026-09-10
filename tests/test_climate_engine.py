"""Minimal safety-critical test coverage for ClimateEngine (Phase 12C).

Pure-Python unit tests — no running Home Assistant instance required. The
`engine` / `mock_coord` fixtures (see conftest.py) stand in for a real
HelixCoordinator via unittest.mock, with explicit attribute stubs covering
exactly the surface area these methods touch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate.climate_engine import (
    THERMAL_PURGE_MARGIN_C,
    VPD_ASSIST_STEP_C,
)


# ── _bang_bang_vpd ──────────────────────────────────────────────────────────

def test_bang_bang_vpd_in_range(engine):
    """VPD comfortably inside [vpd_target_min, vpd_target_max] → no action."""
    # mock_coord.vpd_target_min/max = 0.8 / 1.2
    want_humidify, want_dehumidify = engine._bang_bang_vpd(1.0)
    assert want_humidify is False
    assert want_dehumidify is False


def test_bang_bang_vpd_above_max(engine):
    """VPD above vpd_target_max (air too dry) → the engine requests humidify.

    `_bang_bang_vpd()` returns `(want_humidify, want_dehumidify)`. When the
    leaf VPD reading exceeds the upper bound, the air is too dry, so the
    correct actuator response is to *humidify* (raise RH, which lowers VPD).
    """
    want_humidify, want_dehumidify = engine._bang_bang_vpd(1.5)  # > vpd_target_max (1.2)
    assert want_humidify is True
    assert want_dehumidify is False


def test_bang_bang_vpd_below_min(engine):
    """VPD below vpd_target_min (air too wet) → the engine requests dehumidify."""
    want_humidify, want_dehumidify = engine._bang_bang_vpd(0.5)  # < vpd_target_min (0.8)
    assert want_humidify is False
    assert want_dehumidify is True


# ── _vpd_trend ──────────────────────────────────────────────────────────────

def test_vpd_trend_positive_slope(engine, mock_coord):
    """A monotonically increasing VPD series yields a positive OLS slope."""
    t0 = datetime.now(timezone.utc)
    readings = [0.80, 0.90, 1.00, 1.10]
    for i, vpd in enumerate(readings):
        mock_coord._vpd_history.append((t0 + timedelta(seconds=30 * i), vpd))

    slope, projected = engine._vpd_trend()

    assert slope is not None
    assert slope > 0.0
    assert projected is not None
    assert projected > readings[-1]


def test_vpd_trend_insufficient_samples(engine, mock_coord):
    """Fewer than 3 samples in the history deque → (None, None)."""
    t0 = datetime.now(timezone.utc)
    mock_coord._vpd_history.append((t0, 1.0))
    mock_coord._vpd_history.append((t0 + timedelta(seconds=30), 1.05))

    slope, projected = engine._vpd_trend()

    assert slope is None
    assert projected is None


# ── _vpd_assist_bias ─────────────────────────────────────────────────────────

def test_vpd_assist_bias_stateless(engine, monkeypatch):
    """Returns the identical bias for identical inputs regardless of call
    order or how many times it has already been invoked this tick — the
    method holds no internal state of its own (Phase 9C design constraint).
    """
    # Force the humidifier to appear saturated; VPD is above vpd_target_max
    # (1.2, air too dry). The humidifier is the appliance that would be
    # running to correct that, so a saturated humidifier means temp must be
    # nudged DOWN (-VPD_ASSIST_STEP_C) to raise RH / lower VPD instead.
    monkeypatch.setattr(
        engine,
        "_is_saturated",
        lambda zone_label, appliance: appliance == "humidifier",
    )

    leaf_vpd = 1.5  # > vpd_target_max
    first = engine._vpd_assist_bias("zone2", leaf_vpd)
    second = engine._vpd_assist_bias("zone2", leaf_vpd)
    third = engine._vpd_assist_bias("zone2", leaf_vpd)

    assert first == second == third == pytest.approx(-VPD_ASSIST_STEP_C)


# ── _vpd_assist_bias against real _is_saturated (regression for the swapped-
#    appliance-check bug: the code once checked humidifier saturation on the
#    "too wet" branch and dehumidifier saturation on the "too dry" branch) ───

def test_vpd_assist_bias_saturated_dehumidifier_at_low_vpd(engine, mock_coord):
    """A genuinely saturated dehumidifier (10+ min continuous runtime, VPD
    trend flat/not improving) with VPD stuck below vpd_target_min (too wet)
    must nudge temp UP to help raise VPD — exercised via the real
    _is_saturated/_vpd_trend logic, not a monkeypatch.
    """
    now = dt_util.utcnow()
    for i in range(4):
        mock_coord._vpd_history.append((now - timedelta(minutes=3 - i), 0.5))
    mock_coord._dehumid_on_since = {"zone2": now - timedelta(minutes=10)}
    mock_coord._humid_on_since = {"zone2": None}

    bias = engine._vpd_assist_bias("zone2", leaf_vpd=0.5)  # < vpd_target_min (0.8)

    assert bias == pytest.approx(VPD_ASSIST_STEP_C)


def test_vpd_assist_bias_saturated_humidifier_at_high_vpd(engine, mock_coord):
    """A genuinely saturated humidifier (10+ min continuous runtime, VPD
    trend flat/not improving) with VPD stuck above vpd_target_max (too dry)
    must nudge temp DOWN to help lower VPD — exercised via the real
    _is_saturated/_vpd_trend logic, not a monkeypatch.
    """
    now = dt_util.utcnow()
    for i in range(4):
        mock_coord._vpd_history.append((now - timedelta(minutes=3 - i), 1.5))
    mock_coord._humid_on_since = {"zone2": now - timedelta(minutes=10)}
    mock_coord._dehumid_on_since = {"zone2": None}

    bias = engine._vpd_assist_bias("zone2", leaf_vpd=1.5)  # > vpd_target_max (1.2)

    assert bias == pytest.approx(-VPD_ASSIST_STEP_C)


def test_vpd_assist_bias_not_saturated_yields_no_bias(engine, mock_coord):
    """A dehumidifier that has only just turned on (well under the 8-minute
    dwell threshold) is not yet saturated, so no assist bias should fire even
    though VPD is below vpd_target_min.
    """
    now = dt_util.utcnow()
    for i in range(4):
        mock_coord._vpd_history.append((now - timedelta(minutes=3 - i), 0.5))
    mock_coord._dehumid_on_since = {"zone2": now - timedelta(minutes=2)}
    mock_coord._humid_on_since = {"zone2": None}

    bias = engine._vpd_assist_bias("zone2", leaf_vpd=0.5)

    assert bias == 0.0


def test_vpd_assist_bias_none_when_not_saturated(engine, monkeypatch):
    """No bias is applied when the relevant appliance is not saturated,
    even if VPD is outside range."""
    monkeypatch.setattr(engine, "_is_saturated", lambda zone_label, appliance: False)

    bias = engine._vpd_assist_bias("zone2", 1.5)  # > vpd_target_max, but not saturated

    assert bias == 0.0


def test_vpd_assist_bias_none_when_vpd_is_none(engine):
    """Guards against None leaf_vpd (sensor dropout) — always returns 0.0."""
    assert engine._vpd_assist_bias("zone2", None) == 0.0


# ── _thermal_purge_pct ───────────────────────────────────────────────────────

def test_thermal_purge_pct_ramp(engine, mock_coord):
    """Proportional ramp: 0.0 at the margin boundary, 100.0 at
    thermal_runaway_c, and linearly interpolated in between.
    """
    runaway_c = mock_coord._config["thermal_runaway_c"]  # 32.0
    purge_start = runaway_c - THERMAL_PURGE_MARGIN_C  # 30.5

    # At (or below) the purge-start boundary — inactive.
    assert engine._thermal_purge_pct(purge_start) == 0.0
    assert engine._thermal_purge_pct(purge_start - 5.0) == 0.0

    # Exactly at the hard runaway threshold — full 100% ramp.
    assert engine._thermal_purge_pct(runaway_c) == pytest.approx(100.0)

    # Halfway through the margin band — ~75% (midpoint of the 50-100 ramp).
    midpoint_temp = purge_start + (THERMAL_PURGE_MARGIN_C / 2.0)
    assert engine._thermal_purge_pct(midpoint_temp) == pytest.approx(75.0)


# ── _handle_thermal_runaway ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thermal_runaway_override(engine, mock_coord):
    """When canopy temp meets/exceeds thermal_runaway_c, all Zone 1/2 heater
    switches are commanded OFF and both critical notifications fire.
    """
    mock_coord._config.update(
        {
            "zone1_heater": "switch.zone1_heater",
            "zone1_backup_heater": "switch.zone1_backup_heater",
            "zone2_heater": "switch.zone2_heater",
        }
    )

    # Ensure _set_switch proceeds past its "entity exists" guard.
    fake_state = type("FakeState", (), {"state": "on"})()
    mock_coord.hass.states.get.return_value = fake_state

    runaway_temp = mock_coord._config["thermal_runaway_c"] + 1.0  # comfortably over threshold

    triggered = await engine._handle_thermal_runaway(runaway_temp)

    assert triggered is True

    # All three heater entities should have received a turn_off service call.
    off_calls = [
        call
        for call in mock_coord.hass.services.async_call.await_args_list
        if call.args[:2] == ("switch", "turn_off")
    ]
    off_entity_ids = {call.args[2]["entity_id"] for call in off_calls}
    assert off_entity_ids == {
        "switch.zone1_heater",
        "switch.zone1_backup_heater",
        "switch.zone2_heater",
    }

    # Both the thermal-runaway alert and the "Base Under Siege" easter-egg
    # notification should have fired via the centralised notifier.
    assert mock_coord._notify_critical.await_count == 2


@pytest.mark.asyncio
async def test_thermal_runaway_not_triggered_below_threshold(engine, mock_coord):
    """Canopy temp below the threshold does not trigger runaway handling."""
    safe_temp = mock_coord._config["thermal_runaway_c"] - 5.0

    triggered = await engine._handle_thermal_runaway(safe_temp)

    assert triggered is False
    mock_coord._notify_critical.assert_not_awaited()


@pytest.mark.asyncio
async def test_thermal_runaway_notifies_once_per_sustained_episode(engine, mock_coord):
    """Regression test: a sustained runaway must not re-fire the critical
    notifications on every tick. Before this fix, `_notify_critical` had no
    "already alerted" guard for this path (unlike the light-leak watchdog,
    which already implements this correctly), so a multi-minute runaway
    would generate a duplicate mobile push per ~30s coordinator tick.

    The safety response itself (heater kill / exhaust override, verified by
    `test_thermal_runaway_override` above) must still re-apply every tick —
    only the notification is deduplicated.
    """
    fake_state = type("FakeState", (), {"state": "on"})()
    mock_coord.hass.states.get.return_value = fake_state
    runaway_temp = mock_coord._config["thermal_runaway_c"] + 1.0

    first = await engine._handle_thermal_runaway(runaway_temp)
    assert first is True
    assert mock_coord._notify_critical.await_count == 2

    # Still over threshold on the next tick — no *new* notifications.
    second = await engine._handle_thermal_runaway(runaway_temp)
    assert second is True
    assert mock_coord._notify_critical.await_count == 2

    # Temp recovers below threshold — episode ends, guard clears.
    recovered = await engine._handle_thermal_runaway(
        mock_coord._config["thermal_runaway_c"] - 5.0
    )
    assert recovered is False
    assert mock_coord._notify_critical.await_count == 2

    # A brand new episode alerts again.
    third = await engine._handle_thermal_runaway(runaway_temp)
    assert third is True
    assert mock_coord._notify_critical.await_count == 4


# ── _control_zone anti-short-cycle recording ─────────────────────────────────

@pytest.mark.asyncio
async def test_control_zone_records_compressor_off_when_ac_turns_off(engine, mock_coord):
    """Regression test for the anti-short-cycle ordering bug: previously
    `zone.request_cool(...)` overwrote `zone.ac_on` *before* the "was this
    appliance on a moment ago" check ran, so `_record_compressor_off` was
    unreachable for any discrete (non-reverse-cycle) AC or dehumidifier —
    the user-configurable anti-short-cycle dwell never actually engaged.
    """
    from custom_components.helix_cultivate.climate_engine import ZoneInterlock

    ac_id = "switch.zone2_ac"

    def fake_states_get(entity_id):
        if entity_id == ac_id:
            return type("FakeState", (), {"state": "on"})()
        return None

    mock_coord.hass.states.get.side_effect = fake_states_get
    mock_coord.temp_setpoint = 24.0

    zone = ZoneInterlock("zone2")

    await engine._control_zone(
        zone=zone,
        zone_label="zone2",
        current_temp=24.0,  # inside the temp deadband -> no cool demand
        leaf_vpd=1.0,       # inside the VPD deadband -> no humidify/dehumidify demand
        heater_id=None,
        ac_id=ac_id,
        humid_id=None,
        dehumid_id=None,
    )

    assert mock_coord._last_compressor_off.get("zone2_ac") is not None


# ── _control_exhaust thermal_runaway hard override ──────────────────────────

@pytest.mark.asyncio
async def test_control_exhaust_forces_100_on_thermal_runaway(engine):
    """When `thermal_runaway=True` is passed in, exhaust is forced to 100%
    regardless of VPD/enthalpy readings — the hard safety override takes
    precedence over all other control logic.
    """
    result = await engine._control_exhaust(
        leaf_vpd=1.0,
        canopy_temp=25.0,
        upper_enthalpy=None,
        lung_enthalpy=None,
        sensor_dropout=False,
        lights_on=True,
        thermal_runaway=True,
    )
    assert result == 100.0
