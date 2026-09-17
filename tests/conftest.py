"""Pytest fixtures for the Helix Cultivate minimal test suite.

These fixtures build a lightweight mock coordinator (via unittest.mock) with
explicit attribute stubs — no `homeassistant.test_util` dependency and no
running Home Assistant instance is required. This keeps the suite fast and
runnable in any CI environment with just `pytest` + `pytest-asyncio`
installed alongside the `homeassistant` package (for `ClimateEngine`'s
internal imports).
"""
from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.climate_engine import ClimateEngine


@pytest.fixture
def mock_coord():
    """Return a MagicMock standing in for HelixCoordinator with the minimal
    surface area ClimateEngine touches during a control tick."""
    coord = MagicMock()

    # ── hass + services ────────────────────────────────────────────────────
    coord.hass = MagicMock()
    coord.hass.states = MagicMock()
    coord.hass.states.get = MagicMock(return_value=None)
    coord.hass.services = MagicMock()
    coord.hass.services.async_call = AsyncMock()

    # ── merged config dict ─────────────────────────────────────────────────
    coord._config = {
        "thermal_runaway_c": 32.0,
        "heater_cutoff_c": 26.0,
        "anti_short_cycle_min": 3,
        "control_algorithm": "bang_bang",
        "topology": "coordinated",
    }

    # ── setpoints ───────────────────────────────────────────────────────────
    coord.vpd_target = 1.0
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2
    coord.temp_setpoint = 24.0
    coord.rh_setpoint = 65.0
    coord.light_intensity_pct = 100.0

    # ── history buffers (Phase 6 / 9D trend detection) ─────────────────────
    coord._vpd_history = deque(maxlen=6)
    coord._temp_history = deque(maxlen=6)

    # ── saturation tracking (Phase 9) ──────────────────────────────────────
    coord._dehumid_on_since = {"zone1": None, "zone2": None, "drying": None}
    coord._humid_on_since = {"zone1": None, "zone2": None, "drying": None}

    # ── appliance dropout watchdog (Phase 10B) ─────────────────────────────
    coord._appliance_unavail_since = {}
    coord._check_appliance_dropout = MagicMock(return_value=False)

    # ── compressor anti-short-cycle timers ──────────────────────────────────
    coord._last_compressor_off = {}

    # ── notifications ───────────────────────────────────────────────────────
    coord._notify_critical = AsyncMock()

    # ── lights-off purge state ──────────────────────────────────────────────
    coord._lights_off_purge_until = None
    coord._lights_state_prev = None
    coord._lights_on = MagicMock(return_value=True)

    # ── drying-stage gentle-cyclic airflow state (Part 2.A) ─────────────────
    coord._drying_humidity_high_since = None
    coord._drying_humidity_override_alerted = False
    coord._drying_cycle_phase_since = None
    coord._drying_cycle_is_on = True
    coord._drying_airflow_applied_pct = 0.0
    coord._drying_humidity_override_active = False
    # Real callables (not auto-mocks) so per-tier gentle drying actually
    # exercises the tier-enabled gate rather than always looking "enabled".
    coord._is_fan_tier_enabled = MagicMock(return_value=True)
    coord._apply_fan_speed_to_tier = AsyncMock()

    # ── Environmental Learning (Part 7) — disabled by default in tests, so
    # existing control-loop tests aren't short-circuited by a MagicMock's
    # default truthy return value. ─────────────────────────────────────────
    coord.is_deep_calibration_active = MagicMock(return_value=False)
    coord.active_live_actuator_test_for_zone = MagicMock(return_value=None)

    # ── v1.6.0 Part 5.2: Shadow Mode feedforward — a real callable (not a
    # bare MagicMock, which isn't subscriptable) returning the inert
    # "Environmental Learning disabled" shape by default, matching the
    # real coordinator method's own disabled-toggle fallback exactly.
    def _default_shadow_feedforward(generic_bias_c, outdoor_temp_c=None, indoor_temp_c=None,
                                     lights_on=False, light_pct=0.0, occupied=False):
        return {
            "shadow_mode": True,
            "generic_bias_c": generic_bias_c,
            "blended_bias_c": 0.0,
            "confidence": 0.0,
            "applied_bias_c": generic_bias_c,
            "predicted_indoor_temp_c": None,
        }

    coord.get_conditioning_shadow_feedforward = MagicMock(side_effect=_default_shadow_feedforward)

    # ── v1.4.1 Part 1.2: real dict (not a MagicMock auto-attribute), same
    # reasoning as _learning_last_log above — follow_me's rate-limit compares
    # a float against the "last sent" value, which must be able to be None.
    coord._follow_me_last_sent = {}

    # ── fire-once-per-episode notification guards ──────────────────────────
    # Real explicit bools (not left to MagicMock auto-vivification, which
    # would return a truthy child Mock and silently skip the "not yet
    # alerted" branch these guards depend on).
    coord._thermal_runaway_alerted = False
    coord._sensor_dropout_alerted = False
    coord._appliance_dropout_alerted = {}

    # ── stage manager stub (used by drying-zone control) ───────────────────
    stage_manager = MagicMock()
    stage_manager.current_stage = "peak_flower"
    stage_manager.is_drying_unlocked = MagicMock(return_value=False)
    stage_manager.current_vpd_range = MagicMock(return_value=(0.8, 1.2))
    stage_manager.current_temp_anchor = MagicMock(return_value=24.0)
    coord.stage_manager = stage_manager

    coord.data = {}

    return coord


@pytest.fixture
def engine(mock_coord):
    """Return a ClimateEngine bound to the mock coordinator."""
    return ClimateEngine(mock_coord)
