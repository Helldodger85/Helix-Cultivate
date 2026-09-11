"""Tests for the v1.3 -> v1.4 config-key migration in async_migrate_entry
(__init__.py): CONF_GROW_LIGHT/CONF_LIGHT_TYPE ("grow_light"/"light_type")
renamed to CONF_ZONE2_GROW_LIGHT/CONF_ZONE2_LIGHT_TYPE
("zone2_grow_light"/"zone2_light_type") for consistency with every other
Zone 2 hardware key.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import CONFIG_MINOR_VERSION


def _make_config_entry(entry_id="entry123", version=1, minor_version=3, data=None, options=None):
    return SimpleNamespace(
        entry_id=entry_id,
        version=version,
        minor_version=minor_version,
        data=data or {},
        options=options or {},
    )


@pytest.fixture
def fake_hass(monkeypatch):
    # No sensor entities to rename at this minor_version — keep the v1.3
    # entity-registry branch a no-op so these tests exercise only v1.4.
    monkeypatch.setattr(helix_init.er, "async_get", lambda hass: MagicMock())
    monkeypatch.setattr(
        helix_init.er, "async_entries_for_config_entry", lambda registry, entry_id: []
    )
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


@pytest.mark.asyncio
async def test_existing_grow_light_and_light_type_values_migrate(fake_hass):
    entry = _make_config_entry(
        options={"grow_light": "light.old_grow_light", "light_type": "hid_ballast"},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    fake_hass.config_entries.async_update_entry.assert_called_once()
    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    new_opts = call_kwargs["options"]
    assert new_opts["zone2_grow_light"] == "light.old_grow_light"
    assert new_opts["zone2_light_type"] == "hid_ballast"
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_values_in_data_also_migrate(fake_hass):
    entry = _make_config_entry(
        data={"grow_light": "switch.old_grow_light"},
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["data"]["zone2_grow_light"] == "switch.old_grow_light"


@pytest.mark.asyncio
async def test_no_prior_values_is_a_clean_noop(fake_hass):
    entry = _make_config_entry()

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert "zone2_grow_light" not in call_kwargs["options"]
    assert "zone2_light_type" not in call_kwargs["options"]


@pytest.mark.asyncio
async def test_existing_new_key_value_is_never_clobbered(fake_hass):
    """If somehow both the old and new keys are already present (e.g. a
    replayed migration), the already-migrated new value must win — never
    overwritten by the stale old-key value."""
    entry = _make_config_entry(
        options={
            "grow_light": "light.stale_old_value",
            "zone2_grow_light": "light.correct_current_value",
        },
    )

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"]["zone2_grow_light"] == "light.correct_current_value"
