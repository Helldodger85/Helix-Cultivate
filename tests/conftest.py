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
