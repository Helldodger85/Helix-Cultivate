"""Tests for the v1.2 -> v1.3 entity-registry rename migration in
async_migrate_entry (__init__.py) — sensor entity_ids are pinned to their
stable description key going forward (sensor.py), but entity_registry only
honors that for brand-new entities, so existing installs need this explicit
one-time rename to actually benefit from the fix.

Monkeypatches the `er` (entity_registry) module reference inside
custom_components.helix_cultivate.__init__ with a small fake registry, since
building a real EntityRegistry needs a full running HA core the rest of this
test suite deliberately avoids (see conftest.py).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import CONFIG_MINOR_VERSION, DOMAIN


class _FakeRegistryEntry:
    def __init__(self, entity_id, unique_id, domain="sensor", platform=DOMAIN):
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


def _make_config_entry(entry_id="entry123", version=1, minor_version=2):
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
async def test_v13_migration_renames_mismatched_sensor_entity_ids(monkeypatch, fake_hass):
    entry = _make_config_entry()
    old_entries = [
        _FakeRegistryEntry(
            "sensor.helix_cultivate_lung_room_temperature", f"{entry.entry_id}_lung_temp"
        ),
        _FakeRegistryEntry(
            "sensor.helix_cultivate_upper_canopy_humidity", f"{entry.entry_id}_upper_canopy_rh"
        ),
        # Already matches the new scheme — must be left alone (idempotent).
        _FakeRegistryEntry(
            "sensor.helix_cultivate_leaf_vpd", f"{entry.entry_id}_leaf_vpd"
        ),
        # A different domain entirely (e.g. a number entity) — must be ignored.
        _FakeRegistryEntry(
            "number.helix_cultivate_vpd_target", f"{entry.entry_id}_vpd_target", domain="number"
        ),
        # A different integration's entity that happens to share unique_id
        # prefix format — must be ignored (platform mismatch).
        _FakeRegistryEntry(
            "sensor.some_other_integration_thing", f"{entry.entry_id}_lung_temp", platform="other_domain"
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
    assert fake_registry.async_get("sensor.helix_cultivate_lung_temp") is not None
    assert fake_registry.async_get("sensor.helix_cultivate_lung_room_temperature") is None
    assert fake_registry.async_get("sensor.helix_cultivate_upper_canopy_rh") is not None
    assert fake_registry.async_get("sensor.helix_cultivate_upper_canopy_humidity") is None
    # Already-correct and non-matching entries are untouched.
    assert fake_registry.async_get("sensor.helix_cultivate_leaf_vpd") is not None
    assert fake_registry.async_get("number.helix_cultivate_vpd_target") is not None
    assert fake_registry.async_get("sensor.some_other_integration_thing") is not None

    # Config entry bumped to the current version/minor version.
    fake_hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_v13_migration_skips_when_target_entity_id_taken(monkeypatch, fake_hass):
    entry = _make_config_entry()
    old_entries = [
        _FakeRegistryEntry(
            "sensor.helix_cultivate_lung_room_temperature", f"{entry.entry_id}_lung_temp"
        ),
        # Collision: something already occupies the target entity_id.
        _FakeRegistryEntry(
            "sensor.helix_cultivate_lung_temp", f"{entry.entry_id}_some_other_unique_id"
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

    # The original entity must be left in place rather than silently dropped
    # or overwriting the occupant of the target entity_id.
    assert fake_registry.async_get("sensor.helix_cultivate_lung_room_temperature") is not None


@pytest.mark.asyncio
async def test_migration_from_current_version_is_a_noop_rename(monkeypatch, fake_hass):
    """An entry already fully migrated (current_minor == CONFIG_MINOR_VERSION)
    must not touch the entity registry at all — every version-gated branch,
    sensor rename (v1.3) and select rename (v1.5) alike, is skipped."""
    from custom_components.helix_cultivate.const import CONFIG_MINOR_VERSION

    entry = _make_config_entry(minor_version=CONFIG_MINOR_VERSION)
    calls = []
    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: (calls.append(1), None)[1])

    await helix_init.async_migrate_entry(fake_hass, entry)

    assert calls == []


@pytest.mark.asyncio
async def test_v13_boundary_sensor_branch_skipped_but_v15_select_branch_still_runs(
    monkeypatch, fake_hass
):
    """An entry at exactly minor_version=3 has already had its sensors
    renamed (v1.3 done) but still needs the v1.5 select rename — confirms
    the two branches are independently gated, not bundled."""
    entry = _make_config_entry(minor_version=3)
    select_entry = _FakeRegistryEntry(
        "select.helix_cultivate_grow_light_type", f"{entry.entry_id}_light_type",
        domain="select",
    )
    fake_registry = _FakeEntityRegistry([select_entry])

    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: fake_registry)
    monkeypatch.setattr(
        helix_init.er,
        "async_entries_for_config_entry",
        lambda registry, entry_id: list(registry._by_entity_id.values()),
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    assert fake_registry.async_get("select.helix_cultivate_light_type") is not None
    assert fake_registry.async_get("select.helix_cultivate_grow_light_type") is None
