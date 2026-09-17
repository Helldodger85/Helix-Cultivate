"""Tests for v1.6.0 Part 7: the weather-event log.

7.1: Genuinely new logging machinery (not a reuse of hourly_logs) that
detects and logs notable discrete forecast changes — precipitation
probability crossing a threshold, or a significant forecast temperature
swing — as timestamped, human-readable entries. Edge-triggered: a
sustained condition logs once, not again every tick until it clears.

7.2: Each logged event is correlated with the Shadow prediction at that
exact moment.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.learning_engine import LearningEngine
from custom_components.helix_cultivate.learning_store import LearningStore


def _real_store():
    """A real LearningStore with persistence stubbed out, so
    get_weather_event_state/get_weather_events reflect genuine in-memory
    state transitions rather than a MagicMock's default behavior."""
    store = LearningStore.__new__(LearningStore)
    import copy
    from custom_components.helix_cultivate.learning_store import EMPTY_LEARNING_STORE
    store._data = copy.deepcopy(EMPTY_LEARNING_STORE)
    store._save = AsyncMock()
    return store


@pytest.mark.asyncio
class TestWeatherEventDetection:
    async def test_no_event_when_conditions_are_unremarkable(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=10.0, shadow_prediction=None,
        )

        assert store.get_weather_events() == []

    async def test_precipitation_crossing_threshold_logs_event(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=75.0, shadow_prediction=None,
        )

        events = store.get_weather_events()
        assert len(events) == 1
        assert "Rain expected" in events[0]["message"]

    async def test_precipitation_event_does_not_repeat_while_still_active(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=75.0, shadow_prediction=None,
        )
        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=80.0, shadow_prediction=None,
        )

        assert len(store.get_weather_events()) == 1

    async def test_precipitation_event_re_fires_after_clearing(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=75.0, shadow_prediction=None,
        )
        # Condition clears.
        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=20.0, shadow_prediction=None,
        )
        # Then re-crosses the threshold.
        await engine.maybe_log_weather_event(
            future_temp_c=15.0, current_outdoor_temp_c=14.0,
            precipitation_probability=90.0, shadow_prediction=None,
        )

        assert len(store.get_weather_events()) == 2

    async def test_significant_temperature_swing_logs_event(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=20.0, current_outdoor_temp_c=10.0,  # +10C swing
            precipitation_probability=None, shadow_prediction=None,
        )

        events = store.get_weather_events()
        assert len(events) == 1
        assert "temperature rise" in events[0]["message"]
        assert "+10.0" in events[0]["message"]

    async def test_temperature_drop_uses_drop_wording(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=5.0, current_outdoor_temp_c=15.0,  # -10C swing
            precipitation_probability=None, shadow_prediction=None,
        )

        events = store.get_weather_events()
        assert "temperature drop" in events[0]["message"]

    async def test_small_temperature_delta_is_not_notable(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=16.0, current_outdoor_temp_c=14.0,  # +2C, below threshold
            precipitation_probability=None, shadow_prediction=None,
        )

        assert store.get_weather_events() == []

    async def test_event_correlated_with_shadow_prediction_at_that_moment(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=20.0, current_outdoor_temp_c=10.0,
            precipitation_probability=None,
            shadow_prediction={
                "blended_bias_c": 1.3, "predicted_indoor_temp_c": 23.7,
            },
        )

        event = store.get_weather_events()[0]
        assert event["correlated_bias_c"] == pytest.approx(1.3)
        assert event["correlated_predicted_temp_c"] == pytest.approx(23.7)

    async def test_none_forecast_values_are_silently_skipped(self, mock_coord):
        store = _real_store()
        mock_coord.hass.data = {"helix_cultivate": {"learning_store": store}}
        engine = LearningEngine(mock_coord)

        await engine.maybe_log_weather_event(
            future_temp_c=None, current_outdoor_temp_c=None,
            precipitation_probability=None, shadow_prediction=None,
        )

        assert store.get_weather_events() == []

    async def test_inert_when_store_unavailable(self, mock_coord):
        mock_coord.hass.data = {"helix_cultivate": {}}
        engine = LearningEngine(mock_coord)

        # Must not raise.
        await engine.maybe_log_weather_event(
            future_temp_c=20.0, current_outdoor_temp_c=10.0,
            precipitation_probability=90.0, shadow_prediction=None,
        )
