"""Tests for v1.4.1 Part 4: the Environmental Learning System's confidence
model upgraded from bucketed running-mean averaging to a genuine
multi-variable ordinary least-squares regression (learning_regression.py),
with prediction-interval-based confidence feeding the existing
confidence-weighted blending mechanism.

Covers the regression math directly (fit_ols/predict_with_confidence/
build_feature_vector) plus the engine-level wiring: refit-on-log cadence,
and get_confidence_blended_bias reading the fitted model instead of a
bucket.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.helix_cultivate.const import MIN_REGRESSION_SAMPLES
from custom_components.helix_cultivate.learning_engine import LearningEngine
from custom_components.helix_cultivate.learning_regression import (
    build_feature_vector,
    fit_ols,
    predict_with_confidence,
)
from custom_components.helix_cultivate.learning_store import LearningStore

DOMAIN = "helix_cultivate"


# ── Direct regression-math tests ─────────────────────────────────────────────


def _synthetic_dataset(n: int, seed: int = 7) -> tuple[list[list[float]], list[float]]:
    """A real (small-noise) linear relationship across every input
    variable, with every variable actually varying across rows — a
    rank-deficient design (e.g. every row sharing the same hour/month)
    would make the fit degenerate for reasons that have nothing to do with
    sample size, so this deliberately spreads every dimension out."""
    rng = random.Random(seed)
    rows: list[list[float]] = []
    targets: list[float] = []
    for i in range(n):
        outdoor_temp_c = -10.0 + (i % 41)  # -10..30
        hour = i % 24
        month = (i % 12) + 1
        lights_on = i % 2 == 0
        light_pct = float((i * 13) % 100)
        occupied = i % 3 == 0
        vector = build_feature_vector(
            outdoor_temp_c=outdoor_temp_c, hour_of_day=hour, month=month,
            lights_on=lights_on, light_pct=light_pct, occupied=occupied,
        )
        assert vector is not None
        # True relationship: gap shrinks as outdoor warms, plus a small
        # lights-on and occupied effect, plus small noise.
        true_value = (
            0.3 * outdoor_temp_c
            + (0.5 if lights_on else 0.0)
            + (0.3 if occupied else 0.0)
            + rng.uniform(-0.2, 0.2)
        )
        rows.append(vector)
        targets.append(true_value)
    return rows, targets


class TestBuildFeatureVector:
    def test_none_when_outdoor_temp_missing(self):
        assert build_feature_vector(
            outdoor_temp_c=None, hour_of_day=12, month=6,
            lights_on=True, light_pct=50.0, occupied=False,
        ) is None

    def test_defaults_hour_and_month_when_missing(self):
        vector = build_feature_vector(
            outdoor_temp_c=10.0, hour_of_day=None, month=None,
            lights_on=False, light_pct=0.0, occupied=False,
        )
        assert vector is not None
        assert len(vector) == 9

    def test_vector_length_matches_feature_count(self):
        vector = build_feature_vector(
            outdoor_temp_c=10.0, hour_of_day=6, month=3,
            lights_on=True, light_pct=75.0, occupied=True,
        )
        assert len(vector) == 9
        assert vector[0] == 1.0  # intercept
        assert vector[1] == 10.0  # outdoor_temp_c


class TestFitOlsSafeFallback:
    def test_none_below_minimum_sample_count(self):
        rows, targets = _synthetic_dataset(5)
        assert fit_ols(rows, targets) is None

    def test_none_when_design_matrix_is_rank_deficient(self):
        """Every row identical (no variation in any input) — a genuinely
        singular fit that must never produce a falsely-confident model."""
        vector = build_feature_vector(
            outdoor_temp_c=10.0, hour_of_day=12, month=6,
            lights_on=True, light_pct=50.0, occupied=False,
        )
        rows = [vector] * (MIN_REGRESSION_SAMPLES + 10)
        targets = [2.0] * len(rows)
        assert fit_ols(rows, targets) is None

    def test_fits_successfully_with_enough_varied_data(self):
        rows, targets = _synthetic_dataset(MIN_REGRESSION_SAMPLES + 10)
        model = fit_ols(rows, targets)
        assert model is not None
        assert model["n"] == len(rows)
        assert len(model["coefficients"]) == 9


class TestPredictWithConfidence:
    def test_confidence_increases_with_more_data(self):
        """More data covering the same input space should narrow the
        prediction interval and raise confidence for the same query
        point — the actual claim behind "prediction-interval width
        correctly narrows as more relevant data accumulates"."""
        x0 = build_feature_vector(
            outdoor_temp_c=10.0, hour_of_day=12, month=6,
            lights_on=True, light_pct=50.0, occupied=False,
        )

        small_rows, small_targets = _synthetic_dataset(MIN_REGRESSION_SAMPLES + 3)
        small_model = fit_ols(small_rows, small_targets)
        _, small_confidence = predict_with_confidence(small_model, x0)

        large_rows, large_targets = _synthetic_dataset(300)
        large_model = fit_ols(large_rows, large_targets)
        _, large_confidence = predict_with_confidence(large_model, x0)

        assert large_confidence > small_confidence
        assert large_confidence <= 1.0

    def test_confidence_never_exceeds_one(self):
        rows, targets = _synthetic_dataset(500)
        model = fit_ols(rows, targets)
        x0 = build_feature_vector(
            outdoor_temp_c=10.0, hour_of_day=12, month=6,
            lights_on=True, light_pct=50.0, occupied=False,
        )
        _, confidence = predict_with_confidence(model, x0)
        assert 0.0 <= confidence <= 1.0

    def test_prediction_sensible_for_unseen_combination_of_seen_factors(self):
        """The actual proof of genuine multi-variable regression rather
        than disguised bucketing: fit on data where "occupied" and a very
        cold outdoor temperature never occur together, but each factor's
        effect has separately been observed elsewhere. The regression must
        still produce a sensible prediction for that exact unseen
        combination by combining the two separately-learned effects."""
        rng = random.Random(3)
        rows: list[list[float]] = []
        targets: list[float] = []
        for i in range(200):
            # Cold and occupied never co-occur in the training set...
            if i % 2 == 0:
                outdoor_temp_c = -10.0 + (i % 10)  # cold, always unoccupied
                occupied = False
            else:
                outdoor_temp_c = 15.0 + (i % 15)  # mild/warm, sometimes occupied
                occupied = i % 4 == 1
            hour = i % 24
            month = (i % 12) + 1
            lights_on = i % 2 == 0
            light_pct = float((i * 11) % 100)
            vector = build_feature_vector(
                outdoor_temp_c=outdoor_temp_c, hour_of_day=hour, month=month,
                lights_on=lights_on, light_pct=light_pct, occupied=occupied,
            )
            true_value = 0.3 * outdoor_temp_c + (0.8 if occupied else 0.0) + rng.uniform(-0.1, 0.1)
            rows.append(vector)
            targets.append(true_value)

        model = fit_ols(rows, targets)
        assert model is not None

        # Query the never-seen combination: very cold AND occupied.
        x0 = build_feature_vector(
            outdoor_temp_c=-10.0, hour_of_day=12, month=1,
            lights_on=True, light_pct=50.0, occupied=True,
        )
        predicted, confidence = predict_with_confidence(model, x0)

        # A bucketed model would have zero information for this exact
        # combination (never observed). A real regression combines the
        # separately-learned outdoor_temp effect (~0.3 * -10 = -3.0) and
        # occupied effect (~+0.8) into a sensible combined prediction.
        assert predicted == pytest.approx(0.3 * -10.0 + 0.8, abs=0.6)
        assert confidence > 0.0

    def test_malformed_model_returns_zero_confidence_not_a_crash(self):
        predicted, confidence = predict_with_confidence({"garbage": True}, [1.0])
        assert predicted == 0.0
        assert confidence == 0.0


# ── Engine-level wiring ──────────────────────────────────────────────────────


class _FakeStorage:
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
    fake_hass.data[DOMAIN]["learning_store"] = store
    return store


@pytest.fixture
def fake_coord(fake_hass, learning_store):
    coord = MagicMock()
    coord.hass = fake_hass
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.temp_setpoint = 24.0
    coord._learning_last_log = {}
    return coord


async def _log_varied_samples(engine, fake_coord, zone: str, n: int) -> None:
    rng = random.Random(11)
    for i in range(n):
        fake_coord._learning_last_log[zone] = None
        hour = i % 24
        month = (i % 12) + 1
        fake_now = datetime(2024, month, 15, hour, 0, tzinfo=timezone.utc)
        outdoor_temp_c = -10.0 + (i % 41)
        indoor_temp_c = 24.0 - 0.3 * outdoor_temp_c + rng.uniform(-0.2, 0.2)
        lights_on = i % 2 == 0
        light_pct = float((i * 13) % 100)
        cycle_id = "cyc1" if i % 3 == 0 else None
        with patch(
            "custom_components.helix_cultivate.learning_engine.dt_util.utcnow",
            return_value=fake_now,
        ):
            await engine.maybe_log_hourly(
                zone, outdoor_temp_c, indoor_temp_c, 50.0, lights_on, light_pct, cycle_id
            )


@pytest.mark.asyncio
class TestEngineRefitsOnRollingCadence:
    async def test_no_model_below_minimum_samples(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", 5)
        assert learning_store.get_regression_model("zone2") is None

    async def test_model_appears_once_enough_samples_logged(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", MIN_REGRESSION_SAMPLES + 5)
        model = learning_store.get_regression_model("zone2")
        assert model is not None
        assert model["n"] == MIN_REGRESSION_SAMPLES + 5

    async def test_refits_again_as_more_data_arrives_never_freezes(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", MIN_REGRESSION_SAMPLES + 5)
        first_n = learning_store.get_regression_model("zone2")["n"]

        await _log_varied_samples(engine, fake_coord, "zone2", 20)
        second_n = learning_store.get_regression_model("zone2")["n"]

        assert second_n > first_n

    async def test_pre_upgrade_rows_without_setpoint_gap_are_skipped(self, fake_coord, learning_store):
        """A v1.4.0 install's existing hourly_logs rows predate
        setpoint_gap_c/month/occupied — they must be silently skipped by
        the regression rather than crashing or being treated as zero."""
        for _ in range(MIN_REGRESSION_SAMPLES + 5):
            await learning_store.record_hourly_log(
                {"zone": "zone2", "outdoor_temp_c": 10.0, "indoor_temp_c": 22.0}
            )
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", 3)
        # Only the 3 new-format rows exist — still below threshold.
        assert learning_store.get_regression_model("zone2") is None


@pytest.mark.asyncio
class TestGetConfidenceBlendedBiasUsesFittedModel:
    async def test_zero_when_no_model(self, fake_coord):
        engine = LearningEngine(fake_coord)
        assert engine.get_confidence_blended_bias("zone2", 10.0) == 0.0

    async def test_nonzero_once_model_is_fitted(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", MIN_REGRESSION_SAMPLES + 20)

        bias = engine.get_confidence_blended_bias(
            "zone2", 10.0, hour_of_day=12, month=6, lights_on=True, light_pct=50.0, occupied=False,
        )
        assert bias != 0.0

    async def test_zero_when_query_missing_outdoor_temp(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await _log_varied_samples(engine, fake_coord, "zone2", MIN_REGRESSION_SAMPLES + 20)
        assert engine.get_confidence_blended_bias("zone2", None) == 0.0
