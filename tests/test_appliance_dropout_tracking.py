"""Tests for coordinator._record_command_failure (Part 1): an exhausted-
retry actuator command failure must feed the same dwell-and-notify tracking
_check_appliance_dropout uses for entities the HA state machine reports
unavailable — not a second, separate alerting system. Also covers the fix
for _appliance_dropout_alerted never being initialised in __init__ (would
have raised AttributeError on the very first real dropout check).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.coordinator import HelixCoordinator

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_coord(monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: FIXED_NOW)

    coord = MagicMock()
    coord._appliance_unavail_since = {}
    coord._appliance_dropout_alerted = {}
    coord._notify_critical = AsyncMock()
    coord.hass = MagicMock()
    coord.hass.async_create_task = MagicMock(side_effect=lambda coro: coro.close())
    coord.hass.states.get = MagicMock(return_value=None)

    coord._record_command_failure = lambda role, eid: HelixCoordinator._record_command_failure(coord, role, eid)
    coord._check_appliance_dropout = lambda role, eid: HelixCoordinator._check_appliance_dropout(coord, role, eid)
    coord._raise_appliance_dropout_notification = lambda role, eid: HelixCoordinator._raise_appliance_dropout_notification(coord, role, eid)
    return coord


def test_first_failure_starts_dwell_without_alerting(fake_coord):
    fake_coord._record_command_failure("zone1_heater", "switch.heater")

    assert fake_coord._appliance_unavail_since["zone1_heater"] == FIXED_NOW
    assert fake_coord._appliance_dropout_alerted.get("zone1_heater", False) is False
    fake_coord.hass.async_create_task.assert_not_called()


def test_alert_fires_once_after_5_minute_dwell(fake_coord, monkeypatch):
    fake_coord._record_command_failure("zone1_heater", "switch.heater")

    later = FIXED_NOW + timedelta(minutes=5, seconds=1)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: later)
    fake_coord._record_command_failure("zone1_heater", "switch.heater")

    assert fake_coord._appliance_dropout_alerted["zone1_heater"] is True
    fake_coord.hass.async_create_task.assert_called_once()

    # A further failure within the same episode must not re-fire.
    fake_coord._record_command_failure("zone1_heater", "switch.heater")
    fake_coord.hass.async_create_task.assert_called_once()


def test_command_failure_and_state_unavailable_share_the_same_dwell(fake_coord, monkeypatch):
    """A command failure starts the dwell; the entity then also reads back
    as unavailable via the normal state-based check — both must accumulate
    into the SAME timer, not two independent ones."""
    fake_coord._record_command_failure("zone2_ac", "switch.ac")

    later = FIXED_NOW + timedelta(minutes=5, seconds=1)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: later)
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="unavailable"))

    dropped_out = fake_coord._check_appliance_dropout("zone2_ac", "switch.ac")

    assert dropped_out is True
    fake_coord.hass.async_create_task.assert_called_once()


def test_recovery_resets_dwell_for_both_paths(fake_coord, monkeypatch):
    fake_coord._record_command_failure("zone1_heater", "switch.heater")

    # Entity comes back — _check_appliance_dropout's own reset branch clears
    # the dwell shared by both tracking paths.
    fake_coord.hass.states.get = MagicMock(return_value=MagicMock(state="on"))
    fake_coord._check_appliance_dropout("zone1_heater", "switch.heater")

    assert fake_coord._appliance_unavail_since["zone1_heater"] is None
    assert fake_coord._appliance_dropout_alerted["zone1_heater"] is False
