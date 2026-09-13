"""Tests for v1.5.0 Part 5: a permanent save via Plant Cycle's "Save Stage
Targets" button — for the stage CURRENTLY active — must take effect on the
very next control-loop tick, not deferred until a config-entry reload
completes or the next stage/cycle. Verified directly rather than assumed,
per the ticket's explicit instruction given this app's documented history
of persistence/draft-loss bugs in this exact area.

Root cause found and fixed: ws_update_stage_targets only wrote to
entry.options and relied entirely on the config-entry-update-triggered
reload to ever refresh the live coordinator's in-memory _config — unlike
ws_update_settings_fields, which already patches coordinator._config
immediately in addition to queuing the persisted write. Now both do.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.stage_manager import StageManager

DOMAIN = "helix_cultivate"


@pytest.fixture
def fake_hass_and_coord():
    coordinator = MagicMock()
    coordinator._config = {}

    entry = MagicMock(entry_id="entry123")
    entry.options = {}
    hass = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.config_entries.async_update_entry = MagicMock(
        side_effect=lambda e, options: setattr(e, "options", options)
    )
    hass.data = {DOMAIN: {"entry123": coordinator}}
    hass._background_tasks = []
    hass.async_create_background_task = (
        lambda coro, name, **kwargs: hass._background_tasks.append(asyncio.ensure_future(coro))
    )
    return hass, coordinator, entry


async def _call_ws_handler(handler, hass, connection, msg):
    handler(hass, connection, msg)
    await asyncio.gather(*hass._background_tasks)


@pytest.mark.asyncio
class TestSaveStageTargetsTakesEffectImmediately:
    async def test_patches_live_coordinator_config_not_only_entry_options(
        self, fake_hass_and_coord
    ):
        hass, coordinator, entry = fake_hass_and_coord
        connection = MagicMock()
        msg = {
            "id": 1, "entry_id": "entry123", "stage": "peak_flower",
            "targets": {"day_temp_c": 27.5},
        }

        await _call_ws_handler(helix_init.ws_update_stage_targets, hass, connection, msg)

        # Both the persisted entry.options AND the live in-memory
        # coordinator._config reflect the new value — not just the former,
        # which alone would only take effect once a reload completes.
        assert entry.options["stage_targets_peak_flower"]["day_temp_c"] == 27.5
        assert coordinator._config["stage_targets_peak_flower"]["day_temp_c"] == 27.5

    async def test_active_stages_profile_reflects_the_save_on_the_very_next_call(
        self, fake_hass_and_coord
    ):
        """The actual end-to-end proof: a real StageManager whose
        _current_stage is the one just saved sees the new value the very
        next time _profile() is called — no reload, no extra tick, no
        special-casing for "is this the active stage."
        """
        hass, coordinator, entry = fake_hass_and_coord
        connection = MagicMock()
        msg = {
            "id": 1, "entry_id": "entry123", "stage": "peak_flower",
            "targets": {"day_temp_c": 27.5, "day_vpd_max": 1.5},
        }

        mgr = StageManager(MagicMock(), coordinator._config)
        mgr._current_stage = "peak_flower"
        before = mgr._profile("peak_flower")["day_temp_c"]

        await _call_ws_handler(helix_init.ws_update_stage_targets, hass, connection, msg)
        # Simulates the coordinator's own tick calling update_config() with
        # its (now-patched) _config, exactly as _async_update_data() does
        # every cycle — no reload required for this to happen.
        mgr.update_config(coordinator._config)

        after = mgr._profile("peak_flower")["day_temp_c"]
        assert before != after
        assert after == 27.5
        assert mgr._profile("peak_flower")["day_vpd_max"] == 1.5

    async def test_partial_update_does_not_clobber_other_previously_saved_keys(
        self, fake_hass_and_coord
    ):
        hass, coordinator, entry = fake_hass_and_coord
        entry.options = {"stage_targets_peak_flower": {"day_temp_c": 26.0, "fan_speed_pct": 60}}
        coordinator._config = dict(entry.options)
        connection = MagicMock()
        msg = {
            "id": 1, "entry_id": "entry123", "stage": "peak_flower",
            "targets": {"day_temp_c": 27.5},
        }

        await _call_ws_handler(helix_init.ws_update_stage_targets, hass, connection, msg)

        assert coordinator._config["stage_targets_peak_flower"]["day_temp_c"] == 27.5
        assert coordinator._config["stage_targets_peak_flower"]["fan_speed_pct"] == 60

    async def test_coordinator_not_yet_loaded_still_persists_without_crashing(self):
        """A defensive edge case — coordinator missing from hass.data (e.g.
        mid-setup) must not prevent the persisted write from succeeding."""
        entry = MagicMock(entry_id="entry123")
        entry.options = {}
        hass = MagicMock()
        hass.config_entries.async_get_entry = MagicMock(return_value=entry)
        hass.config_entries.async_update_entry = MagicMock(
            side_effect=lambda e, options: setattr(e, "options", options)
        )
        hass.data = {DOMAIN: {}}
        hass._background_tasks = []
        hass.async_create_background_task = (
            lambda coro, name, **kwargs: hass._background_tasks.append(asyncio.ensure_future(coro))
        )
        connection = MagicMock()
        msg = {
            "id": 1, "entry_id": "entry123", "stage": "peak_flower",
            "targets": {"day_temp_c": 27.5},
        }

        await _call_ws_handler(helix_init.ws_update_stage_targets, hass, connection, msg)

        assert entry.options["stage_targets_peak_flower"]["day_temp_c"] == 27.5
        connection.send_result.assert_called_once_with(1, {"success": True})
