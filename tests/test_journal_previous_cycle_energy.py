"""Tests for JournalStore's Previous Cycle energy archive (Energy & ROI tab
Reset button, 2.6/2.7): archiving the current cycle's totals, retrieving
them afterward, the empty state before any archive has ever happened, and
overwrite-not-append behavior across repeated resets.
"""
from __future__ import annotations

import copy

import pytest

from custom_components.helix_cultivate.journal_store import EMPTY_STORE, JournalStore


class _FakeHass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _make_store() -> JournalStore:
    store = JournalStore.__new__(JournalStore)
    store._hass = _FakeHass()
    store._data = copy.deepcopy(EMPTY_STORE)
    store._save = _noop_save.__get__(store)
    return store


async def _noop_save(self) -> None:
    return None


def test_no_archive_yet_returns_none():
    store = _make_store()
    assert store.get_previous_cycle_energy("entry_a") is None


@pytest.mark.asyncio
async def test_archive_then_retrieve():
    store = _make_store()
    record = await store.async_set_previous_cycle_energy("entry_a", 12.5, 3.75)

    assert record["cycle_kwh"] == 12.5
    assert record["cycle_cost_usd"] == 3.75
    assert "archived_at" in record

    fetched = store.get_previous_cycle_energy("entry_a")
    assert fetched == record


@pytest.mark.asyncio
async def test_second_reset_overwrites_not_appends():
    store = _make_store()
    await store.async_set_previous_cycle_energy("entry_a", 12.5, 3.75)
    second = await store.async_set_previous_cycle_energy("entry_a", 5.0, 1.20)

    fetched = store.get_previous_cycle_energy("entry_a")
    assert fetched == second
    assert fetched["cycle_kwh"] == 5.0
    assert fetched["cycle_cost_usd"] == 1.20


@pytest.mark.asyncio
async def test_archives_are_independent_per_entry():
    store = _make_store()
    await store.async_set_previous_cycle_energy("entry_a", 12.5, 3.75)
    await store.async_set_previous_cycle_energy("entry_b", 8.0, 2.00)

    assert store.get_previous_cycle_energy("entry_a")["cycle_kwh"] == 12.5
    assert store.get_previous_cycle_energy("entry_b")["cycle_kwh"] == 8.0


@pytest.mark.asyncio
async def test_rounding_applied_to_archived_values():
    store = _make_store()
    record = await store.async_set_previous_cycle_energy("entry_a", 12.34567, 3.7891)
    assert record["cycle_kwh"] == 12.346
    assert record["cycle_cost_usd"] == 3.79
