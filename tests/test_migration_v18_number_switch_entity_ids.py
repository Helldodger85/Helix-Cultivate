"""Tests for the v1.7 -> v1.8 entity-registry rename migration in
async_migrate_entry (__init__.py): the same entity_id-pinning fix already
applied to sensor (v1.3) and select (v1.5) domains, extended to number and
switch. HelixNumber/HelixSwitch never pinned entity_id at all before this
session, so HA fell back to a name-derived slug that rarely matches the
entity_description key (e.g. key "temp_setpoint" vs name "Temperature
Setpoint") — meaning every number.set_value/switch.turn_on call the
frontend makes against number.helix_cultivate_{key}/switch.helix_cultivate_
{key} was silently targeting a nonexistent entity. This is the actual root
cause behind sliders and toggles (Safety tab, Breeze, setpoints, fan speed/
variance) that appeared to work but never took effect.

Monkeypatches the `er` (entity_registry) module reference inside
custom_components.helix_cultivate.__init__ with a small fake registry, same
approach as test_migration_v13.py.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import CONFIG_MINOR_VERSION, DOMAIN


class _FakeRegistryEntry:
    def __init__(self, entity_id, unique_id, domain="number", platform=DOMAIN):
        self.entity_id = entity_id
        self.unique_id = unique_id
        self.domain = domain
        self.platform = platform


class _FakeEntityRegistry:
    def __init__(self, entries):
        self._by_entity_id = {e.entity_id: e for e in entries}

    def async_get(self, entity_id):
        return self._by_entity_id.get(entity_id)

    def async_update_entity(self, entity_id, *, new_entity_id):
        entry = self._by_entity_id.pop(entity_id)
        entry.entity_id = new_entity_id
        self._by_entity_id[new_entity_id] = entry
        return entry


def _make_config_entry(entry_id="entry123", version=1, minor_version=7):
    return SimpleNamespace(
        entry_id=entry_id,
        version=version,
        minor_version=minor_version,
        data={},
        options={},
    )


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_v18_migration_renames_mismatched_number_and_switch_entity_ids(monkeypatch, fake_hass):
    entry = _make_config_entry()
    old_entries = [
        _FakeRegistryEntry(
            "number.helix_cultivate_temperature_setpoint", f"{entry.entry_id}_temp_setpoint",
            domain="number",
        ),
        _FakeRegistryEntry(
            "switch.helix_cultivate_upper_canopy_breeze_mode", f"{entry.entry_id}_breeze_upper",
            domain="switch",
        ),
        # Already matches the new scheme — must be left alone (idempotent).
        _FakeRegistryEntry(
            "number.helix_cultivate_vpd_target", f"{entry.entry_id}_vpd_target", domain="number",
        ),
        # A different domain entirely (e.g. a sensor) — must be ignored.
        _FakeRegistryEntry(
            "sensor.helix_cultivate_leaf_vpd", f"{entry.entry_id}_leaf_vpd", domain="sensor",
        ),
    ]
    fake_registry = _FakeEntityRegistry(old_entries)

    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: fake_registry)
    monkeypatch.setattr(
        helix_init.er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: list(registry._by_entity_id.values()),
    )

    result = await helix_init.async_migrate_entry(fake_hass, entry)

    assert result is True
    assert fake_registry.async_get("number.helix_cultivate_temp_setpoint") is not None
    assert fake_registry.async_get("number.helix_cultivate_temperature_setpoint") is None
    assert fake_registry.async_get("switch.helix_cultivate_breeze_upper") is not None
    assert fake_registry.async_get("switch.helix_cultivate_upper_canopy_breeze_mode") is None
    # Already-correct and non-matching entries are untouched.
    assert fake_registry.async_get("number.helix_cultivate_vpd_target") is not None
    assert fake_registry.async_get("sensor.helix_cultivate_leaf_vpd") is not None

    fake_hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_v18_migration_skips_when_target_entity_id_taken(monkeypatch, fake_hass):
    entry = _make_config_entry()
    old_entries = [
        _FakeRegistryEntry(
            "switch.helix_cultivate_mid_canopy_breeze_mode", f"{entry.entry_id}_breeze_mid",
            domain="switch",
        ),
        # Collision: something already occupies the target entity_id.
        _FakeRegistryEntry(
            "switch.helix_cultivate_breeze_mid", f"{entry.entry_id}_some_other_unique_id",
            domain="switch",
        ),
    ]
    fake_registry = _FakeEntityRegistry(old_entries)

    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: fake_registry)
    monkeypatch.setattr(
        helix_init.er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: list(registry._by_entity_id.values()),
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    assert fake_registry.async_get("switch.helix_cultivate_mid_canopy_breeze_mode") is not None


@pytest.mark.asyncio
async def test_migration_from_current_version_is_a_noop_rename(monkeypatch, fake_hass):
    """An entry already fully migrated must not touch the entity registry
    at all — every version-gated branch (sensor/select/number/switch
    renames) is skipped."""
    entry = _make_config_entry(minor_version=CONFIG_MINOR_VERSION)
    calls = []
    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: (calls.append(1), None)[1])

    await helix_init.async_migrate_entry(fake_hass, entry)

    assert calls == []


@pytest.mark.asyncio
async def test_v18_boundary_number_and_switch_rename_runs_after_earlier_versions(
    monkeypatch, fake_hass
):
    """An entry at exactly minor_version=7 (v1.7's cycle_state migration
    already applied) still needs the v1.8 number/switch rename — confirms
    the branch is independently gated, not skipped by mistake."""
    entry = _make_config_entry(minor_version=7)
    number_entry = _FakeRegistryEntry(
        "number.helix_cultivate_sunrise_sunset_ramp", f"{entry.entry_id}_sunrise_ramp_min",
        domain="number",
    )
    fake_registry = _FakeEntityRegistry([number_entry])

    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: fake_registry)
    monkeypatch.setattr(
        helix_init.er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: list(registry._by_entity_id.values()),
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    assert fake_registry.async_get("number.helix_cultivate_sunrise_ramp_min") is not None
    assert fake_registry.async_get("number.helix_cultivate_sunrise_sunset_ramp") is None
