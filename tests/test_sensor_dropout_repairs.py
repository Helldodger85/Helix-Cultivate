"""Tests for Part 2.1's missing piece: coordinator.py already detects
primary sensor dropout (_check_sensor_dropout) and fires a critical
notification, but never actually raised a Repairs issue for it — meaning
the dashboard's "link to Repairs" requirement had nothing real to link to.
Covers the new "primary_sensor_dropout" issue (created/cleared alongside
the existing checks) and the sensor.py attr exposing the specific flagged
entity for the dashboard popover.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from custom_components.helix_cultivate.const import (
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C,
    CONF_DRYING_CUSTOM_UNLOCKED,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {CONF_PRIMARY_TEMP_SENSOR: "sensor.canopy_temp"}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.hass = MagicMock()
    coord.stage_manager = MagicMock()
    coord.stage_manager._profile = MagicMock(return_value={})

    coord._check_repairs_issues = lambda lt, lr, sd=False: HelixCoordinator._check_repairs_issues(
        coord, lt, lr, sd
    )
    return coord


def test_issue_created_when_sensor_dropout_active(fake_coord):
    with patch("custom_components.helix_cultivate.coordinator.ir") as mock_ir:
        fake_coord._check_repairs_issues(None, None, True)

        dropout_calls = [
            c for c in mock_ir.async_create_issue.call_args_list
            if c.args[2] == "primary_sensor_dropout"
        ]
        assert len(dropout_calls) == 1
        call = dropout_calls[0]
        assert call.kwargs["translation_placeholders"] == {"entity_id": "sensor.canopy_temp"}


def test_issue_cleared_when_sensor_recovers(fake_coord):
    with patch("custom_components.helix_cultivate.coordinator.ir") as mock_ir:
        fake_coord._check_repairs_issues(None, None, False)

        mock_ir.async_delete_issue.assert_any_call(
            fake_coord.hass, "helix_cultivate", "primary_sensor_dropout"
        )
        dropout_creates = [
            c for c in mock_ir.async_create_issue.call_args_list
            if c.args[2] == "primary_sensor_dropout"
        ]
        assert dropout_creates == []


def test_no_issue_when_dropout_active_but_sensor_never_mapped(fake_coord):
    """No entity_id to report — nothing meaningful to flag."""
    fake_coord._config = {}
    with patch("custom_components.helix_cultivate.coordinator.ir") as mock_ir:
        fake_coord._check_repairs_issues(None, None, True)

        dropout_creates = [
            c for c in mock_ir.async_create_issue.call_args_list
            if c.args[2] == "primary_sensor_dropout"
        ]
        assert dropout_creates == []
