"""Tests for v1.5.0 Part 4: the Temporary Override system — Day/Night-keyed
live overrides for Temp Setpoint, VPD Target, and Light Intensity that take
precedence over that context's saved stage default until the active stage
changes, independent per context/kind, and clearly indicated via
has_active_override()/the override_* sensor attrs.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.stage_manager import StageManager

DOMAIN = "helix_cultivate"


def _bind(coord, *names):
    for name in names:
        setattr(coord, name, (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name))


@pytest.fixture
def fake_coord():
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.smooth_glides_enabled = True
    coord.temp_setpoint = 24.0
    coord.vpd_target = 1.0
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2
    coord.light_intensity_pct = 100.0
    coord._temp_override = {"day": None, "night": None}
    coord._vpd_override = {"day": None, "night": None}
    coord._light_override = {"day": None, "night": None}
    coord.stage_manager = MagicMock()
    coord.stage_manager.current_stage = "peak_flower"
    coord.stage_manager.current_vpd_range = MagicMock(return_value=(1.10, 1.40))
    coord.stage_manager.current_temp_anchor = MagicMock(return_value=26.0)
    coord.stage_manager._profile = MagicMock(return_value={"light_intensity_pct": 100})
    _bind(
        coord,
        "apply_temporary_override",
        "clear_stage_overrides",
        "has_active_override",
        "_apply_active_setpoints",
        "_override_store",
    )
    return coord


class TestApplyTemporaryOverrideAppliesImmediately:
    def test_applying_for_active_context_updates_live_setpoint_now(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)  # currently day
        fake_coord.apply_temporary_override("day", "temp", 28.0)
        assert fake_coord.temp_setpoint == 28.0

    def test_applying_for_inactive_context_does_not_touch_live_setpoint(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)  # currently day
        fake_coord.apply_temporary_override("night", "temp", 18.0)
        # Live temp_setpoint stays at whatever the day resolution gives —
        # unaffected by a night-only override while it's actually day.
        assert fake_coord.temp_setpoint != 18.0
        assert fake_coord.has_active_override("night", "temp") is True

    def test_vpd_override_recenters_min_max_preserving_band_width(self, fake_coord):
        """The stage's own day VPD band is 1.10-1.40 (width 0.30) — an
        override recenters that same width around the new value rather
        than fabricating an arbitrary deadband."""
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "vpd", 1.0)
        assert fake_coord.vpd_target == 1.0
        assert fake_coord.vpd_target_min == pytest.approx(0.85)
        assert fake_coord.vpd_target_max == pytest.approx(1.15)

    def test_light_override_applies_immediately_for_active_context(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "light", 60.0)
        assert fake_coord.light_intensity_pct == 60.0

    def test_invalid_context_raises(self, fake_coord):
        with pytest.raises(ValueError):
            fake_coord.apply_temporary_override("afternoon", "temp", 20.0)

    def test_invalid_kind_raises(self, fake_coord):
        with pytest.raises(ValueError):
            fake_coord.apply_temporary_override("day", "humidity", 20.0)


class TestOverrideIndependencePerContextAndKind:
    def test_day_override_does_not_affect_night_default_or_override(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=False)  # currently night
        fake_coord.apply_temporary_override("night", "temp", 19.0)
        assert fake_coord.has_active_override("day", "temp") is False
        assert fake_coord._temp_override["day"] is None
        assert fake_coord._temp_override["night"] == 19.0

    def test_night_override_does_not_affect_day_override(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "temp", 27.0)
        fake_coord.apply_temporary_override("night", "temp", 19.0)
        assert fake_coord._temp_override["day"] == 27.0
        assert fake_coord._temp_override["night"] == 19.0

    def test_temp_override_does_not_affect_vpd_or_light(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "temp", 27.0)
        assert fake_coord.has_active_override("day", "vpd") is False
        assert fake_coord.has_active_override("day", "light") is False


class TestOverridePersistsAcrossDayNightFlipWithinSameStage:
    def test_day_override_survives_the_tick_recomputing_for_night(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "temp", 27.0)

        # Now it's night — the tick's own resolution runs for "night" and
        # must leave the day override slot completely untouched.
        fake_coord._lights_on = MagicMock(return_value=False)
        fake_coord._apply_active_setpoints()
        assert fake_coord._temp_override["day"] == 27.0
        # And it's still exactly 27.0 the next time day comes back around.
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord._apply_active_setpoints()
        assert fake_coord.temp_setpoint == 27.0


class TestClearStageOverridesOnStageTransition:
    def test_clear_stage_overrides_clears_all_six_slots(self, fake_coord):
        fake_coord._lights_on = MagicMock(return_value=True)
        fake_coord.apply_temporary_override("day", "temp", 27.0)
        fake_coord.apply_temporary_override("night", "vpd", 0.9)
        fake_coord.apply_temporary_override("day", "light", 50.0)

        fake_coord.clear_stage_overrides()

        for store in (fake_coord._temp_override, fake_coord._vpd_override, fake_coord._light_override):
            assert store["day"] is None
            assert store["night"] is None

    def test_real_stage_manager_advance_clears_overrides_via_coord_ref(self):
        """End-to-end through the real StageManager — _advance_stage() and
        set_stage() both call coordinator.clear_stage_overrides() on every
        transition, manual or PROG_TIMEFRAME auto-advance alike."""
        from custom_components.helix_cultivate.const import STAGE_GERMINATION, STAGE_SEEDLING

        hass = MagicMock()
        mgr = StageManager(hass, {"current_stage": STAGE_GERMINATION})
        coord_ref = MagicMock()
        mgr.set_coordinator_ref(coord_ref)

        mgr.set_stage(STAGE_SEEDLING)

        coord_ref.clear_stage_overrides.assert_called_once()


@pytest.mark.asyncio
class TestNumberEntityRoutesThroughOverrideSystem:
    async def test_temp_setpoint_number_entity_sets_override_for_current_context(self):
        from custom_components.helix_cultivate.number import HelixNumber, NUMBER_DESCRIPTIONS
        from custom_components.helix_cultivate.const import NUMBER_TEMP_SETPOINT

        description = next(d for d in NUMBER_DESCRIPTIONS if d.key == NUMBER_TEMP_SETPOINT)
        coordinator = MagicMock()
        coordinator._entry = MagicMock(entry_id="entry123")
        coordinator._lights_on = MagicMock(return_value=True)
        coordinator.apply_temporary_override = MagicMock()
        entity = HelixNumber(coordinator, description)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(27.5)

        coordinator.apply_temporary_override.assert_called_once_with("day", "temp", 27.5)

    async def test_light_intensity_number_entity_sets_override_for_current_context(self):
        from custom_components.helix_cultivate.number import HelixNumber, NUMBER_DESCRIPTIONS
        from custom_components.helix_cultivate.const import NUMBER_LIGHT_INTENSITY

        description = next(d for d in NUMBER_DESCRIPTIONS if d.key == NUMBER_LIGHT_INTENSITY)
        coordinator = MagicMock()
        coordinator._entry = MagicMock(entry_id="entry123")
        coordinator._lights_on = MagicMock(return_value=False)
        coordinator.apply_temporary_override = MagicMock()
        entity = HelixNumber(coordinator, description)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(40.0)

        coordinator.apply_temporary_override.assert_called_once_with("night", "light", 40.0)

    async def test_rh_setpoint_number_entity_unaffected_still_uses_manual_flag(self):
        """RH is explicitly out of scope for the Temporary Override system
        — it keeps its own pre-existing manual-override flag."""
        from custom_components.helix_cultivate.number import HelixNumber, NUMBER_DESCRIPTIONS
        from custom_components.helix_cultivate.const import NUMBER_RH_SETPOINT

        description = next(d for d in NUMBER_DESCRIPTIONS if d.key == NUMBER_RH_SETPOINT)
        coordinator = MagicMock()
        coordinator._entry = MagicMock(entry_id="entry123")
        coordinator.apply_temporary_override = MagicMock()
        coordinator.rh_setpoint_manual_override = False
        entity = HelixNumber(coordinator, description)
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_set_native_value(65.0)

        coordinator.apply_temporary_override.assert_not_called()
        assert coordinator.rh_setpoint_manual_override is True
        assert coordinator.rh_setpoint == 65.0
