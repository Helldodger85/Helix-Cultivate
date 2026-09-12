"""Tests for the v1.6 -> v1.7 config migration in async_migrate_entry
(__init__.py): introduces CONF_CYCLE_STATE. Critical requirement: any entry
that already existed before this version has a real, currently-tracked
stage and day-count and must migrate straight to "active", preserving its
current stage exactly as-is — never interrupted or reset. Only entries
created from v1.7 onward (which never go through this migration path at
all) default to "not_started".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import (
    CONF_CYCLE_STATE,
    CONFIG_MINOR_VERSION,
    CYCLE_STATE_ACTIVE,
    CYCLE_STATE_NOT_STARTED,
    DEFAULT_CYCLE_STATE,
)
from custom_components.helix_cultivate.stage_manager import StageManager


def _make_config_entry(entry_id="entry123", version=1, minor_version=6, data=None, options=None):
    return SimpleNamespace(
        entry_id=entry_id,
        version=version,
        minor_version=minor_version,
        data=data or {},
        options=options or {},
    )


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_existing_entry_migrates_to_active(fake_hass):
    entry = _make_config_entry(
        options={"current_stage": "early_veg", "stage_start_date": "2026-01-01"},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"][CONF_CYCLE_STATE] == CYCLE_STATE_ACTIVE
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_migration_preserves_existing_stage_and_start_date_exactly(fake_hass):
    """The critical requirement: stage/day-count must not be disturbed."""
    entry = _make_config_entry(
        options={"current_stage": "peak_flower", "stage_start_date": "2026-02-10"},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"]["current_stage"] == "peak_flower"
    assert call_kwargs["options"]["stage_start_date"] == "2026-02-10"


@pytest.mark.asyncio
async def test_migrated_active_entry_reconstructs_correct_stage_manager_state(fake_hass):
    """End-to-end: after migration, constructing a StageManager from the
    migrated options dict must show the preserved stage as active, not a
    fresh not-started cycle."""
    entry = _make_config_entry(
        options={"current_stage": "early_veg", "stage_start_date": "2026-01-01"},
    )
    await helix_init.async_migrate_entry(fake_hass, entry)
    migrated_options = fake_hass.config_entries.async_update_entry.call_args.kwargs["options"]

    merged_config = {**entry.data, **migrated_options, "initial_stage": migrated_options["current_stage"]}
    sm = StageManager(MagicMock(), merged_config)

    assert sm.cycle_state == CYCLE_STATE_ACTIVE
    assert sm.is_cycle_active is True
    assert sm.current_stage == "early_veg"


def test_new_stage_manager_defaults_to_not_started_when_key_absent():
    """A brand-new install's StageManager (never migrated, key simply
    absent from a freshly-created entry) must default to not_started."""
    sm = StageManager(MagicMock(), {})

    assert sm.cycle_state == CYCLE_STATE_NOT_STARTED
    assert sm.is_cycle_active is False
    assert DEFAULT_CYCLE_STATE == CYCLE_STATE_NOT_STARTED
