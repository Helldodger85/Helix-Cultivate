"""Test for v1.6.0 Part 6/7: the get_shadow_comparison_data WS command
returns Conditioning Room's real-vs-shadow hourly rows and the weather-event
log for the same window, filtered to the requested timeframe, reusing the
existing hourly_logs store with no new data-collection cadence.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.helix_cultivate import ws_get_shadow_comparison_data as _ws_handler
from custom_components.helix_cultivate.const import DOMAIN

# async_response wraps the real handler as a sync task-scheduler — unwrap it
# so the test can await the actual coroutine function directly.
ws_get_shadow_comparison_data = _ws_handler.__wrapped__


def _mock_hass(store):
    hass = MagicMock()
    hass.data = {DOMAIN: {"learning_store": store}}
    return hass


def _mock_connection():
    connection = MagicMock()
    connection.send_result = MagicMock()
    return connection


@pytest.mark.asyncio
class TestShadowComparisonWs:
    async def test_no_store_returns_empty_lists(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        connection = _mock_connection()

        await ws_get_shadow_comparison_data(hass, connection, {"id": 1, "timeframe": "24h"})

        connection.send_result.assert_called_once_with(1, {"rows": [], "weather_events": []})

    async def test_filters_rows_and_events_to_timeframe(self):
        now = dt_util.utcnow()
        old_ts = (now - timedelta(hours=100)).isoformat()
        recent_ts = (now - timedelta(hours=2)).isoformat()

        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=[
            {"zone": "conditioning", "ts": old_ts, "indoor_temp_c": 21.0,
             "shadow_predicted_indoor_temp_c": 21.5},
            {"zone": "conditioning", "ts": recent_ts, "indoor_temp_c": 22.0,
             "shadow_predicted_indoor_temp_c": 22.3},
        ])
        store.get_weather_events = MagicMock(return_value=[
            {"ts": old_ts, "message": "old event"},
            {"ts": recent_ts, "message": "recent event"},
        ])

        hass = _mock_hass(store)
        connection = _mock_connection()

        await ws_get_shadow_comparison_data(hass, connection, {"id": 2, "timeframe": "24h"})

        result = connection.send_result.call_args.args[1]
        assert len(result["rows"]) == 1
        assert result["rows"][0]["indoor_temp_c"] == 22.0
        assert result["rows"][0]["shadow_predicted_indoor_temp_c"] == 22.3
        assert len(result["weather_events"]) == 1
        assert result["weather_events"][0]["message"] == "recent event"

    async def test_7d_timeframe_includes_row_within_168_hours(self):
        now = dt_util.utcnow()
        within_7d = (now - timedelta(hours=100)).isoformat()

        store = MagicMock()
        store.get_hourly_logs = MagicMock(return_value=[
            {"zone": "conditioning", "ts": within_7d, "indoor_temp_c": 21.0,
             "shadow_predicted_indoor_temp_c": 21.5},
        ])
        store.get_weather_events = MagicMock(return_value=[])

        hass = _mock_hass(store)
        connection = _mock_connection()

        await ws_get_shadow_comparison_data(hass, connection, {"id": 3, "timeframe": "7d"})

        result = connection.send_result.call_args.args[1]
        assert len(result["rows"]) == 1
