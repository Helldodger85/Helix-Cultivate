"""Tests for v1.6.0 Part 5: Environmental Learning Shadow Mode.

5.1: A new Shadow Mode toggle (CONF_LEARNING_SHADOW_MODE) on the
Environmental Learning Settings tab, visible only when the master toggle is
on, defaulting to on whenever Environmental Learning is first enabled.

5.2: The regression's confidence-weighted blending (get_confidence_blended_
bias) is wired into Conditioning Room's existing weather-feedforward
setpoint pre-compensation. The prediction is computed and logged every
relevant tick regardless of Shadow Mode's state; only whether it's actually
APPLIED to the real setpoint depends on Shadow Mode:
  - Shadow Mode ON: only the generic weather feedforward is applied.
  - Shadow Mode OFF: the full confidence-weighted blended value is applied.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_LEARNING_SHADOW_MODE,
    CONF_THERMAL_LEARNING_ENABLED,
    DEFAULT_LEARNING_SHADOW_MODE,
)
from custom_components.helix_cultivate.learning_engine import LearningEngine

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestShadowModeDefaultsOn:
    @pytest.mark.asyncio
    async def test_ensure_started_seeds_shadow_mode_true(self, mock_coord):
        mock_coord._config = {}
        mock_coord._get = lambda k, d=None: mock_coord._config.get(k, d)
        mock_coord.queue_option_write = MagicMock()
        engine = LearningEngine(mock_coord)

        await engine.ensure_started()

        assert mock_coord._config[CONF_LEARNING_SHADOW_MODE] is True
        mock_coord.queue_option_write.assert_any_call(CONF_LEARNING_SHADOW_MODE, True)

    def test_shadow_mode_enabled_defaults_true_when_unset(self, mock_coord):
        mock_coord._config = {}
        mock_coord._get = lambda k, d=None: mock_coord._config.get(k, d)
        engine = LearningEngine(mock_coord)
        assert engine.shadow_mode_enabled() is True

    def test_shadow_mode_enabled_respects_explicit_false(self, mock_coord):
        mock_coord._config = {CONF_LEARNING_SHADOW_MODE: False}
        mock_coord._get = lambda k, d=None: mock_coord._config.get(k, d)
        engine = LearningEngine(mock_coord)
        assert engine.shadow_mode_enabled() is False

    def test_default_constant_is_true(self):
        assert DEFAULT_LEARNING_SHADOW_MODE is True


class TestShadowFeedforwardComputedRegardlessOfMode:
    """The blended prediction must always be computed (and available for
    Part 6's chart), whether or not Shadow Mode allows it to be applied."""

    def _engine_with_model(self, mock_coord, shadow_mode: bool):
        mock_coord._config = {CONF_LEARNING_SHADOW_MODE: shadow_mode}
        mock_coord._get = lambda k, d=None: mock_coord._config.get(k, d)
        mock_coord.temp_setpoint = 24.0
        store = MagicMock()
        store.get_regression_model = MagicMock(return_value={"fake": "model"})
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)
        return engine

    def test_shadow_on_computes_blended_but_applies_generic_only(self, mock_coord, monkeypatch):
        engine = self._engine_with_model(mock_coord, shadow_mode=True)
        monkeypatch.setattr(
            "custom_components.helix_cultivate.learning_regression.build_feature_vector",
            lambda **kw: [1.0],
        )
        monkeypatch.setattr(
            "custom_components.helix_cultivate.learning_regression.predict_with_confidence",
            lambda model, x0: (2.0, 0.8),  # predicted=2.0C, confidence=0.8 -> blended=1.6
        )

        result = engine.compute_conditioning_shadow_feedforward(
            generic_bias_c=0.5, outdoor_temp_c=10.0, indoor_temp_c=22.0,
        )

        assert result["shadow_mode"] is True
        assert result["generic_bias_c"] == 0.5
        assert result["blended_bias_c"] == pytest.approx(1.6)
        assert result["confidence"] == pytest.approx(0.8)
        # Shadow ON: applied must be the GENERIC value, never the blended one.
        assert result["applied_bias_c"] == pytest.approx(0.5)
        # But the prediction itself is still fully computed/available.
        assert result["predicted_indoor_temp_c"] == pytest.approx(24.0 - 1.6)

    def test_shadow_off_applies_full_blended_value(self, mock_coord, monkeypatch):
        engine = self._engine_with_model(mock_coord, shadow_mode=False)
        monkeypatch.setattr(
            "custom_components.helix_cultivate.learning_regression.build_feature_vector",
            lambda **kw: [1.0],
        )
        monkeypatch.setattr(
            "custom_components.helix_cultivate.learning_regression.predict_with_confidence",
            lambda model, x0: (2.0, 0.8),
        )

        result = engine.compute_conditioning_shadow_feedforward(
            generic_bias_c=0.5, outdoor_temp_c=10.0, indoor_temp_c=22.0,
        )

        assert result["shadow_mode"] is False
        # Shadow OFF: applied must be the full BLENDED value, not the generic one.
        assert result["applied_bias_c"] == pytest.approx(1.6)

    def test_no_fitted_model_yet_is_inert_regardless_of_shadow_mode(self, mock_coord):
        mock_coord._config = {CONF_LEARNING_SHADOW_MODE: False}
        mock_coord._get = lambda k, d=None: mock_coord._config.get(k, d)
        mock_coord.temp_setpoint = 24.0
        store = MagicMock()
        store.get_regression_model = MagicMock(return_value=None)
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        result = engine.compute_conditioning_shadow_feedforward(
            generic_bias_c=0.5, outdoor_temp_c=10.0, indoor_temp_c=22.0,
        )

        assert result["blended_bias_c"] == 0.0
        assert result["confidence"] == 0.0
        # Shadow mode off means "apply the blended value" — but with no
        # fitted model yet, blended is a safe 0.0, so applied is 0.0 too.
        assert result["applied_bias_c"] == 0.0


class TestCoordinatorLevelSafeWrapper:
    """HelixCoordinator.get_conditioning_shadow_feedforward mirrors
    is_deep_calibration_active's cheap always-safe pattern."""

    def test_inert_when_learning_disabled(self, mock_coord):
        from custom_components.helix_cultivate.coordinator import HelixCoordinator

        mock_coord._get = lambda key, default=None: {CONF_THERMAL_LEARNING_ENABLED: False}.get(key, default)

        result = HelixCoordinator.get_conditioning_shadow_feedforward(
            mock_coord, generic_bias_c=0.7, outdoor_temp_c=5.0, indoor_temp_c=20.0,
        )

        assert result["shadow_mode"] is True
        assert result["applied_bias_c"] == pytest.approx(0.7)
        assert result["blended_bias_c"] == 0.0
        assert result["predicted_indoor_temp_c"] is None


@pytest.mark.asyncio
class TestConditioningRoomAppliesCorrectBiasPerShadowMode:
    """End-to-end through ClimateEngine.run()'s real Zone 1 control block:
    the extra_setpoint_bias_c actually fed to _control_zone must reflect
    Shadow Mode's gating, proving the wiring inside run() itself — not just
    the isolated LearningEngine helper."""

    def _wired_engine(self, mock_coord, shadow_result):
        from unittest.mock import AsyncMock
        from custom_components.helix_cultivate.climate_engine import ClimateEngine

        mock_coord._config.update({"topology": "coordinated"})
        engine = ClimateEngine(mock_coord)

        # Isolate the Zone 1 control block: neutralise every other branch
        # run() touches so only the shadow-feedforward wiring is exercised.
        engine._handle_thermal_runaway = AsyncMock(return_value=False)
        engine._handle_light_high_temp_dim = AsyncMock(return_value=None)
        engine._handle_dew_point_risk = AsyncMock(return_value=False)
        engine._check_zone1_heater_cutoff = AsyncMock(return_value=None)
        engine._control_exhaust = AsyncMock(return_value=50.0)
        engine._conditioning_room_enabled = MagicMock(return_value=True)
        engine._drying_environment_enabled = MagicMock(return_value=False)
        engine._weather_feedforward_bias_c = AsyncMock(return_value=0.4)
        engine._preheat_bias_c = MagicMock(return_value=0.0)
        engine._bang_bang_rh = MagicMock(return_value=(False, False))
        engine._control_zone = AsyncMock(return_value=None)
        engine._stage_backup_heater = AsyncMock(return_value=False)
        engine._check_light_leak = AsyncMock(return_value=None)
        engine._check_stratification = AsyncMock(return_value=None)
        mock_coord._get = lambda key, default=None: mock_coord._config.get(key, default)
        mock_coord.get_conditioning_shadow_feedforward = MagicMock(return_value=shadow_result)
        return engine

    async def _run_zone1_tick(self, engine):
        await engine.run(
            upper_temp=24.0, upper_rh=60.0, mid_temp=24.0, mid_rh=60.0,
            lower_temp=24.0, lower_rh=60.0, lung_temp=22.0, lung_rh=55.0,
            leaf_vpd=1.0, upper_enthalpy=None, lung_enthalpy=None,
            sensor_dropout=False, lights_on=True,
        )
        for call in engine._control_zone.call_args_list:
            if call.kwargs.get("zone_label") == "zone1":
                return call
        raise AssertionError("_control_zone was never called for zone1")

    async def test_shadow_on_feeds_generic_bias_not_blended(self, mock_coord):
        engine = self._wired_engine(mock_coord, shadow_result={
            "shadow_mode": True, "generic_bias_c": 0.4, "blended_bias_c": 1.9,
            "confidence": 0.9, "applied_bias_c": 0.4, "predicted_indoor_temp_c": 22.1,
        })

        zone1_call = await self._run_zone1_tick(engine)

        assert zone1_call.kwargs["extra_setpoint_bias_c"] == pytest.approx(0.4)

    async def test_shadow_off_feeds_full_blended_value(self, mock_coord):
        engine = self._wired_engine(mock_coord, shadow_result={
            "shadow_mode": False, "generic_bias_c": 0.4, "blended_bias_c": 1.9,
            "confidence": 0.9, "applied_bias_c": 1.9, "predicted_indoor_temp_c": 22.1,
        })

        zone1_call = await self._run_zone1_tick(engine)

        assert zone1_call.kwargs["extra_setpoint_bias_c"] == pytest.approx(1.9)

    async def test_shadow_prediction_returned_in_run_result_regardless_of_mode(self, mock_coord):
        engine = self._wired_engine(mock_coord, shadow_result={
            "shadow_mode": True, "generic_bias_c": 0.4, "blended_bias_c": 1.9,
            "confidence": 0.9, "applied_bias_c": 0.4, "predicted_indoor_temp_c": 22.1,
        })

        result = await engine.run(
            upper_temp=24.0, upper_rh=60.0, mid_temp=24.0, mid_rh=60.0,
            lower_temp=24.0, lower_rh=60.0, lung_temp=22.0, lung_rh=55.0,
            leaf_vpd=1.0, upper_enthalpy=None, lung_enthalpy=None,
            sensor_dropout=False, lights_on=True,
        )

        assert result["shadow_prediction"]["blended_bias_c"] == pytest.approx(1.9)
        assert result["shadow_prediction"]["predicted_indoor_temp_c"] == pytest.approx(22.1)


# ── Frontend: Shadow Mode toggle gating/default/copy ────────────────────────

CHECK_SCRIPT = REPO_ROOT / "tests" / "js" / "check_shadow_mode_toggle.js"

pytestmark_js = pytest.mark.skipif(
    shutil.which("node") is None, reason="Node.js is required for this frontend check"
)


@pytestmark_js
def test_shadow_mode_toggle_frontend_behavior():
    result = subprocess.run(
        ["node", str(CHECK_SCRIPT)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"Node check failed.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK: Shadow Mode toggle gated on master toggle" in result.stdout
