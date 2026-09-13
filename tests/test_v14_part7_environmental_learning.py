"""Tests for v1.4.0 Parts 7-8: Environmental Learning System core —
master toggle inertness, the Learning/Active state machine's unconditional
fixed-duration graduation, confidence-weighted blending, Deep Calibration's
occupancy/dependency gating (reusing Part 3/4's corrected rules), restart
safety for an in-progress test, and the optional exporter's fail-quiet
behavior.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_DRYING_OCCUPIED,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_LEARNING_DURATION_DAYS,
    CONF_LEARNING_STARTED_AT,
    CONF_LEARNING_STATE,
    CONF_THERMAL_LEARNING_ENABLED,
    CONF_ZONE2_OCCUPIED,
    DEFAULT_LEARNING_DURATION_DAYS,
    LEARNING_STATE_ACTIVE,
    LEARNING_STATE_LEARNING,
)
from custom_components.helix_cultivate.learning_engine import (
    TEST_TYPE_DEEP_CALIBRATION,
    LearningEngine,
    outdoor_temp_bucket,
)
from custom_components.helix_cultivate.learning_store import LearningStore
from homeassistant.util import dt as dt_util

DOMAIN = "helix_cultivate"


class _FakeStorage:
    """In-memory stand-in for homeassistant.helpers.storage.Store — avoids
    touching real disk while still exercising LearningStore's real logic."""

    def __init__(self):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        import copy
        self._data = copy.deepcopy(data)


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def learning_store(fake_hass):
    store = LearningStore(fake_hass)
    store._store = _FakeStorage()
    # A freshly constructed LearningStore already starts from a deep copy
    # of EMPTY_LEARNING_STORE (see __init__) — no need to await async_load()
    # here, which avoids needing an async fixture (pytest-asyncio strict
    # mode, used throughout this suite, only awaits *test* functions marked
    # @pytest.mark.asyncio, not plain @pytest.fixture functions).
    fake_hass.data[DOMAIN]["learning_store"] = store
    return store


@pytest.fixture
def fake_coord(fake_hass, learning_store):
    coord = MagicMock()
    coord.hass = fake_hass
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.queue_option_write = MagicMock(
        side_effect=lambda k, v: coord._config.__setitem__(k, v)
    )
    coord.temp_setpoint = 24.0
    coord.light_intensity_pct = 100.0
    coord.data = {}
    coord.is_zone2_occupied = MagicMock(return_value=False)
    coord.is_drying_occupied = MagicMock(return_value=False)
    coord.is_conditioning_room_calibration_eligible = MagicMock(return_value=True)
    coord.conditioning_room_dependent_zones = MagicMock(return_value=["zone2"])
    coord._learning_last_log = {}
    return coord


class TestOutdoorTempBucket:
    def test_buckets_group_by_5_degrees(self):
        assert outdoor_temp_bucket(12.0) == "10to15"
        assert outdoor_temp_bucket(14.9) == "10to15"
        assert outdoor_temp_bucket(15.0) == "15to20"
        assert outdoor_temp_bucket(-3.0) == "-5to0"

    def test_unknown_when_none(self):
        assert outdoor_temp_bucket(None) == "unknown"


@pytest.mark.asyncio
class TestLearningStateMachine:
    async def test_ensure_started_sets_learning_state(self, fake_coord):
        engine = LearningEngine(fake_coord)
        await engine.ensure_started()

        assert fake_coord._config[CONF_LEARNING_STATE] == LEARNING_STATE_LEARNING
        assert fake_coord._config[CONF_LEARNING_STARTED_AT] is not None

    async def test_ensure_started_is_idempotent(self, fake_coord):
        engine = LearningEngine(fake_coord)
        await engine.ensure_started()
        first_started_at = fake_coord._config[CONF_LEARNING_STARTED_AT]
        await engine.ensure_started()

        assert fake_coord._config[CONF_LEARNING_STARTED_AT] == first_started_at

    async def test_does_not_graduate_before_duration_elapses(self, fake_coord):
        engine = LearningEngine(fake_coord)
        await engine.ensure_started()

        assert engine.maybe_graduate_to_active() is False
        assert engine.learning_state() == LEARNING_STATE_LEARNING

    async def test_graduates_unconditionally_after_fixed_duration(self, fake_coord):
        """Must graduate regardless of what conditions were or weren't
        observed — no event-based gate of any kind."""
        engine = LearningEngine(fake_coord)
        started_at = dt_util.utcnow() - timedelta(days=DEFAULT_LEARNING_DURATION_DAYS + 1)
        fake_coord._config[CONF_LEARNING_STARTED_AT] = started_at.isoformat()
        fake_coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_LEARNING

        graduated = engine.maybe_graduate_to_active()

        assert graduated is True
        assert engine.learning_state() == LEARNING_STATE_ACTIVE

    async def test_respects_configured_custom_duration(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord._config[CONF_LEARNING_DURATION_DAYS] = 7
        started_at = dt_util.utcnow() - timedelta(days=8)
        fake_coord._config[CONF_LEARNING_STARTED_AT] = started_at.isoformat()
        fake_coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_LEARNING

        assert engine.maybe_graduate_to_active() is True

    async def test_already_active_does_not_re_graduate(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_ACTIVE
        fake_coord._config[CONF_LEARNING_STARTED_AT] = dt_util.utcnow().isoformat()

        assert engine.maybe_graduate_to_active() is False

    async def test_model_keeps_refitting_after_active_not_frozen(self, fake_coord, learning_store):
        """Active does not mean logging/regression updates stop — they
        continue indefinitely (Part 7.2's "never freezes" requirement).
        A single sample isn't enough to fit the v1.4.1 regression, but the
        raw hourly log row itself (with the new setpoint_gap_c/month/
        occupied fields the regression trains on) must still be recorded
        every time, unconditionally."""
        engine = LearningEngine(fake_coord)
        fake_coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_ACTIVE
        fake_coord._config[CONF_LEARNING_STARTED_AT] = dt_util.utcnow().isoformat()

        await engine.maybe_log_hourly("zone2", 10.0, 22.0, 50.0, True, 100.0, "cyc1")

        logs = learning_store.get_hourly_logs("zone2")
        assert len(logs) == 1
        assert logs[0]["setpoint_gap_c"] == pytest.approx(24.0 - 22.0)
        assert logs[0]["occupied"] is True
        assert logs[0]["month"] is not None
        # Below the minimum sample threshold — no fitted model yet.
        assert learning_store.get_regression_model("zone2") is None


@pytest.mark.asyncio
class TestConfidenceWeightedBlending:
    """v1.4.1 Part 4: confidence-weighted blending is now backed by a
    fitted multi-variable regression (learning_regression.py) rather than
    bucketed averaging — see test_v141_part4_regression.py for the
    regression math itself. These tests cover the engine-level wiring:
    zero bias with no fitted model, and independence across zones."""

    async def test_zero_bias_with_no_data(self, fake_coord):
        engine = LearningEngine(fake_coord)
        assert engine.get_confidence_blended_bias("zone2", 10.0) == 0.0

    async def test_zero_bias_below_minimum_sample_count(self, fake_coord, learning_store):
        """Part 4.4: too little data to fit at all -> no model saved ->
        blended bias stays exactly 0.0, deferring entirely to the generic
        fallback rather than guessing from a handful of points."""
        engine = LearningEngine(fake_coord)
        for i in range(5):
            fake_coord._learning_last_log["zone2"] = None
            await engine.maybe_log_hourly("zone2", 10.0 + i, 22.0, 50.0, True, 100.0, "cyc1")

        assert learning_store.get_regression_model("zone2") is None
        assert engine.get_confidence_blended_bias("zone2", 10.0) == 0.0

    async def test_different_zones_are_independent(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await learning_store.set_regression_model(
            "zone2", {"coefficients": [1.0] * 9, "xtx_inv": [[0.0] * 9 for _ in range(9)], "sigma": 0.0, "n": 100}
        )

        assert engine.get_confidence_blended_bias("drying", 10.0) == 0.0


@pytest.mark.asyncio
class TestDeepCalibrationGating:
    async def test_blocked_when_zone2_occupied(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord.is_zone2_occupied = MagicMock(return_value=True)

        with pytest.raises(ValueError):
            await engine.start_deep_calibration("zone2")

    async def test_allowed_when_zone2_unoccupied(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord.is_zone2_occupied = MagicMock(return_value=False)

        test = await engine.start_deep_calibration("zone2")
        assert test["type"] == TEST_TYPE_DEEP_CALIBRATION
        assert test["zone"] == "zone2"

    async def test_conditioning_room_follows_corrected_dependency_rule(self, fake_coord):
        """Reuses Part 3's is_conditioning_room_calibration_eligible —
        not its own (always-empty) occupancy."""
        engine = LearningEngine(fake_coord)
        fake_coord.is_conditioning_room_calibration_eligible = MagicMock(return_value=False)

        with pytest.raises(ValueError):
            await engine.start_deep_calibration("conditioning")

        fake_coord.is_conditioning_room_calibration_eligible = MagicMock(return_value=True)
        test = await engine.start_deep_calibration("conditioning")
        assert test["zone"] == "conditioning"

    async def test_is_deep_calibration_active_true_only_for_matching_zone(self, fake_coord):
        engine = LearningEngine(fake_coord)
        await engine.start_deep_calibration("zone2")

        assert engine.is_deep_calibration_active("zone2") is True
        assert engine.is_deep_calibration_active("drying") is False

    async def test_zero_fan_and_occupancy_do_not_confuse_drying_gate(self, fake_coord):
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord.is_drying_occupied = MagicMock(return_value=True)
        engine = LearningEngine(fake_coord)

        with pytest.raises(ValueError):
            await engine.start_deep_calibration("drying")


@pytest.mark.asyncio
class TestRestartSafety:
    async def test_active_test_survives_reconstruction(self, fake_coord, learning_store):
        """Simulates a restart: a fresh LearningEngine built on the same
        durable store must see the in-progress test exactly as it was."""
        engine = LearningEngine(fake_coord)
        original = await engine.start_deep_calibration("zone2")

        fresh_engine = LearningEngine(fake_coord)  # simulates a new coordinator instance
        resumed = fresh_engine._store.get_active_test()

        assert resumed["zone"] == "zone2"
        assert resumed["started_at"] == original["started_at"]

    async def test_finished_test_clears_active_slot_and_resumes_control(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        test = await engine.start_deep_calibration("zone2")
        # Force it to already be past its duration.
        test["started_at"] = (dt_util.utcnow() - timedelta(minutes=test["duration_min"] + 1)).isoformat()
        await learning_store.set_active_test(test)

        await engine.tick_active_test({"zone2": 22.0})

        assert learning_store.get_active_test() is None
        assert engine.is_deep_calibration_active("zone2") is False


@pytest.mark.asyncio
class TestExporterFailsQuietly:
    async def test_noop_when_disabled(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord._config["thermal_learning_export_enabled"] = False
        # Should not raise even though hass.helpers isn't a real client.
        await engine._maybe_export("zone2", 10.0, 22.0, 50.0)

    async def test_noop_when_url_unset(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord._config["thermal_learning_export_enabled"] = True
        fake_coord._config["thermal_learning_export_url"] = None
        await engine._maybe_export("zone2", 10.0, 22.0, 50.0)

    async def test_does_not_raise_when_endpoint_unreachable(self, fake_coord):
        engine = LearningEngine(fake_coord)
        fake_coord._config["thermal_learning_export_enabled"] = True
        fake_coord._config["thermal_learning_export_url"] = "http://unreachable.invalid/write"
        session = MagicMock()
        session.post = AsyncMock(side_effect=ConnectionError("no route"))
        fake_coord.hass.helpers.aiohttp_client.async_get_clientsession = MagicMock(return_value=session)

        # Must not raise — core function is unaffected by exporter failure.
        await engine._maybe_export("zone2", 10.0, 22.0, 50.0)
