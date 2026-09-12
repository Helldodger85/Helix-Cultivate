"""Tests for the v1.5 -> v1.6 config migration in async_migrate_entry
(__init__.py): "supplemental" is removed from Main Lighting's
zone2_light_type options (replaced with "quantum_board") and folded into its
own independent Supplemental Lighting system. Any existing entry with
zone2_light_type == "supplemental" must migrate to "led".
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.const import (
    CONFIG_MINOR_VERSION,
    FIXTURE_EFFICACY_UMOL_PER_J,
    FIXTURE_LEAF_OFFSET_DEFAULTS,
    LIGHT_FULL_SPECTRUM,
    LIGHT_HID,
    LIGHT_LED,
    LIGHT_QUANTUM_BOARD,
    LIGHT_TYPE_LABELS,
    LIGHT_TYPE_OPTIONS,
)


def _make_config_entry(entry_id="entry123", version=1, minor_version=5, data=None, options=None):
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


# ── const.py fixture-type surface ───────────────────────────────────────────

def test_light_type_options_no_longer_include_supplemental():
    assert "supplemental" not in LIGHT_TYPE_OPTIONS
    assert LIGHT_QUANTUM_BOARD in LIGHT_TYPE_OPTIONS


def test_light_type_options_exact_expected_set():
    assert LIGHT_TYPE_OPTIONS == [LIGHT_LED, LIGHT_FULL_SPECTRUM, LIGHT_HID, LIGHT_QUANTUM_BOARD]


def test_quantum_board_has_label():
    assert LIGHT_TYPE_LABELS[LIGHT_QUANTUM_BOARD] == "Quantum Board"


def test_quantum_board_efficacy_in_expected_range():
    efficacy = FIXTURE_EFFICACY_UMOL_PER_J[LIGHT_QUANTUM_BOARD]
    assert 2.8 <= efficacy <= 3.0


def test_quantum_board_leaf_offset_is_cooler_than_led():
    assert (
        FIXTURE_LEAF_OFFSET_DEFAULTS[LIGHT_QUANTUM_BOARD]
        < FIXTURE_LEAF_OFFSET_DEFAULTS[LIGHT_LED]
    )


# ── async_migrate_entry v1.6 migration ──────────────────────────────────────

@pytest.mark.asyncio
async def test_supplemental_zone2_light_type_migrates_to_led_in_options(fake_hass):
    entry = _make_config_entry(options={"zone2_light_type": "supplemental"})

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"]["zone2_light_type"] == LIGHT_LED
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION


@pytest.mark.asyncio
async def test_supplemental_zone2_light_type_migrates_to_led_in_data(fake_hass):
    entry = _make_config_entry(data={"zone2_light_type": "supplemental"})

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["data"]["zone2_light_type"] == LIGHT_LED


@pytest.mark.asyncio
async def test_non_supplemental_light_type_left_untouched(fake_hass):
    entry = _make_config_entry(options={"zone2_light_type": LIGHT_HID})

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert call_kwargs["options"]["zone2_light_type"] == LIGHT_HID


@pytest.mark.asyncio
async def test_no_light_type_configured_is_a_clean_noop(fake_hass):
    entry = _make_config_entry()

    await helix_init.async_migrate_entry(fake_hass, entry)

    call_kwargs = fake_hass.config_entries.async_update_entry.call_args.kwargs
    assert "zone2_light_type" not in call_kwargs["options"]
    assert call_kwargs["minor_version"] == CONFIG_MINOR_VERSION
