"""Tests for the generic actuator command retry wrapper (Part 1):
ClimateEngine._call_service_with_retry — up to 2 retries with backoff on a
failed service call, and routing an exhausted-retry failure into the
existing appliance-dropout notification pathway (coordinator.
_record_command_failure) rather than a new, separate alerting system.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import custom_components.helix_cultivate.climate_engine as climate_engine_module


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Retries sleep for real seconds between attempts — replace with a
    no-op so these tests run instantly instead of waiting ~7s each."""
    monkeypatch.setattr(climate_engine_module.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_succeeds_on_first_attempt_no_retry(engine, mock_coord):
    mock_coord.hass.services.async_call = AsyncMock()

    ok = await engine._call_service_with_retry(
        "switch", "turn_on", {"entity_id": "switch.heater"}, role="zone1_heater"
    )

    assert ok is True
    assert mock_coord.hass.services.async_call.await_count == 1
    mock_coord._record_command_failure.assert_not_called()


@pytest.mark.asyncio
async def test_retries_up_to_2_times_then_succeeds(engine, mock_coord):
    mock_coord.hass.services.async_call = AsyncMock(
        side_effect=[Exception("blip"), Exception("blip again"), None]
    )

    ok = await engine._call_service_with_retry(
        "fan", "set_percentage", {"entity_id": "fan.exhaust", "percentage": 50}, role="exhaust"
    )

    assert ok is True
    assert mock_coord.hass.services.async_call.await_count == 3
    mock_coord._record_command_failure.assert_not_called()


@pytest.mark.asyncio
async def test_sleeps_with_correct_backoff_between_retries(engine, mock_coord, monkeypatch):
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(climate_engine_module.asyncio, "sleep", fake_sleep)
    mock_coord.hass.services.async_call = AsyncMock(
        side_effect=[Exception("blip"), Exception("blip again"), None]
    )

    await engine._call_service_with_retry(
        "fan", "turn_off", {"entity_id": "fan.exhaust"}, role="exhaust"
    )

    assert sleep_calls == [2.0, 5.0]


@pytest.mark.asyncio
async def test_exhausted_retries_routes_to_appliance_dropout_pathway_not_new_alert(engine, mock_coord):
    mock_coord.hass.services.async_call = AsyncMock(side_effect=Exception("still down"))

    ok = await engine._call_service_with_retry(
        "switch", "turn_on", {"entity_id": "switch.heater"}, role="zone1_heater"
    )

    assert ok is False
    assert mock_coord.hass.services.async_call.await_count == 3  # 1 + 2 retries
    # Fed into the existing dropout watchdog dwell-and-notify tracking —
    # never a direct, separate _notify_critical call from the wrapper itself.
    mock_coord._record_command_failure.assert_called_once_with("zone1_heater", "switch.heater")
    mock_coord._notify_critical.assert_not_called()


@pytest.mark.asyncio
async def test_set_switch_routes_through_retry_wrapper(engine, mock_coord):
    mock_coord.hass.states.get.return_value = None  # any non-None value works; None short-circuits
    mock_coord.hass.states.get = lambda eid: object()  # simulate entity exists
    mock_coord.hass.services.async_call = AsyncMock(side_effect=Exception("blip"))
    mock_coord._check_appliance_dropout.return_value = False

    await engine._set_switch("switch.heater", True, role="zone1_heater")

    assert mock_coord.hass.services.async_call.await_count == 3
    mock_coord._record_command_failure.assert_called_once_with("zone1_heater", "switch.heater")
