"""Additional targeted tests closing out specific items from v1.4.0 Part
11's test list not already covered elsewhere in this session's test files:

- abort_cycle()/close_out_harvest() never touch Environmental Learning's
  stored data (Part 7.7's explicit requirement).
- Two cycle_ids can exist concurrently without cross-contamination — a
  fresh cycle started in Primary Grow Space while an older batch's
  cycle_id is still open in the Drying Room.
- Backup Heater remains independently controllable alongside an active
  Reverse Cycle unit.
- Live Actuator Response Testing is available regardless of occupancy
  (unlike Deep Calibration).
- Conditioning Room's cross-zone response test records a lag/magnitude
  dataset distinct from same-zone regression buckets.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_DRYING_CYCLE_ID,
    CONF_DRYING_OCCUPIED,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_ZONE2_CYCLE_ID,
    CONF_ZONE2_OCCUPIED,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.learning_engine import LearningEngine
from custom_components.helix_cultivate.learning_store import LearningStore

DOMAIN = "helix_cultivate"


class _FakeStorage:
    def __init__(self):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        import copy
        self._data = copy.deepcopy(data)


def _bind(coord, *names):
    for name in names:
        setattr(coord, name, (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name))


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


class TestLearningDataUntouchedByLifecycleResets:
    @pytest.fixture
    def fake_coord(self, fake_hass, learning_store):
        coord = MagicMock()
        coord.hass = fake_hass
        coord._config = {}
        coord._get = lambda key, default=None: coord._config.get(key, default)
        coord._entry = MagicMock(entry_id="entry123")
        coord._entry.options = {}
        coord.hass.config_entries.async_update_entry = MagicMock()
        coord.hass.bus.async_fire = MagicMock()
        coord.stage_manager = MagicMock()
        coord.stage_manager.return_to_not_started = MagicMock()
        coord.stage_manager.current_stage = "not_started"
        _bind(coord, "abort_cycle")
        return coord

    @pytest.mark.asyncio
    async def test_abort_cycle_does_not_touch_learning_store(self, fake_coord, learning_store):
        await learning_store.update_regression_bucket("zone2", "10to15", 2.0)
        await learning_store.set_active_test({"type": "deep_calibration", "zone": "zone2"})
        before_buckets = dict(learning_store._data["regression_buckets"])
        before_test = learning_store.get_active_test()

        await fake_coord.abort_cycle()

        assert learning_store._data["regression_buckets"] == before_buckets
        assert learning_store.get_active_test() == before_test


class TestConcurrentCycleIds:
    @pytest.fixture
    def fake_coord(self, fake_hass, learning_store):
        coord = MagicMock()
        coord.hass = fake_hass
        coord._config = {CONF_ENABLE_DRYING_ENVIRONMENT: True}
        coord._get = lambda key, default=None: coord._config.get(key, default)
        coord._entry = MagicMock(entry_id="entry123")
        coord._entry.options = {}
        coord.hass.config_entries.async_update_entry = MagicMock(
            side_effect=lambda entry, options: coord._config.update(options)
        )
        coord.hass.bus.async_fire = MagicMock()
        coord.stage_manager = MagicMock()
        coord.stage_manager.actual_stage_durations = MagicMock(return_value={"drying": 3})
        coord.stage_manager.start_new_cycle = MagicMock()

        journal = MagicMock()
        journal.open_drying_batch = AsyncMock()
        journal.get_open_drying_batch = MagicMock(
            return_value={"stage_durations_snapshot": {"drying": 3}}
        )
        journal.close_open_drying_batch = AsyncMock()
        journal.async_pop_timelapse_images = AsyncMock(return_value=[])
        journal.archive_cycle = AsyncMock(return_value="harvest_0003")
        journal.async_set_previous_cycle_energy = AsyncMock(return_value={})
        coord.hass.data.setdefault(DOMAIN, {})["journal_store"] = journal
        coord._journal = journal
        coord._notify_critical = AsyncMock()
        from collections import deque
        coord._vpd_history = deque()
        coord.vpd_target_min, coord.vpd_target_max = 0.8, 1.2
        coord._drying_cycle_kwh = 2.0
        coord._drying_cycle_cost = 0.5
        coord.data = {}

        _bind(coord, "start_cycle", "space_now_empty", "harvest_complete_drying_batch",
              "is_zone2_occupied", "is_drying_occupied", "_vpd_in_range_pct",
              "_finalize_harvest_record")
        return coord

    @pytest.mark.asyncio
    async def test_fresh_cycle_in_zone2_does_not_disturb_open_drying_batch(self, fake_coord):
        # First batch starts, then transfers to Drying.
        await fake_coord.start_cycle("photoperiod", "2026-01-01", "germination")
        first_cycle_id = fake_coord._config[CONF_ZONE2_CYCLE_ID]
        await fake_coord.space_now_empty()
        drying_cycle_id = fake_coord._config[CONF_DRYING_CYCLE_ID]
        assert drying_cycle_id == first_cycle_id

        # A second, brand-new cycle now starts in the freed Primary Grow Space.
        await fake_coord.start_cycle("photoperiod", "2026-02-01", "germination")
        second_cycle_id = fake_coord._config[CONF_ZONE2_CYCLE_ID]

        assert second_cycle_id != first_cycle_id
        # The Drying Room's own cycle_id record is untouched by the new cycle.
        assert fake_coord._config[CONF_DRYING_CYCLE_ID] == first_cycle_id
        assert fake_coord._config[CONF_ZONE2_OCCUPIED] is True
        assert fake_coord._config[CONF_DRYING_OCCUPIED] is True

    @pytest.mark.asyncio
    async def test_harvest_complete_for_old_batch_does_not_touch_new_cycle(self, fake_coord):
        await fake_coord.start_cycle("photoperiod", "2026-01-01", "germination")
        first_cycle_id = fake_coord._config[CONF_ZONE2_CYCLE_ID]
        await fake_coord.space_now_empty()
        await fake_coord.start_cycle("photoperiod", "2026-02-01", "germination")
        second_cycle_id = fake_coord._config[CONF_ZONE2_CYCLE_ID]

        result = await fake_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["cycle_id"] == first_cycle_id
        assert fake_coord._config[CONF_ZONE2_CYCLE_ID] == second_cycle_id
        assert fake_coord._config[CONF_ZONE2_OCCUPIED] is True
        assert fake_coord._config[CONF_DRYING_OCCUPIED] is False


class TestLiveActuatorTestAvailableRegardlessOfOccupancy:
    @pytest.fixture
    def fake_coord(self, fake_hass, learning_store):
        coord = MagicMock()
        coord.hass = fake_hass
        coord._config = {}
        coord._get = lambda key, default=None: coord._config.get(key, default)
        coord.is_zone2_occupied = MagicMock(return_value=True)
        coord.is_drying_occupied = MagicMock(return_value=True)
        coord.conditioning_room_dependent_zones = MagicMock(return_value=["zone2"])
        return coord

    @pytest.mark.asyncio
    async def test_live_test_starts_even_when_zone_occupied(self, fake_coord):
        engine = LearningEngine(fake_coord)
        test = await engine.start_live_actuator_test("zone2", thermostat_controlled=True)
        assert test["zone"] == "zone2"
        assert test["thermostat_controlled"] is True


class TestCrossZoneResponseDistinctFromSameZoneData:
    @pytest.mark.asyncio
    async def test_cross_zone_and_regression_buckets_are_independent_datasets(self, learning_store):
        await learning_store.update_regression_bucket("zone2", "10to15", 2.0)
        await learning_store.update_cross_zone_response("zone2", lag_min=12.0, magnitude_ratio=0.6)

        same_zone = learning_store.get_regression_bucket("zone2", "10to15")
        cross_zone = learning_store.get_cross_zone_response("zone2")

        assert same_zone is not None and cross_zone is not None
        assert same_zone != cross_zone
        assert cross_zone["mean_lag_min"] == 12.0
        assert cross_zone["mean_magnitude_ratio"] == 0.6

    @pytest.mark.asyncio
    async def test_cross_zone_response_accumulates_running_mean(self, learning_store):
        await learning_store.update_cross_zone_response("zone2", lag_min=10.0, magnitude_ratio=0.5)
        await learning_store.update_cross_zone_response("zone2", lag_min=20.0, magnitude_ratio=0.7)

        record = learning_store.get_cross_zone_response("zone2")
        assert record["count"] == 2
        assert record["mean_lag_min"] == pytest.approx(15.0)


class TestBackupHeaterIndependentOfReverseCycle:
    @pytest.mark.asyncio
    async def test_backup_heater_can_engage_while_reverse_cycle_unit_is_heating(self):
        """Part 5.4: Backup Heater is never a substitute for Reverse Cycle
        in the control logic — both can be genuinely needed simultaneously."""
        from datetime import timedelta
        from custom_components.helix_cultivate.climate_engine import (
            BACKUP_HEATER_DWELL_MIN, HVAC_MODE_HEAT, ClimateEngine,
        )
        from homeassistant.util import dt as dt_util

        mock_coord = MagicMock()
        mock_coord.temp_setpoint = 24.0
        mock_coord._backup_heater_falling_behind_since = None
        engine = ClimateEngine(mock_coord)
        engine._get = lambda key, default=None: {"zone1_backup_heater": "switch.backup"}.get(key, default)
        engine._outdoor_temp_c = MagicMock(return_value=2.0)
        engine._backup_heater_threshold = MagicMock(return_value=5.0)
        engine._set_switch = AsyncMock()

        # Reverse Cycle unit is actively in HEAT mode (primary_rc_mode) but
        # still falling behind setpoint — after the dwell, backup should
        # stage on ALONGSIDE it, not instead of it.
        start = dt_util.utcnow()
        result = await engine._stage_backup_heater(
            current_temp=None, lung_temp=18.0, primary_heat_on=False, primary_rc_mode=HVAC_MODE_HEAT,
        )
        assert result is False  # not yet past dwell

        past_dwell = start + timedelta(minutes=BACKUP_HEATER_DWELL_MIN + 1)
        import custom_components.helix_cultivate.climate_engine as ce_module
        import unittest.mock as mock
        with mock.patch.object(ce_module.dt_util, "utcnow", return_value=past_dwell):
            result = await engine._stage_backup_heater(None, 18.0, False, HVAC_MODE_HEAT)

        assert result is True
        engine._set_switch.assert_awaited_with("switch.backup", True, role="zone1_backup_heater")
