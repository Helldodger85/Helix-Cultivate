"""Tests for v1.6.1 Part 2: the Conditioning Room hardware-mapping form's
Reverse Cycle Unit toggle not persisting.

Root cause investigation (per the ticket's own three checkpoints):

1. Frontend save payload — CONFIRMED the real bug. HelixTabConditioning's
   extraFieldsGetter never read `.hw-layer-toggle` checkboxes at all (see
   tests/js/check_reverse_cycle_toggle_save.js and helix-panel.js), unlike
   the equivalent Zone 2 / Drying Room callbacks. Save's WS payload never
   contained `zone1_is_reverse_cycle`, regardless of the checkbox's state.
2. Backend persistence — genuinely fine already. `zone1_is_reverse_cycle`
   was already in VALID_SETTINGS_FIELD_KEYS, and this file proves
   queue_option_write()'s debounced flush round-trips it correctly through
   a real config-entry `.options` dict, AND survives an unrelated
   subsequent save (the exact "unrelated save silently reverts an
   unrelated field" regression class this codebase has hit once before) —
   because _flush_pending_options merges `{**self._entry.options,
   **pending}` against the entry's live options rather than replacing them
   wholesale.
3. Frontend read-back on reopen — also genuinely fine already; it reads
   the same coordinator-attribute path every other already-working
   reverse-cycle toggle (zone2/drying) uses.

So this file exists to lock in #2 with real assertions (not just "save
returned success") now that #1 is fixed and can actually reach it.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import custom_components.helix_cultivate as helix_init
from custom_components.helix_cultivate.coordinator import HelixCoordinator

DOMAIN = "helix_cultivate"


def _bind_real_methods(coord, *names):
    for name in names:
        setattr(
            coord, name,
            (lambda n: lambda *a, **kw: getattr(HelixCoordinator, n)(coord, *a, **kw))(name),
        )


class FakeConfigEntry:
    """Stands in for a real ConfigEntry: a plain, mutable `.options` dict,
    exactly what `_flush_pending_options` reads from and writes back to."""
    def __init__(self, entry_id="entry123"):
        self.entry_id = entry_id
        self.options = {}


@pytest.fixture
def real_option_write_coord():
    entry = FakeConfigEntry()
    coord = MagicMock()
    coord._entry = entry
    coord._config = {}
    coord._pending_options = {}
    coord._options_write_unsub = None
    coord.hass = MagicMock()

    # Mirrors real HA's async_update_entry: replaces entry.options wholesale
    # with whatever new_options dict it's given — the merge behavior being
    # tested lives entirely in _flush_pending_options itself, not here.
    def _async_update_entry(_entry, options):
        entry.options = options
    coord.hass.config_entries.async_update_entry = MagicMock(side_effect=_async_update_entry)

    _bind_real_methods(coord, "queue_option_write", "_flush_pending_options")
    return coord, entry


@pytest.fixture
def fake_hass_and_coord(real_option_write_coord):
    coord, entry = real_option_write_coord
    hass = MagicMock()
    hass.config_entries.async_get_entry = MagicMock(return_value=entry)
    hass.data = {DOMAIN: {entry.entry_id: coord}}
    hass._background_tasks = []
    hass.async_create_background_task = (
        lambda coro, name, **kwargs: hass._background_tasks.append(asyncio.ensure_future(coro))
    )
    return hass, coord, entry


async def _call_ws_handler(handler, hass, connection, msg):
    handler(hass, connection, msg)
    await asyncio.gather(*hass._background_tasks)


@pytest.mark.asyncio
async def test_reverse_cycle_toggle_round_trips_through_real_persistence(fake_hass_and_coord):
    """Saves the toggle as on, then reads the persisted config entry's
    options DIRECTLY (not the WS "success" response) to confirm the true
    stored value is actually True — the exact check the ticket asks for,
    since 'save succeeded' was never the part that was actually broken."""
    hass, coord, entry = fake_hass_and_coord
    connection = MagicMock()
    msg = {"id": 1, "entry_id": entry.entry_id, "fields": {"zone1_is_reverse_cycle": True}}

    with patch("custom_components.helix_cultivate.coordinator.async_call_later") as mock_call_later:
        mock_call_later.return_value = lambda: None
        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)
        # Simulate the debounce interval elapsing — fires the real,
        # unmocked _flush_pending_options.
        coord._flush_pending_options()

    assert entry.options.get("zone1_is_reverse_cycle") is True
    connection.send_result.assert_called_once_with(1, {"success": True})


@pytest.mark.asyncio
async def test_reverse_cycle_toggle_off_also_round_trips(fake_hass_and_coord):
    """Explicitly proves False round-trips too, not just "anything truthy
    sticks" — the bug's actual symptom was the field being silently
    omitted, which reads back indistinguishably from a real, deliberate
    False, so both directions need to be provably correct."""
    hass, coord, entry = fake_hass_and_coord
    entry.options["zone1_is_reverse_cycle"] = True  # started on
    connection = MagicMock()
    msg = {"id": 1, "entry_id": entry.entry_id, "fields": {"zone1_is_reverse_cycle": False}}

    with patch("custom_components.helix_cultivate.coordinator.async_call_later") as mock_call_later:
        mock_call_later.return_value = lambda: None
        await _call_ws_handler(helix_init.ws_update_settings_fields, hass, connection, msg)
        coord._flush_pending_options()

    assert entry.options.get("zone1_is_reverse_cycle") is False


@pytest.mark.asyncio
async def test_unrelated_save_does_not_revert_reverse_cycle_toggle(fake_hass_and_coord):
    """The exact regression class named in the ticket as having happened
    once before in this codebase: an unrelated field's save silently
    reverting a previously-saved, unrelated toggle. Proves
    _flush_pending_options's `{**self._entry.options, **pending}` merge
    (rather than a wholesale options replacement) protects this toggle."""
    hass, coord, entry = fake_hass_and_coord
    connection = MagicMock()

    with patch("custom_components.helix_cultivate.coordinator.async_call_later") as mock_call_later:
        mock_call_later.return_value = lambda: None

        # Step 1: save the Reverse Cycle toggle on.
        await _call_ws_handler(
            helix_init.ws_update_settings_fields, hass, connection,
            {"id": 1, "entry_id": entry.entry_id, "fields": {"zone1_is_reverse_cycle": True}},
        )
        coord._flush_pending_options()
        assert entry.options.get("zone1_is_reverse_cycle") is True

        # Step 2: a completely unrelated save (e.g. adjusting the Temp
        # Setpoint form's preheat lead time) in a later, separate flush.
        await _call_ws_handler(
            helix_init.ws_update_settings_fields, hass, connection,
            {"id": 2, "entry_id": entry.entry_id, "fields": {"preheat_lead_min": 20}},
        )
        coord._flush_pending_options()

    assert entry.options.get("preheat_lead_min") == 20
    assert entry.options.get("zone1_is_reverse_cycle") is True, (
        "an unrelated settings save must never revert the Reverse Cycle toggle — "
        "this exact regression class has happened once before in this codebase"
    )
