"""Tests for the v1.8 -> v1.9 config migration: the v1.6->v1.7 migration
set cycle_state to "active" for every already-existing entry but never
wrote CONF_STAGE_START_DATE into persisted options, despite its own
comment claiming day-count was preserved. StageManager.__init__ re-reads
this value fresh from config on every reload and treats it as "no start
date" (0 elapsed days) when absent — so every reload since v1.7 shipped
silently froze an already-affected install's day-count. This migration
writes today as the new stable reference point (the true original date
can't be recovered) so day-counting starts working correctly going
forward.

Critically tests that the value actually SURVIVES a simulated reload —
not just that it's set once at migration time — by feeding the migrated
options straight into a fresh StageManager and confirming its elapsed-day
math is stable across repeated construction from the same persisted dict,
the way a real config-entry reload would reconstruct it.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import (
    CONF_STAGE_START_DATE,
    CONFIG_MINOR_VERSION,
)
from custom_components.helix_cultivate.stage_manager import StageManager

# The migration writes dt_util.now().date() (HA's own configured-timezone
# "now"), while StageManager._elapsed_days() separately computes against
# the bare Python date.today() — the two are only guaranteed to agree in a
# real install because HA and the host OS share one timezone. In this bare
# test harness (no hass.config.time_zone configured) dt_util defaults to
# UTC, which can genuinely fall on a different calendar date than the test
# machine's own local date.today() depending on time of day — pinning
# dt_util.now() to "right now, in date.today()'s own date" removes that
# ambiguity outright rather than working around it after the fact.
_TODAY = date.today()


def _make_config_entry(entry_id="entry123", version=1, minor_version=6, data=None, options=None):
    return SimpleNamespace(
        entry_id=entry_id,
        version=version,
        minor_version=minor_version,
        data=data or {},
        options=options or {},
    )


@pytest.fixture(autouse=True)
def _pin_dt_util_now(monkeypatch):
    fixed = datetime.combine(_TODAY, time(12, 0), tzinfo=timezone.utc)
    monkeypatch.setattr(helix_init.dt_util, "now", lambda: fixed)


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_v19_migration_writes_stage_start_date_when_missing(fake_hass):
    """An entry that went through the old v1.7 migration (cycle_state
    active, current_stage set, but no stage_start_date ever written)."""
    entry = _make_config_entry(
        minor_version=6,
        options={"current_stage": "peak_flower"},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"].get(CONF_STAGE_START_DATE) == _TODAY.isoformat()
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_v19_migration_does_not_overwrite_a_real_existing_date(fake_hass):
    """An entry that already has a genuine stage_start_date (e.g. started
    via start_cycle() after v1.7 shipped) must be left completely alone."""
    real_date = "2026-01-15"
    entry = _make_config_entry(
        minor_version=8,
        options={"current_stage": "peak_flower", CONF_STAGE_START_DATE: real_date},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"][CONF_STAGE_START_DATE] == real_date


@pytest.mark.asyncio
async def test_v19_migration_is_noop_for_already_current_entry(fake_hass):
    entry = _make_config_entry(minor_version=CONFIG_MINOR_VERSION)

    result = await helix_init.async_migrate_entry(fake_hass, entry)

    assert result is True
    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert CONF_STAGE_START_DATE not in call_kwargs["options"]


@pytest.mark.asyncio
async def test_stage_start_date_survives_simulated_reload_across_multiple_constructions(fake_hass):
    """The actual regression: confirm the migrated value keeps producing
    the same elapsed-day count across repeated StageManager construction
    from the same persisted options dict — simulating several
    integration reloads in a row, not just a single migration run."""
    entry = _make_config_entry(minor_version=6, options={"current_stage": "peak_flower"})
    await helix_init.async_migrate_entry(fake_hass, entry)
    migrated_options = fake_hass.config_entries.async_update_entry.call_args.kwargs["options"]

    merged_config = {**entry.data, **migrated_options, "initial_stage": migrated_options["current_stage"]}

    sm_reload_1 = StageManager(MagicMock(), dict(merged_config))
    elapsed_1 = sm_reload_1._elapsed_days()

    # A second, later "reload" — same persisted dict, simulating the
    # config entry being torn down and reconstructed again.
    sm_reload_2 = StageManager(MagicMock(), dict(merged_config))
    elapsed_2 = sm_reload_2._elapsed_days()

    assert sm_reload_1._stage_start_date == _TODAY
    assert sm_reload_2._stage_start_date == _TODAY
    assert elapsed_1 == elapsed_2 == 0


@pytest.mark.asyncio
async def test_stage_start_date_reload_reflects_real_elapsed_time_once_persisted(fake_hass):
    """Once a real start date exists in persisted options (post-fix), a
    reload several days later must correctly compute non-zero elapsed
    days — confirming the value genuinely round-trips, not just that the
    migration wrote *something*."""
    backdated = (date.today() - timedelta(days=5)).isoformat()
    entry = _make_config_entry(
        minor_version=CONFIG_MINOR_VERSION,
        options={"current_stage": "peak_flower", CONF_STAGE_START_DATE: backdated},
    )
    await helix_init.async_migrate_entry(fake_hass, entry)
    persisted_options = fake_hass.config_entries.async_update_entry.call_args.kwargs["options"]

    merged_config = {**entry.data, **persisted_options, "initial_stage": "peak_flower"}
    sm = StageManager(MagicMock(), merged_config)

    assert sm._elapsed_days() == 5
