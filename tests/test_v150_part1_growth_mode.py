"""Tests for v1.5.0 Part 1: Growth Mode as a single, unified source of
truth (computed_photoperiod_hours() can never diverge from
_light_schedule_params(), since both resolve through the same
_light_schedule_params_for_stage() helper), and locked read-only while
CONF_ZONE2_OCCUPIED is True — enforced server-side (ws_update_settings_
fields), not just disabled in the UI.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import (
    CONF_AF_LIGHT_HOURS,
    CONF_GROWTH_MODE,
    CONF_PP_FLOWER_HOURS,
    CONF_PP_VEG_HOURS,
    GROWTH_MODE_AUTOFLOWER,
    GROWTH_MODE_PHOTOPERIOD,
    STAGE_DRYING,
    STAGE_EARLY_VEG,
    STAGE_GERMINATION,
    STAGE_LATE_VEG,
    STAGE_PEAK_FLOWER,
    STAGE_RIPENING,
    STAGE_SEEDLING,
    STAGE_STRETCH,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

DOMAIN = "helix_cultivate"


def _bind(coord, *names):
    for name in names:
        setattr(coord, name, (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name))


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    _bind(
        coord,
        "computed_photoperiod_hours",
        "_light_schedule_params_for_stage",
        "_light_schedule_params",
    )
    coord.stage_manager = MagicMock()
    return coord


class TestComputedPhotoperiodHoursSingleSourceOfTruth:
    def test_autoflower_ignores_stage_entirely(self, fake_coord):
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
        fake_coord._config[CONF_AF_LIGHT_HOURS] = 20.0
        for stage in (STAGE_GERMINATION, STAGE_STRETCH, STAGE_PEAK_FLOWER, STAGE_RIPENING):
            assert fake_coord.computed_photoperiod_hours(stage) == 20.0

    def test_photoperiod_veg_group(self, fake_coord):
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
        fake_coord._config[CONF_PP_VEG_HOURS] = 18.0
        fake_coord._config[CONF_PP_FLOWER_HOURS] = 12.0
        for stage in (STAGE_GERMINATION, STAGE_SEEDLING, STAGE_EARLY_VEG, STAGE_LATE_VEG):
            assert fake_coord.computed_photoperiod_hours(stage) == 18.0

    def test_photoperiod_flower_group(self, fake_coord):
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
        fake_coord._config[CONF_PP_VEG_HOURS] = 18.0
        fake_coord._config[CONF_PP_FLOWER_HOURS] = 12.0
        for stage in (STAGE_STRETCH, STAGE_PEAK_FLOWER, STAGE_RIPENING):
            assert fake_coord.computed_photoperiod_hours(stage) == 12.0

    def test_drying_always_zero_regardless_of_mode(self, fake_coord):
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
        fake_coord._config[CONF_AF_LIGHT_HOURS] = 20.0
        assert fake_coord.computed_photoperiod_hours(STAGE_DRYING) == 0.0

    def test_updates_immediately_when_growth_mode_changes(self, fake_coord):
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
        fake_coord._config[CONF_PP_VEG_HOURS] = 18.0
        assert fake_coord.computed_photoperiod_hours(STAGE_GERMINATION) == 18.0

        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_AUTOFLOWER
        fake_coord._config[CONF_AF_LIGHT_HOURS] = 20.0
        assert fake_coord.computed_photoperiod_hours(STAGE_GERMINATION) == 20.0

    def test_never_diverges_from_the_real_live_control_schedule(self, fake_coord):
        """The actual single-source-of-truth guarantee: whichever stage is
        CURRENTLY active, computed_photoperiod_hours(that stage) must equal
        exactly what _light_schedule_params() (the live control loop) is
        actually using — same call, same result, since both route through
        _light_schedule_params_for_stage()."""
        fake_coord._config[CONF_GROWTH_MODE] = GROWTH_MODE_PHOTOPERIOD
        fake_coord._config[CONF_PP_VEG_HOURS] = 16.5
        fake_coord._config[CONF_PP_FLOWER_HOURS] = 11.5
        for stage in (STAGE_EARLY_VEG, STAGE_STRETCH, STAGE_PEAK_FLOWER):
            fake_coord.stage_manager.current_stage = stage
            live_hours, _on_time, _key = fake_coord._light_schedule_params()
            assert fake_coord.computed_photoperiod_hours(stage) == live_hours


# ── Server-side lock enforcement (Part 1.2) ─────────────────────────────────


@pytest.fixture
def fake_hass_and_coord():
    coordinator = MagicMock()
    coordinator._config = {}
    coordinator.queue_option_write = MagicMock()
    coordinator.is_zone2_occupied = MagicMock(return_value=False)

    entry = MagicMock(entry_id="entry123")
    hass = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.data = {DOMAIN: {"entry123": coordinator}}
    hass._background_tasks = []
    hass.async_create_background_task = (
        lambda coro, name, **kwargs: hass._background_tasks.append(asyncio.ensure_future(coro))
    )
    return hass, coordinator


async def _call_ws_handler(handler, hass, connection, msg):
    handler(hass, connection, msg)
    await asyncio.gather(*hass._background_tasks)


@pytest.mark.asyncio
class TestGrowthModeLockedWhileOccupied:
    async def test_rejected_when_zone2_occupied(self, fake_hass_and_coord):
        hass, coordinator = fake_hass_and_coord
        coordinator.is_zone2_occupied = MagicMock(return_value=True)
        connection = MagicMock()
        msg = {"id": 1, "entry_id": "entry123", "fields": {"growth_mode": "autoflower"}}

        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)

        coordinator.queue_option_write.assert_not_called()
        assert "growth_mode" not in coordinator._config
        connection.send_error.assert_called_once()
        assert connection.send_error.call_args.args[1] == "growth_mode_locked"

    async def test_accepted_when_zone2_not_occupied(self, fake_hass_and_coord):
        """No dedicated Drying Room, or between cycles — both are simply
        is_zone2_occupied() == False, this handler doesn't need to know
        which topology it's in."""
        hass, coordinator = fake_hass_and_coord
        coordinator.is_zone2_occupied = MagicMock(return_value=False)
        connection = MagicMock()
        msg = {"id": 1, "entry_id": "entry123", "fields": {"growth_mode": "autoflower"}}

        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)

        coordinator.queue_option_write.assert_called_once_with("growth_mode", "autoflower")
        assert coordinator._config["growth_mode"] == "autoflower"
        connection.send_result.assert_called_once_with(1, {"success": True})

    async def test_editable_again_once_occupancy_clears(self, fake_hass_and_coord):
        """Simulates Space Now Empty (dedicated Drying Room) or a full
        stage-sequence completion (no dedicated room) clearing the flag —
        either way, is_zone2_occupied() flips back to False and the very
        next write succeeds."""
        hass, coordinator = fake_hass_and_coord
        connection = MagicMock()

        coordinator.is_zone2_occupied = MagicMock(return_value=True)
        msg = {"id": 1, "entry_id": "entry123", "fields": {"growth_mode": "autoflower"}}
        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)
        coordinator.queue_option_write.assert_not_called()

        coordinator.is_zone2_occupied = MagicMock(return_value=False)
        connection2 = MagicMock()
        msg2 = {"id": 2, "entry_id": "entry123", "fields": {"growth_mode": "photoperiod"}}
        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection2, msg2)
        coordinator.queue_option_write.assert_called_once_with("growth_mode", "photoperiod")

    async def test_other_fields_unaffected_by_growth_mode_lock(self, fake_hass_and_coord):
        """The lock is specific to growth_mode — an unrelated settings
        field in the same batch must still be accepted."""
        hass, coordinator = fake_hass_and_coord
        coordinator.is_zone2_occupied = MagicMock(return_value=True)
        connection = MagicMock()
        msg = {"id": 1, "entry_id": "entry123", "fields": {"zone2_plant_count": 4}}

        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)

        coordinator.queue_option_write.assert_called_once_with("zone2_plant_count", 4)
