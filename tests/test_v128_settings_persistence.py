"""Tests for Part 3: the five v1.2.8 features' new settings controls must
persist correctly via the same update_settings_fields WS handler ->
queue_option_write() path every other explicit-Save settings field uses —
previously none of these five had any settings-flow or gear-icon control
surface at all.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import (
    DEFAULT_DEW_POINT_MARGIN_C,
    DEFAULT_LIGHT_HIGH_TEMP_DIM_C,
    DEFAULT_PREHEAT_LEAD_MIN,
    DEFAULT_STAGE_WARNING_LEAD_DAYS,
    DEFAULT_WIND_SWEEP_ENABLED,
)

DOMAIN = "helix_cultivate"


@pytest.fixture
def fake_hass_and_coord():
    coordinator = MagicMock()
    coordinator._config = {}
    coordinator.queue_option_write = MagicMock()

    entry = MagicMock(entry_id="entry123")
    hass = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.data = {DOMAIN: {"entry123": coordinator}}
    # ws_update_settings_fields is wrapped by @websocket_api.async_response,
    # which schedules the real handler via hass.async_create_background_task
    # rather than returning an awaitable directly (it's designed to be
    # invoked by HA's WS dispatcher, not called directly). Capture the
    # scheduled task here so the test can await it explicitly.
    hass._background_tasks = []
    hass.async_create_background_task = (
        lambda coro, name, **kwargs: hass._background_tasks.append(asyncio.ensure_future(coro))
    )
    return hass, coordinator


async def _call_ws_handler(handler, hass, connection, msg):
    """Invoke an @websocket_api.async_response-wrapped handler and wait for
    the background task it schedules to actually finish."""
    handler(hass, connection, msg)
    await asyncio.gather(*hass._background_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("field_key,value", [
    ("light_high_temp_dim_c", 27.5),
    ("wind_sweep_enabled", True),
    ("dew_point_margin_c", 3.0),
    ("preheat_lead_min", 20),
    ("stage_warning_lead_days", 5),
])
async def test_v128_field_persists_via_queue_option_write(fake_hass_and_coord, field_key, value):
    hass, coordinator = fake_hass_and_coord
    connection = MagicMock()
    msg = {"id": 1, "entry_id": "entry123", "fields": {field_key: value}}

    await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)

    coordinator.queue_option_write.assert_called_once_with(field_key, value)
    assert coordinator._config[field_key] == value
    connection.send_result.assert_called_once_with(1, {"success": True})


@pytest.mark.asyncio
async def test_unknown_field_key_is_rejected(fake_hass_and_coord):
    hass, coordinator = fake_hass_and_coord
    connection = MagicMock()
    msg = {"id": 1, "entry_id": "entry123", "fields": {"not_a_real_field": 1}}

    await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)

    coordinator.queue_option_write.assert_not_called()
    assert "not_a_real_field" not in coordinator._config


def test_v128_defaults_are_unchanged_by_this_session():
    """Part 3 explicitly must not change any of the coded defaults — only
    make them visible/editable."""
    assert DEFAULT_LIGHT_HIGH_TEMP_DIM_C == 29.0
    assert DEFAULT_WIND_SWEEP_ENABLED is False
    assert DEFAULT_DEW_POINT_MARGIN_C == 2.0
    assert DEFAULT_PREHEAT_LEAD_MIN == 15.0
    assert DEFAULT_STAGE_WARNING_LEAD_DAYS == 3
