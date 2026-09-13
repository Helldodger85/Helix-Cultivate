"""Tests for v1.5.0 Part 3: the per-stage day-count is now genuinely
editable and wired to the real value StageManager._duration() uses for
PROG_TIMEFRAME auto-advance timing and the stage-progression heads-up
warning lead-time calculation — not a disconnected display number.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

from custom_components.helix_cultivate.const import (
    CONF_PROGRESSION_MODE,
    PROG_TIMEFRAME,
    STAGE_DEFAULT_DURATIONS,
    STAGE_GERMINATION,
    STAGE_SEEDLING,
)
from custom_components.helix_cultivate.stage_manager import StageManager


def _make_manager(config: dict) -> StageManager:
    hass = MagicMock()
    return StageManager(hass, config)


class TestDurationDefaultsAndOverride:
    def test_default_duration_matches_stage_default_durations(self):
        mgr = _make_manager({})
        for stage, expected in STAGE_DEFAULT_DURATIONS.items():
            assert mgr._duration(stage) == expected

    def test_persisted_stage_target_overrides_default(self):
        mgr = _make_manager({"stage_targets_germination": {"duration_days": 6}})
        assert mgr._duration(STAGE_GERMINATION) == 6
        # Unrelated stages are untouched.
        assert mgr._duration(STAGE_SEEDLING) == STAGE_DEFAULT_DURATIONS[STAGE_SEEDLING]

    def test_persisted_stage_target_takes_precedence_over_recipe(self):
        """Matches _profile()'s own established precedence: recipe YAML
        overrides the coded default, but a user-persisted stage_targets_{stage}
        value has the final say — the same "later layers win" order."""
        mgr = _make_manager({"stage_targets_germination": {"duration_days": 9}})
        mgr._recipe = {"stages": {"germination": {"duration_days": 3}}}
        assert mgr._duration(STAGE_GERMINATION) == 9

    def test_recipe_duration_used_when_no_persisted_override(self):
        mgr = _make_manager({})
        mgr._recipe = {"stages": {"germination": {"duration_days": 3}}}
        assert mgr._duration(STAGE_GERMINATION) == 3


class TestEditedDurationDrivesRealAutoAdvance:
    def test_prog_timeframe_does_not_advance_before_edited_duration_elapses(self):
        start = date.today() - timedelta(days=5)
        mgr = _make_manager({
            CONF_PROGRESSION_MODE: PROG_TIMEFRAME,
            "current_stage": STAGE_GERMINATION,
            "stage_start_date": start.isoformat(),
            "stage_targets_germination": {"duration_days": 10},
        })
        mgr.tick()
        assert mgr.current_stage == STAGE_GERMINATION

    def test_prog_timeframe_advances_once_edited_duration_elapses(self):
        """The whole point of Part 3.3: editing and saving the day-count
        must genuinely change when auto-advance fires — a shorter edited
        duration than the coded default (4 days) fires sooner."""
        start = date.today() - timedelta(days=3)
        mgr = _make_manager({
            CONF_PROGRESSION_MODE: PROG_TIMEFRAME,
            "current_stage": STAGE_GERMINATION,
            "stage_start_date": start.isoformat(),
            "stage_targets_germination": {"duration_days": 2},
        })
        mgr.tick()
        assert mgr.current_stage == STAGE_SEEDLING

    def test_coded_default_alone_would_not_have_advanced_yet(self):
        """Sanity check proving the edit above is what actually mattered —
        without it, 3 elapsed days is still short of Germination's coded
        4-day default."""
        start = date.today() - timedelta(days=3)
        mgr = _make_manager({
            CONF_PROGRESSION_MODE: PROG_TIMEFRAME,
            "current_stage": STAGE_GERMINATION,
            "stage_start_date": start.isoformat(),
        })
        mgr.tick()
        assert mgr.current_stage == STAGE_GERMINATION


class TestHeadsUpWarningUsesRealEditedDuration:
    def test_days_remaining_reflects_edited_duration(self):
        """_check_stage_progression_warning() (coordinator.py) reads
        stage_manager._duration(stage) directly — proving the real
        StageManager (not a mock) returns the edited value is what
        closes the loop for that feature."""
        start = date.today() - timedelta(days=8)
        mgr = _make_manager({
            "current_stage": STAGE_GERMINATION,
            "stage_start_date": start.isoformat(),
            "stage_targets_germination": {"duration_days": 10},
        })
        duration = mgr._duration(mgr.current_stage)
        elapsed = mgr._elapsed_days()
        assert duration - elapsed == 2
