"""Tests for v1.4.1 Part 3: a Drying-Room batch's day-count must keep
computing live (date.today() - drying_stage_start_date) after Space Now
Empty transfers it, the same way every other stage's day-count already
works — not freeze at whatever elapsed_days happened to read at the moment
of transfer.

Covers:
- space_now_empty() snapshots stage_manager.stage_start_date (the Drying
  stage's own true onset date) alongside the historical stage-durations
  snapshot, and never touches CONF_STAGE_START_DATE itself.
- drying_batch_elapsed_days() recomputes live from that unchanging
  reference point, correctly increasing across multiple simulated days.
- harvest_complete_drying_batch() overrides the frozen "drying" entry in
  the archived stage_durations with the real, final live day-count rather
  than the near-zero value captured at transfer time.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_DRYING_CYCLE_ID,
    CONF_DRYING_OCCUPIED,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_STAGE_START_DATE,
    CONF_ZONE2_CYCLE_ID,
    STAGE_DRYING,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

DOMAIN = "helix_cultivate"


def _bind(coord, *names):
    for name in names:
        setattr(coord, name, (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name))


class _FakeJournal:
    def __init__(self):
        self.batches: dict[str, dict] = {}
        self.async_pop_timelapse_images = AsyncMock(return_value=[])
        self.archive_cycle = AsyncMock(return_value="harvest_0001")
        self.async_set_previous_cycle_energy = AsyncMock(return_value={})

    async def open_drying_batch(self, cycle_id, snapshot):
        self.batches[cycle_id] = snapshot

    def get_open_drying_batch(self, cycle_id):
        return self.batches.get(cycle_id)

    async def close_open_drying_batch(self, cycle_id):
        self.batches.pop(cycle_id, None)


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {CONF_ENABLE_DRYING_ENVIRONMENT: True, CONF_ZONE2_CYCLE_ID: "cyc1"}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord._entry.options = {}
    coord.hass = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock(
        side_effect=lambda entry, options: coord._config.update(options)
    )
    coord.hass.bus.async_fire = MagicMock()

    journal = _FakeJournal()
    coord.hass.data = {DOMAIN: {"journal_store": journal}}

    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = STAGE_DRYING
    coord.stage_manager.actual_stage_durations = MagicMock(
        return_value={"germination": 5, "early_veg": 10, STAGE_DRYING: 0}
    )
    coord._notify_critical = AsyncMock()
    from collections import deque
    coord._vpd_history = deque()
    coord.vpd_target_min, coord.vpd_target_max = 0.8, 1.2
    coord._drying_cycle_kwh = 0.0
    coord._drying_cycle_cost = 0.0
    coord.data = {}

    _bind(
        coord,
        "space_now_empty",
        "harvest_complete_drying_batch",
        "is_drying_occupied",
        "is_zone2_occupied",
        "_vpd_in_range_pct",
        "_finalize_harvest_record",
        "_drying_batch_live_days",
        "drying_batch_elapsed_days",
    )
    return coord


@pytest.mark.asyncio
class TestSpaceNowEmptyNeverTouchesStageStartDate:
    async def test_transfer_does_not_write_stage_start_date(self, fake_coord):
        fake_coord.stage_manager.stage_start_date = date.today() - timedelta(days=2)
        await fake_coord.space_now_empty()
        assert CONF_STAGE_START_DATE not in fake_coord._entry.options
        assert CONF_STAGE_START_DATE not in fake_coord._config

    async def test_transfer_snapshots_the_real_drying_onset_date(self, fake_coord):
        onset = date.today() - timedelta(days=4)
        fake_coord.stage_manager.stage_start_date = onset
        await fake_coord.space_now_empty()
        journal = fake_coord.hass.data[DOMAIN]["journal_store"]
        snapshot = journal.get_open_drying_batch("cyc1")
        assert snapshot["drying_stage_start_date"] == onset.isoformat()


@pytest.mark.asyncio
class TestDryingBatchElapsedDaysComputesLive:
    async def test_none_when_not_occupied(self, fake_coord):
        assert fake_coord.drying_batch_elapsed_days() is None

    async def test_increases_correctly_across_multiple_simulated_days(self, fake_coord):
        """The same snapshot (fixed drying_stage_start_date) must yield a
        larger day-count the further "today" is from it — proving this is
        derived live on every read, not frozen at a single stored number."""
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_CYCLE_ID] = "cyc1"
        journal = fake_coord.hass.data[DOMAIN]["journal_store"]

        for days_ago in (1, 5, 10):
            journal.batches["cyc1"] = {
                "drying_stage_start_date": (date.today() - timedelta(days=days_ago)).isoformat(),
            }
            assert fake_coord.drying_batch_elapsed_days() == days_ago

    async def test_missing_start_date_returns_none_not_a_fabricated_number(self, fake_coord):
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_CYCLE_ID] = "cyc1"
        journal = fake_coord.hass.data[DOMAIN]["journal_store"]
        journal.batches["cyc1"] = {"stage_durations_snapshot": {"germination": 5}}
        assert fake_coord.drying_batch_elapsed_days() is None


@pytest.mark.asyncio
class TestHarvestCompleteUsesLiveFinalDayCount:
    async def test_archived_record_reflects_real_final_drying_days_not_transfer_time_snapshot(
        self, fake_coord
    ):
        onset = date.today() - timedelta(days=9)
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_CYCLE_ID] = "cyc1"
        journal = fake_coord.hass.data[DOMAIN]["journal_store"]
        journal.batches["cyc1"] = {
            # Frozen at transfer time — would have read ~0 days back then.
            "stage_durations_snapshot": {"germination": 5, "early_veg": 10, STAGE_DRYING: 0},
            "drying_stage_start_date": onset.isoformat(),
        }

        result = await fake_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["stage_durations"][STAGE_DRYING] == 9
        assert result["stage_durations"]["germination"] == 5

    async def test_missing_start_date_leaves_snapshot_untouched(self, fake_coord):
        """A batch transferred before this fix (v1.4.0) has no
        drying_stage_start_date — its archived record keeps the old
        transfer-time value rather than crashing or fabricating one."""
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_CYCLE_ID] = "cyc1"
        journal = fake_coord.hass.data[DOMAIN]["journal_store"]
        journal.batches["cyc1"] = {
            "stage_durations_snapshot": {"germination": 5, STAGE_DRYING: 0},
        }

        result = await fake_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["stage_durations"][STAGE_DRYING] == 0
