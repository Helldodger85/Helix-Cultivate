"""Helix Cultivate — Journal & IPM persistent store.

Persists logbook entries, IPM events and maintenance timestamps via
homeassistant.helpers.storage.Store (written to .storage/ as JSON).

Exposes four WebSocket API commands:
    helix_cultivate/journal/get
    helix_cultivate/journal/add_entry
    helix_cultivate/journal/mark_maintenance
    helix_cultivate/journal/add_ipm
"""
from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    DOMAIN,
    WS_CMD_JOURNAL_ADD,
    WS_CMD_JOURNAL_GET,
    WS_CMD_JOURNAL_IPM,
    WS_CMD_JOURNAL_MAINTENANCE,
)

_LOGGER = logging.getLogger(__name__)

JOURNAL_STORE_VERSION: int = 1
JOURNAL_STORE_KEY: str = "helix_cultivate_journal"

_MAINTENANCE_KEYS: frozenset[str] = frozenset(
    ["ph_low", "ph_high", "ec_low", "ec_high", "reservoir", "seaweed"]
)

_IPM_TYPES: frozenset[str] = frozenset(
    ["yellow_trap", "blue_trap", "neem", "pyrethrum"]
)

_ENTRY_TYPES: frozenset[str] = frozenset(
    ["nutrient", "ipm", "maintenance", "note"]
)

EMPTY_STORE: dict[str, Any] = {
    "entries": [],
    "maintenance": {
        "ph_low": None,
        "ph_high": None,
        "ec_low": None,
        "ec_high": None,
        "reservoir": None,
        "seaweed": None,
    },
    "ipm_events": [],
    "cycles_archive": [],
}


# ── WebSocket schema validators ───────────────────────────────────────────────

_ADD_ENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional("type", default="note"): vol.In(_ENTRY_TYPES),
        vol.Optional("label", default=""): str,
        vol.Optional("dose", default=""): str,
        vol.Optional("unit", default=""): str,
        vol.Optional("volume_l", default=0.0): vol.Coerce(float),
        vol.Optional("note", default=""): str,
    }
)

_ADD_IPM_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(_IPM_TYPES),
        vol.Optional("note", default=""): str,
    }
)


def _now_epoch_ms() -> int:
    """Return current UTC time as milliseconds since epoch."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _now_epoch_s() -> int:
    """Return current UTC time as seconds since epoch."""
    return int(datetime.now(timezone.utc).timestamp())


# ── Store class ───────────────────────────────────────────────────────────────

class JournalStore:
    """Manages journal/IPM/maintenance data via HA's built-in Store helper.

    All methods are async-safe and called from the HA event loop.
    The data is automatically written to .storage/helix_cultivate_journal.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, JOURNAL_STORE_VERSION, JOURNAL_STORE_KEY)
        self._data: dict[str, Any] = copy.deepcopy(EMPTY_STORE)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def async_load(self) -> None:
        """Load persisted data from .storage/. Defaults to EMPTY_STORE on first run."""
        raw: Optional[dict[str, Any]] = await self._store.async_load()
        if raw is None:
            self._data = copy.deepcopy(EMPTY_STORE)
            _LOGGER.debug("Helix Journal: no existing store — initialised empty")
        else:
            # Merge to ensure new keys added in future versions are always present
            merged = copy.deepcopy(EMPTY_STORE)
            merged.update(raw)
            # Ensure maintenance dict has all required keys
            for k in EMPTY_STORE["maintenance"]:
                merged["maintenance"].setdefault(k, None)
            self._data = merged
            _LOGGER.debug(
                "Helix Journal: loaded %d entries, %d IPM events",
                len(self._data.get("entries", [])),
                len(self._data.get("ipm_events", [])),
            )

    async def _save(self) -> None:
        """Persist current data to disk."""
        await self._store.async_save(self._data)

    # ── Public API ────────────────────────────────────────────────────────────

    async def async_get(self) -> dict[str, Any]:
        """Return the full journal data dict."""
        return copy.deepcopy(self._data)

    async def async_add_entry(self, entry_data: dict[str, Any]) -> dict[str, Any]:
        """Validate, assign id+ts, append to entries list, persist.

        Returns the fully-formed entry dict.
        """
        try:
            validated = _ADD_ENTRY_SCHEMA(entry_data)
        except vol.Invalid as exc:
            raise ValueError(f"Invalid journal entry: {exc}") from exc

        entry: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "ts": _now_epoch_ms(),
            **validated,
        }
        self._data["entries"].append(entry)
        # Keep list sorted newest-first for frontend convenience (max 1000 entries)
        self._data["entries"] = sorted(
            self._data["entries"], key=lambda e: e["ts"], reverse=True
        )[:1000]
        await self._save()
        _LOGGER.debug("Helix Journal: added entry type=%s id=%s", entry["type"], entry["id"])
        return entry

    async def async_mark_maintenance(self, key: str) -> dict[str, Any]:
        """Mark a maintenance item as done now. Returns the full maintenance dict."""
        if key not in _MAINTENANCE_KEYS:
            raise ValueError(f"Unknown maintenance key: {key!r}. Valid: {sorted(_MAINTENANCE_KEYS)}")
        self._data["maintenance"][key] = _now_epoch_s()
        await self._save()
        _LOGGER.debug("Helix Journal: maintenance '%s' marked done", key)
        return copy.deepcopy(self._data["maintenance"])

    async def async_add_ipm(self, event_data: dict[str, Any]) -> dict[str, Any]:
        """Validate, assign id+ts, append IPM event, persist.

        Returns the fully-formed IPM event dict.
        """
        try:
            validated = _ADD_IPM_SCHEMA(event_data)
        except vol.Invalid as exc:
            raise ValueError(f"Invalid IPM event: {exc}") from exc

        event: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "ts": _now_epoch_ms(),
            **validated,
        }
        self._data["ipm_events"].append(event)
        self._data["ipm_events"] = sorted(
            self._data["ipm_events"], key=lambda e: e["ts"], reverse=True
        )[:500]
        await self._save()
        _LOGGER.debug("Helix Journal: IPM event type=%s id=%s", event["type"], event["id"])
        return event

    async def archive_cycle(self, harvest_data: dict[str, Any]) -> str:
        """Validate and append a completed grow-cycle harvest record.

        Expected keys in harvest_data:
            wet_weight_g, dry_weight_g, cycle_kwh, cycle_cost_usd,
            stage_durations (dict[str, int]), vpd_in_range_pct,
            incidents (list[str]), archived_at (ISO-8601 str).

        Returns the newly-assigned record_id (e.g. "harvest_0001").
        Raises ValueError on schema violation.
        """
        wet_weight_g = harvest_data.get("wet_weight_g")
        dry_weight_g = harvest_data.get("dry_weight_g")

        if wet_weight_g is None or dry_weight_g is None:
            raise ValueError("archive_cycle requires wet_weight_g and dry_weight_g")
        try:
            wet_weight_g = float(wet_weight_g)
            dry_weight_g = float(dry_weight_g)
        except (TypeError, ValueError) as exc:
            raise ValueError("wet_weight_g and dry_weight_g must be numeric") from exc

        if wet_weight_g < 0 or dry_weight_g < 0:
            raise ValueError("wet_weight_g and dry_weight_g must be >= 0")
        if dry_weight_g > wet_weight_g:
            raise ValueError("dry_weight_g cannot exceed wet_weight_g")

        record_id = f"harvest_{len(self._data['cycles_archive']) + 1:04d}"
        record: dict[str, Any] = {"id": record_id, **harvest_data}
        self._data["cycles_archive"].append(record)
        await self._save()
        _LOGGER.info(
            "Helix Journal: archived harvest cycle %s (%.1fg dry)",
            record_id,
            dry_weight_g,
        )
        return record_id


# ── WebSocket command handlers ─────────────────────────────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_JOURNAL_GET,
    }
)
@websocket_api.async_response
async def ws_journal_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return full journal data to the frontend."""
    store: JournalStore = hass.data[DOMAIN]["journal_store"]
    connection.send_result(msg["id"], await store.async_get())


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_JOURNAL_ADD,
        vol.Required("entry"): dict,
    }
)
@websocket_api.async_response
async def ws_journal_add(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add a logbook entry and return the created record."""
    store: JournalStore = hass.data[DOMAIN]["journal_store"]
    try:
        created = await store.async_add_entry(msg["entry"])
        connection.send_result(msg["id"], created)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_entry", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_JOURNAL_MAINTENANCE,
        vol.Required("key"): str,
    }
)
@websocket_api.async_response
async def ws_journal_maintenance(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Mark a maintenance item as completed now and return updated maintenance dict."""
    store: JournalStore = hass.data[DOMAIN]["journal_store"]
    try:
        updated = await store.async_mark_maintenance(msg["key"])
        connection.send_result(msg["id"], updated)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_key", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_JOURNAL_IPM,
        vol.Required("event"): dict,
    }
)
@websocket_api.async_response
async def ws_journal_ipm(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add an IPM event and return the created record."""
    store: JournalStore = hass.data[DOMAIN]["journal_store"]
    try:
        created = await store.async_add_ipm(msg["event"])
        connection.send_result(msg["id"], created)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_event", str(exc))


# ── Public setup function (called from __init__.py) ───────────────────────────

async def async_setup_journal(hass: HomeAssistant) -> JournalStore:
    """Initialise the journal store and register all WebSocket commands.

    Called once during async_setup_entry. The store is keyed at
    hass.data[DOMAIN]['journal_store'] (integration-wide, not per config entry)
    so journal data survives entry reloads.

    Returns the JournalStore instance for reference if needed.
    """
    # Only initialise once — safe on hot-reload / multiple entries
    if "journal_store" in hass.data.get(DOMAIN, {}):
        _LOGGER.debug("Helix Journal: store already initialised — skipping")
        return hass.data[DOMAIN]["journal_store"]

    store = JournalStore(hass)
    await store.async_load()
    hass.data[DOMAIN]["journal_store"] = store

    # Register WebSocket commands — HA guards against duplicate registration
    try:
        websocket_api.async_register_command(hass, ws_journal_get)
        websocket_api.async_register_command(hass, ws_journal_add)
        websocket_api.async_register_command(hass, ws_journal_maintenance)
        websocket_api.async_register_command(hass, ws_journal_ipm)
        _LOGGER.info("Helix Journal: WebSocket commands registered")
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Helix Journal: error registering WebSocket commands")

    return store
