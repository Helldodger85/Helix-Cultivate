"""Tests for v1.4.0 Parts 3 & 4: zone occupancy decoupled from cycle_state/
stage tracking, and Conditioning Room's Deep Calibration eligibility
corrected to depend on every zone that actually depends on it (Part 3),
not its own always-empty occupancy or the global cycle_state.

Covers: is_zone2_occupied/is_drying_occupied, the explicit per-zone
dependency flags and eligibility rule, space_now_empty()'s atomic transfer
and topology guard, and harvest_complete_drying_batch()'s independence
from whatever Primary Grow Space is doing concurrently.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_DRYING_CYCLE_ID,
    CONF_DRYING_DEPENDS_ON_CONDITIONING,
    CONF_DRYING_OCCUPIED,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_ZONE2_CYCLE_ID,
    CONF_ZONE2_DEPENDS_ON_CONDITIONING,
    CONF_ZONE2_OCCUPIED,
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
        "is_zone2_occupied",
        "is_drying_occupied",
        "conditioning_room_dependent_zones",
        "is_conditioning_room_calibration_eligible",
    )
    return coord


class TestOccupancyReaders:
    def test_zone2_defaults_unoccupied(self, fake_coord):
        assert fake_coord.is_zone2_occupied() is False

    def test_zone2_occupied_when_flag_set(self, fake_coord):
        fake_coord._config[CONF_ZONE2_OCCUPIED] = True
        assert fake_coord.is_zone2_occupied() is True

    def test_drying_always_false_without_dedicated_room(self, fake_coord):
        """Even if the raw flag were somehow True, without
        enable_drying_environment there is no separate room at all."""
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = False
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        assert fake_coord.is_drying_occupied() is False

    def test_drying_reflects_flag_when_dedicated_room_exists(self, fake_coord):
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        assert fake_coord.is_drying_occupied() is True


class TestDependencyFlagsAndEligibility:
    def test_default_dependency_is_conservative(self, fake_coord):
        """Part 3.1: whenever a grower hasn't made an explicit choice, the
        default is "depends on Conditioning Room" — the safe assumption."""
        assert fake_coord.conditioning_room_dependent_zones() == ["zone2"]

    def test_drying_excluded_from_dependents_without_dedicated_room(self, fake_coord):
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = False
        fake_coord._config[CONF_DRYING_DEPENDS_ON_CONDITIONING] = True
        assert fake_coord.conditioning_room_dependent_zones() == ["zone2"]

    def test_drying_included_when_dedicated_and_dependent(self, fake_coord):
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_DEPENDS_ON_CONDITIONING] = True
        assert set(fake_coord.conditioning_room_dependent_zones()) == {"zone2", "drying"}

    def test_eligible_when_all_dependents_unoccupied(self, fake_coord):
        fake_coord._config[CONF_ZONE2_OCCUPIED] = False
        assert fake_coord.is_conditioning_room_calibration_eligible() is True

    def test_ineligible_when_dependent_zone2_occupied(self, fake_coord):
        fake_coord._config[CONF_ZONE2_OCCUPIED] = True
        assert fake_coord.is_conditioning_room_calibration_eligible() is False

    def test_ineligible_when_zone2_free_but_dependent_drying_room_occupied(self, fake_coord):
        """The exact scenario Part 3 exists to close off: Primary Grow
        Space is unoccupied (calibration would look "safe" under the old,
        wrong self-occupancy check) but a dependent Drying Room is still
        curing material — Conditioning Room must still be restricted."""
        fake_coord._config[CONF_ZONE2_OCCUPIED] = False
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_DEPENDS_ON_CONDITIONING] = True

        assert fake_coord.is_conditioning_room_calibration_eligible() is False

    def test_eligible_when_dependent_drying_room_freed(self, fake_coord):
        fake_coord._config[CONF_ZONE2_OCCUPIED] = False
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_OCCUPIED] = False
        fake_coord._config[CONF_DRYING_DEPENDS_ON_CONDITIONING] = True

        assert fake_coord.is_conditioning_room_calibration_eligible() is True

    def test_eligible_when_drying_room_occupied_but_independent(self, fake_coord):
        """A Drying Room with its own independent heater/AC/dehumidifier
        does not gate Conditioning Room at all, occupied or not."""
        fake_coord._config[CONF_ZONE2_OCCUPIED] = False
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_coord._config[CONF_DRYING_DEPENDS_ON_CONDITIONING] = False

        assert fake_coord.is_conditioning_room_calibration_eligible() is True

    def test_eligibility_ignores_cycle_state_entirely(self, fake_coord):
        """Confirms the actual bug fix: eligibility must never be derived
        from cycle_state (an earlier, wrong design would gate on
        Conditioning Room's own occupancy — always trivially empty)."""
        fake_coord._config["cycle_state"] = "active"
        fake_coord._config[CONF_ZONE2_OCCUPIED] = False
        assert fake_coord.is_conditioning_room_calibration_eligible() is True


@pytest.fixture
def fake_full_coord():
    """A more complete fake for space_now_empty()/harvest_complete_drying_batch(),
    matching the style of test_close_out_harvest_energy_archive.py's fixture."""
    coord = MagicMock()
    coord._config = {CONF_ZONE2_CYCLE_ID: "cycle_abc123"}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord._entry = MagicMock(entry_id="entry123")
    coord._entry.options = {}
    coord.hass = MagicMock()
    coord.hass.bus.async_fire = MagicMock()
    coord.hass.config_entries.async_update_entry = MagicMock()
    coord.stage_manager = MagicMock()
    coord.stage_manager.actual_stage_durations = MagicMock(
        return_value={"germination": 5, "early_veg": 10}
    )

    journal = MagicMock()
    journal.open_drying_batch = AsyncMock()
    journal.get_open_drying_batch = MagicMock(
        return_value={"stage_durations_snapshot": {"germination": 5, "early_veg": 10}}
    )
    journal.close_open_drying_batch = AsyncMock()
    journal.async_pop_timelapse_images = AsyncMock(return_value=[])
    journal.archive_cycle = AsyncMock(return_value="harvest_0002")
    journal.async_set_previous_cycle_energy = AsyncMock(return_value={})
    coord.hass.data = {DOMAIN: {"journal_store": journal}}
    coord._journal = journal

    coord._notify_critical = AsyncMock()
    from collections import deque
    coord._vpd_history = deque()
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2
    coord._drying_cycle_kwh = 1.5
    coord._drying_cycle_cost = 0.4
    coord.data = {}

    _bind(
        coord,
        "is_zone2_occupied",
        "is_drying_occupied",
        "space_now_empty",
        "harvest_complete_drying_batch",
        "_vpd_in_range_pct",
        "_finalize_harvest_record",
    )
    return coord


@pytest.mark.asyncio
class TestSpaceNowEmpty:
    async def test_raises_without_dedicated_drying_room(self, fake_full_coord):
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = False
        with pytest.raises(ValueError):
            await fake_full_coord.space_now_empty()

    async def test_transfers_occupancy_atomically(self, fake_full_coord):
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_ZONE2_OCCUPIED] = True

        await fake_full_coord.space_now_empty()

        call_kwargs = fake_full_coord.hass.config_entries.async_update_entry.call_args.kwargs
        assert call_kwargs["options"][CONF_ZONE2_OCCUPIED] is False
        assert call_kwargs["options"][CONF_DRYING_OCCUPIED] is True
        assert call_kwargs["options"][CONF_DRYING_CYCLE_ID] == "cycle_abc123"

    async def test_does_not_touch_cycle_id_or_stage_tracking(self, fake_full_coord):
        """Part 4.2: this is a transfer of occupancy, not a reset — the
        batch's cycle_id and stage tracking keep advancing exactly as
        before. stage_manager.return_to_not_started must never be called
        by this action (that would be close_out_harvest's job, not this)."""
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True

        await fake_full_coord.space_now_empty()

        fake_full_coord.stage_manager.return_to_not_started.assert_not_called()
        assert fake_full_coord._config[CONF_ZONE2_CYCLE_ID] == "cycle_abc123"

    async def test_snapshots_stage_durations_for_later_close_out(self, fake_full_coord):
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True

        await fake_full_coord.space_now_empty()

        fake_full_coord._journal.open_drying_batch.assert_awaited_once()
        call_args = fake_full_coord._journal.open_drying_batch.call_args
        assert call_args.args[0] == "cycle_abc123"
        assert call_args.args[1]["stage_durations_snapshot"] == {
            "germination": 5, "early_veg": 10,
        }


@pytest.mark.asyncio
class TestHarvestCompleteDryingBatch:
    async def test_raises_when_nothing_occupying_drying_room(self, fake_full_coord):
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_DRYING_OCCUPIED] = False
        with pytest.raises(ValueError):
            await fake_full_coord.harvest_complete_drying_batch(500.0, 100.0)

    async def test_closes_out_the_correct_cycle_id_and_frees_drying_occupancy(self, fake_full_coord):
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_full_coord._config[CONF_DRYING_CYCLE_ID] = "cycle_abc123"

        result = await fake_full_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["cycle_id"] == "cycle_abc123"
        call_kwargs = fake_full_coord.hass.config_entries.async_update_entry.call_args.kwargs
        assert call_kwargs["options"][CONF_DRYING_OCCUPIED] is False
        fake_full_coord._journal.close_open_drying_batch.assert_awaited_once_with("cycle_abc123")

    async def test_uses_isolated_drying_energy_counters_not_global(self, fake_full_coord):
        """A concurrent, unrelated cycle in Primary Grow Space must not be
        affected — this closes out using _drying_cycle_kwh/_cost only."""
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_full_coord._config[CONF_DRYING_CYCLE_ID] = "cycle_abc123"

        result = await fake_full_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["cycle_kwh"] == 1.5
        assert result["cycle_cost_usd"] == 0.4
        assert fake_full_coord._drying_cycle_kwh == 0.0
        assert fake_full_coord._drying_cycle_cost == 0.0

    async def test_uses_snapshotted_stage_durations_not_live_stage_manager(self, fake_full_coord):
        """Simulates the concurrency scenario: by the time this closes out,
        stage_manager already represents a DIFFERENT, newer cycle — the
        snapshot taken at space_now_empty() time must be used instead."""
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_full_coord._config[CONF_DRYING_CYCLE_ID] = "cycle_abc123"
        # A new, unrelated cycle now active in Primary Grow Space.
        fake_full_coord.stage_manager.actual_stage_durations = MagicMock(
            return_value={"germination": 1}
        )

        result = await fake_full_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["stage_durations"] == {"germination": 5, "early_veg": 10}

    async def test_independent_of_whether_zone2_has_started_a_new_cycle(self, fake_full_coord):
        """Part 4.4: callable regardless of Primary Grow Space's current
        state — a fresh, different cycle_id may already be active there."""
        fake_full_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = True
        fake_full_coord._config[CONF_DRYING_OCCUPIED] = True
        fake_full_coord._config[CONF_DRYING_CYCLE_ID] = "cycle_abc123"
        fake_full_coord._config[CONF_ZONE2_OCCUPIED] = True
        fake_full_coord._config[CONF_ZONE2_CYCLE_ID] = "cycle_new_999"

        result = await fake_full_coord.harvest_complete_drying_batch(500.0, 100.0)

        assert result["cycle_id"] == "cycle_abc123"
        # Zone2's own occupancy/cycle_id are untouched by this call.
        assert fake_full_coord._config[CONF_ZONE2_OCCUPIED] is True
        assert fake_full_coord._config[CONF_ZONE2_CYCLE_ID] == "cycle_new_999"
