"""Tests for v1.4.1 Part 2 (autonomous Live Actuator Response Test
scheduling) and the related Part 1.5 fix to cross-zone response testing's
lag/magnitude measurement (previously compared the wrong pair of readings
and never actually used dedicated dependent-zone sensors for the "ending"
side of the comparison).
"""
from __future__ import annotations

import copy
from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.const import (
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE2_IS_REVERSE_CYCLE,
    LEARNING_STATE_ACTIVE,
    LIVE_ACTUATOR_TEST_INTERVAL_LEARNING_HOURS,
)
from custom_components.helix_cultivate.learning_engine import (
    TEST_TYPE_DEEP_CALIBRATION,
    TEST_TYPE_LIVE_ACTUATOR,
    LearningEngine,
)
from custom_components.helix_cultivate.learning_store import LearningStore
from homeassistant.util import dt as dt_util

DOMAIN = "helix_cultivate"


class _FakeStorage:
    def __init__(self):
        self._data = None

    async def async_load(self):
        return self._data

    async def async_save(self, data):
        self._data = copy.deepcopy(data)


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


@pytest.fixture
def fake_coord(fake_hass, learning_store):
    coord = MagicMock()
    coord.hass = fake_hass
    coord._config = {
        CONF_ZONE2_IS_REVERSE_CYCLE: True,
        CONF_ENABLE_CONDITIONING_ROOM: False,
        CONF_ENABLE_DRYING_ENVIRONMENT: False,
    }
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.conditioning_room_dependent_zones = MagicMock(return_value=[])
    return coord


@pytest.mark.asyncio
class TestAutonomousScheduling:
    async def test_starts_a_test_with_no_history_and_no_active_test(self, fake_coord):
        engine = LearningEngine(fake_coord)
        test = await engine.maybe_schedule_live_actuator_test({"zone2": 24.0})
        assert test is not None
        assert test["zone"] == "zone2"
        assert test["type"] == TEST_TYPE_LIVE_ACTUATOR

    async def test_does_not_start_when_a_test_is_already_active(self, fake_coord, learning_store):
        await learning_store.set_active_test({"type": TEST_TYPE_DEEP_CALIBRATION, "zone": "zone2"})
        engine = LearningEngine(fake_coord)
        result = await engine.maybe_schedule_live_actuator_test({"zone2": 24.0})
        assert result is None

    async def test_does_not_start_before_interval_elapsed(self, fake_coord, learning_store):
        recent = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
        await learning_store.append_test_history(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "ended_at": recent}
        )
        engine = LearningEngine(fake_coord)
        result = await engine.maybe_schedule_live_actuator_test({"zone2": 24.0})
        assert result is None

    async def test_starts_again_once_learning_interval_elapsed(self, fake_coord, learning_store):
        old = (
            dt_util.utcnow() - timedelta(hours=LIVE_ACTUATOR_TEST_INTERVAL_LEARNING_HOURS + 1)
        ).isoformat()
        await learning_store.append_test_history(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "ended_at": old}
        )
        engine = LearningEngine(fake_coord)
        result = await engine.maybe_schedule_live_actuator_test({"zone2": 24.0})
        assert result is not None

    async def test_uses_longer_interval_once_active(self, fake_coord, learning_store):
        fake_coord._config["thermal_learning_state"] = LEARNING_STATE_ACTIVE
        # Elapsed past the (shorter) Learning interval but NOT the (longer) Active one.
        mid = (
            dt_util.utcnow() - timedelta(hours=LIVE_ACTUATOR_TEST_INTERVAL_LEARNING_HOURS + 1)
        ).isoformat()
        await learning_store.append_test_history(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "ended_at": mid}
        )
        engine = LearningEngine(fake_coord)
        result = await engine.maybe_schedule_live_actuator_test({"zone2": 24.0})
        assert result is None

    async def test_ignores_disabled_zones(self, fake_coord):
        fake_coord._config[CONF_ENABLE_CONDITIONING_ROOM] = False
        fake_coord._config[CONF_ENABLE_DRYING_ENVIRONMENT] = False
        engine = LearningEngine(fake_coord)
        test = await engine.maybe_schedule_live_actuator_test(
            {"zone2": 24.0, "conditioning": 20.0, "drying": 15.5}
        )
        # Only zone2 is enabled — a scheduled test must never target a
        # zone that doesn't exist in this install's topology.
        assert test["zone"] == "zone2"

    async def test_conditioning_test_captures_dependent_zone_starting_temps(
        self, fake_coord, learning_store
    ):
        fake_coord._config[CONF_ENABLE_CONDITIONING_ROOM] = True
        fake_coord._config[CONF_ZONE1_IS_REVERSE_CYCLE] = True
        fake_coord._config[CONF_ZONE2_IS_REVERSE_CYCLE] = False
        fake_coord.conditioning_room_dependent_zones = MagicMock(return_value=["zone2"])
        # zone2 is already due-in-the-future (not overdue) so this scheduling
        # pass falls through to conditioning, the zone actually under test.
        recent = dt_util.utcnow().isoformat()
        await learning_store.append_test_history(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "ended_at": recent}
        )
        engine = LearningEngine(fake_coord)

        test = await engine.maybe_schedule_live_actuator_test(
            {"conditioning": 21.0, "zone2": 25.0}
        )

        assert test["zone"] == "conditioning"
        assert test["started_temp_c"] == 21.0
        assert test["started_dependent_temps"] == {"zone2": 25.0}

    async def test_manual_trigger_still_works_alongside_autonomous_scheduling(self, fake_coord):
        """Part 2.2: manual triggering is not replaced by autonomous
        scheduling — the same start_live_actuator_test() entry point
        anyone can call directly still functions identically."""
        engine = LearningEngine(fake_coord)
        test = await engine.start_live_actuator_test(
            "zone2", thermostat_controlled=True, current_temp=24.0,
        )
        assert test["zone"] == "zone2"
        assert test["started_temp_c"] == 24.0


@pytest.mark.asyncio
class TestActiveLiveActuatorTestForZone:
    async def test_returns_none_when_learning_disabled(self, fake_coord):
        fake_coord._get = lambda key, default=None: {"thermal_learning_enabled": False}.get(key, default)
        from custom_components.helix_cultivate.coordinator import HelixCoordinator

        result = HelixCoordinator.active_live_actuator_test_for_zone(fake_coord, "zone2")
        assert result is None

    async def test_returns_test_dict_when_matching(self, fake_coord, learning_store):
        fake_coord._config["thermal_learning_enabled"] = True
        await learning_store.set_active_test(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "nudge_c": 1.0, "thermostat_controlled": True}
        )
        from custom_components.helix_cultivate.coordinator import HelixCoordinator

        result = HelixCoordinator.active_live_actuator_test_for_zone(fake_coord, "zone2")
        assert result is not None
        assert result["nudge_c"] == 1.0

    async def test_returns_none_for_a_different_zone(self, fake_coord, learning_store):
        fake_coord._config["thermal_learning_enabled"] = True
        await learning_store.set_active_test(
            {"type": TEST_TYPE_LIVE_ACTUATOR, "zone": "zone2", "nudge_c": 1.0}
        )
        from custom_components.helix_cultivate.coordinator import HelixCoordinator

        result = HelixCoordinator.active_live_actuator_test_for_zone(fake_coord, "drying")
        assert result is None


@pytest.mark.asyncio
class TestCrossZoneResponseMeasuresRealEndingReadings:
    async def test_magnitude_ratio_uses_dependent_zones_own_ending_reading(
        self, fake_coord, learning_store
    ):
        """Regression test for a real bug: the previous implementation
        compared the SOURCE zone's ending temp against the DEPENDENT
        zone's starting temp — comparing two different zones' readings
        against each other rather than measuring how much the dependent
        zone itself moved."""
        engine = LearningEngine(fake_coord)
        test = await engine.start_live_actuator_test(
            "conditioning", thermostat_controlled=True,
            current_temp=20.0, dependent_temps={"zone2": 25.0},
        )
        test["dependent_zones"] = ["zone2"]
        await learning_store.set_active_test(test)

        # Conditioning Room (source) reaches its nudged target; zone2
        # (dependent) itself moved by exactly half the nudge.
        await engine._finish_live_actuator_test(
            test, {"conditioning": 21.0, "zone2": 25.5}, timed_out=False
        )

        record = learning_store.get_cross_zone_response("zone2")
        assert record is not None
        assert record["mean_magnitude_ratio"] == pytest.approx(0.5)

    async def test_no_cross_zone_update_when_dependent_ending_reading_missing(
        self, fake_coord, learning_store
    ):
        engine = LearningEngine(fake_coord)
        test = await engine.start_live_actuator_test(
            "conditioning", thermostat_controlled=True,
            current_temp=20.0, dependent_temps={"zone2": 25.0},
        )
        test["dependent_zones"] = ["zone2"]
        await learning_store.set_active_test(test)

        await engine._finish_live_actuator_test(
            test, {"conditioning": 21.0, "zone2": None}, timed_out=False
        )

        assert learning_store.get_cross_zone_response("zone2") is None


@pytest.mark.asyncio
class TestTickActiveTestFinishesEarlyOnReachedTarget:
    async def test_finishes_early_when_thermostat_controlled_zone_reaches_nudged_target(
        self, fake_coord, learning_store
    ):
        engine = LearningEngine(fake_coord)
        await engine.start_live_actuator_test(
            "zone2", thermostat_controlled=True, current_temp=24.0,
        )

        # Zone2's dedicated sensor now reads within tolerance of 24+1=25.
        await engine.tick_active_test({"zone2": 24.9})

        assert learning_store.get_active_test() is None
        history = learning_store.get_test_history()
        assert history[-1]["timed_out"] is False

    async def test_does_not_finish_early_when_far_from_target(self, fake_coord, learning_store):
        engine = LearningEngine(fake_coord)
        await engine.start_live_actuator_test("zone2", thermostat_controlled=True, current_temp=24.0)

        await engine.tick_active_test({"zone2": 24.2})

        assert learning_store.get_active_test() is not None
