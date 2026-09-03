"""Helix Cultivate — HA custom integration initialisation."""
from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.components.frontend import add_extra_js_url, async_register_built_in_panel
from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN, CONFIG_VERSION, CONFIG_MINOR_VERSION
from .coordinator import HelixCoordinator
from .journal_store import async_setup_journal

_LOGGER = logging.getLogger(__name__)

WS_CMD_UPDATE_ZONE_DEVICES: str = "helix_cultivate/update_zone_devices"
WS_CMD_GET_CONFIG_SUMMARY: str = "helix_cultivate/get_config_summary"
WS_CMD_UPDATE_STAGE_TARGETS: str = "helix_cultivate/update_stage_targets"
WS_CMD_TOGGLE_DRYING_LOCK: str = "helix_cultivate/toggle_drying_lock"
WS_CMD_CLOSE_OUT_HARVEST: str = "helix_cultivate/close_out_harvest"
WS_CMD_EXPORT_RECIPE: str = "helix_cultivate/export_recipe"
WS_CMD_IMPORT_RECIPE: str = "helix_cultivate/import_recipe"

VALID_STAGE_TARGET_KEYS: frozenset[str] = frozenset({
    "day_temp_c", "night_temp_c",
    "day_vpd_min", "day_vpd_max",
    "night_vpd_min", "night_vpd_max",
    "light_intensity_pct", "photoperiod_h", "fan_speed_pct",
})

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]


# ── Entry migration ───────────────────────────────────────────────────────────

async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entry to the current schema version.

    Version 1.1 is the initial production schema. Future minor-version bumps
    (e.g. adding fertigation keys) increment MINOR_VERSION only and are handled
    here as no-ops with a data-patching step so existing entries remain valid.

    v1.2 migration: Zone1/Zone2 entity-ID values were inverted between
    options_flow (user-facing) and climate_engine (control) prior to this
    version. Swap stored values for all zone-numbered key pairs so existing
    entries continue controlling the same physical hardware after the fix.
    The zone1_backup_heater entity ID is cleared (no zone2 counterpart exists)
    and must be reconfigured by the user via Settings after upgrade.
    """
    from .const import (  # local import avoids circular at module level
        CONF_ZONE1_AC, CONF_ZONE2_AC,
        CONF_ZONE1_HEATER, CONF_ZONE2_HEATER,
        CONF_ZONE1_IS_REVERSE_CYCLE, CONF_ZONE2_IS_REVERSE_CYCLE,
        CONF_ZONE1_HUMIDIFIER, CONF_ZONE2_HUMIDIFIER,
        CONF_ZONE1_DEHUMIDIFIER, CONF_ZONE2_DEHUMIDIFIER,
        CONF_ZONE1_REVERSE_CYCLE, CONF_ZONE2_REVERSE_CYCLE,
        CONF_ZONE1_NAME, CONF_ZONE2_NAME,
        CONF_EM_ZONE1_SENSORS, CONF_EM_ZONE2_SENSORS,
        CONF_ZONE1_BACKUP_HEATER,
    )

    _ZONE_SWAP_PAIRS: list[tuple[str, str]] = [
        (CONF_ZONE1_AC, CONF_ZONE2_AC),
        (CONF_ZONE1_HEATER, CONF_ZONE2_HEATER),
        (CONF_ZONE1_IS_REVERSE_CYCLE, CONF_ZONE2_IS_REVERSE_CYCLE),
        (CONF_ZONE1_HUMIDIFIER, CONF_ZONE2_HUMIDIFIER),
        (CONF_ZONE1_DEHUMIDIFIER, CONF_ZONE2_DEHUMIDIFIER),
        (CONF_ZONE1_REVERSE_CYCLE, CONF_ZONE2_REVERSE_CYCLE),
        (CONF_ZONE1_NAME, CONF_ZONE2_NAME),
        (CONF_EM_ZONE1_SENSORS, CONF_EM_ZONE2_SENSORS),
    ]

    def _swap_zone_pairs(d: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of d with all zone-numbered key-pairs swapped.

        Only touches keys that are already present — absence means the key was
        never configured, so there is nothing to swap. Both keys in a pair are
        written simultaneously from the pre-swap snapshot to avoid clobbering.
        """
        d = dict(d)
        for key_a, key_b in _ZONE_SWAP_PAIRS:
            val_a = d.get(key_a)
            val_b = d.get(key_b)
            if key_a in d or key_b in d:
                # Write B's old value into A's slot (and vice-versa)
                if val_b is not None:
                    d[key_a] = val_b
                elif key_a in d:
                    del d[key_a]
                if val_a is not None:
                    d[key_b] = val_a
                elif key_b in d:
                    del d[key_b]
        # Clear asymmetric backup-heater entity — can't safely re-wire to the
        # opposite room without user confirmation. Threshold scalar is retained.
        d.pop(CONF_ZONE1_BACKUP_HEATER, None)
        return d

    current_version = config_entry.version
    current_minor = config_entry.minor_version

    _LOGGER.debug(
        "Migrating Helix Cultivate config entry from v%s.%s to v%s.%s",
        current_version,
        current_minor,
        CONFIG_VERSION,
        CONFIG_MINOR_VERSION,
    )

    if current_version == 1:
        # ── Minor version migrations within v1 ────────────────────────────────
        new_data: dict[str, Any] = {**config_entry.data}
        new_opts: dict[str, Any] = {**config_entry.options}

        if current_minor < 1:
            # v1.0 → v1.1: initial schema — no transformation needed
            _LOGGER.info("Helix Cultivate: migrated entry to v1.1 (no data changes)")

        if current_minor < 2:
            # v1.1 → v1.2: correct Zone1/Zone2 entity-ID inversion.
            # Hardware mappings live in entry.options (written by options_flow).
            # Zone display names can live in entry.data (written by config_flow)
            # or entry.options (if updated via options_flow later). Patch both.
            new_data = _swap_zone_pairs(new_data)
            new_opts = _swap_zone_pairs(new_opts)
            _LOGGER.warning(
                "Helix Cultivate: migrated entry to v1.2 — swapped %d zone-numbered "
                "key pairs in data + options to correct the Zone1/Zone2 meaning "
                "inversion. zone1_backup_heater entity cleared — please reconfigure "
                "via Settings > Hardware Mapping.",
                len(_ZONE_SWAP_PAIRS),
            )

        hass.config_entries.async_update_entry(
            config_entry,
            data=new_data,
            options=new_opts,
            version=CONFIG_VERSION,
            minor_version=CONFIG_MINOR_VERSION,
        )
        return True

    # Unknown major version — cannot migrate
    _LOGGER.error(
        "Helix Cultivate: cannot migrate config entry from unknown version %s.%s",
        current_version,
        current_minor,
    )
    return False


# ── WebSocket command handlers (zone hardware mapping) ────────────────────────

@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_UPDATE_ZONE_DEVICES,
        vol.Required("entry_id"): str,
        vol.Required("devices"): dict,
    }
)
@websocket_api.async_response
async def ws_update_zone_devices(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist a hardware-key → entity_id mapping update to the config entry.

    Only keys present in ALL_VALID_ZONE_DEVICE_KEYS are accepted, preventing
    arbitrary key injection into config entry options from the frontend.
    """
    from .const import ALL_VALID_ZONE_DEVICE_KEYS

    entry: Optional[ConfigEntry] = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    devices: dict[str, Any] = {
        k: (v or None)
        for k, v in msg["devices"].items()
        if k in ALL_VALID_ZONE_DEVICE_KEYS
    }
    new_options: dict[str, Any] = {**entry.options, **devices}
    hass.config_entries.async_update_entry(entry, options=new_options)
    # Note: triggers _async_options_updated → full reload. Desired: hardware
    # remap requires the coordinator to re-read entity IDs on restart.
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_GET_CONFIG_SUMMARY,
    }
)
@websocket_api.async_response
async def ws_get_config_summary(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the active config entry ID, hardware mapping, and drying lock state."""
    from .const import (
        ALL_VALID_ZONE_DEVICE_KEYS,
        CONF_DRYING_CUSTOM_UNLOCKED,
        DEFAULT_DRYING_CUSTOM_UNLOCKED,
    )

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return

    entry = entries[0]
    merged: dict[str, Any] = {**entry.data, **entry.options}
    hw_map: dict[str, Any] = {
        k: merged.get(k) for k in ALL_VALID_ZONE_DEVICE_KEYS if merged.get(k)
    }
    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "hardware": hw_map,
            "is_drying_unlocked": bool(
                merged.get(CONF_DRYING_CUSTOM_UNLOCKED, DEFAULT_DRYING_CUSTOM_UNLOCKED)
            ),
        },
    )


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_TOGGLE_DRYING_LOCK,
        vol.Required("entry_id"): str,
        vol.Required("unlocked"): bool,
    }
)
@websocket_api.async_response
async def ws_toggle_drying_lock(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Toggle whether the drying zone uses the fixed 60/60 cure profile or
    a user-customisable day/night stage profile."""
    from .const import CONF_DRYING_CUSTOM_UNLOCKED

    entry: Optional[ConfigEntry] = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    new_options: dict[str, Any] = {
        **entry.options,
        CONF_DRYING_CUSTOM_UNLOCKED: msg["unlocked"],
    }
    hass.config_entries.async_update_entry(entry, options=new_options)
    connection.send_result(msg["id"], {"success": True, "unlocked": msg["unlocked"]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_UPDATE_STAGE_TARGETS,
        vol.Required("entry_id"): str,
        vol.Required("stage"): str,
        vol.Required("targets"): dict,
    }
)
@websocket_api.async_response
async def ws_update_stage_targets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist user-customised day/night stage targets to the config entry.

    Only keys present in VALID_STAGE_TARGET_KEYS are accepted. Values are
    merged into the existing `stage_targets_{stage}` dict rather than
    replacing it, so partial updates (e.g. a single slider change) do not
    clobber other previously-persisted keys for the same stage.
    """
    from .const import STAGE_SEQUENCE

    if msg["stage"] not in STAGE_SEQUENCE:
        connection.send_error(msg["id"], "invalid_stage", "Unknown grow stage slug")
        return

    entry: Optional[ConfigEntry] = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    validated: dict[str, Any] = {
        k: v for k, v in msg["targets"].items() if k in VALID_STAGE_TARGET_KEYS
    }
    key = f"stage_targets_{msg['stage']}"
    existing: dict[str, Any] = entry.options.get(key, {})
    merged: dict[str, Any] = {**existing, **validated}
    new_options: dict[str, Any] = {**entry.options, key: merged}
    hass.config_entries.async_update_entry(entry, options=new_options)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_CLOSE_OUT_HARVEST,
        vol.Required("wet_weight_g"): vol.Coerce(float),
        vol.Required("dry_weight_g"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_close_out_harvest(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Archive the completed grow cycle and reset all cycle counters.

    Returns the full harvest record (including record_id) for the frontend
    Harvest Report. Errors (schema violation, missing journal store) are
    surfaced as a WS error rather than raising into the event loop.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    try:
        result = await coordinator.close_out_harvest(
            msg["wet_weight_g"], msg["dry_weight_g"]
        )
        connection.send_result(msg["id"], result)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_EXPORT_RECIPE,
    }
)
@websocket_api.async_response
async def ws_export_recipe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the currently-resolved per-stage profiles as YAML text."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    try:
        yaml_text = coordinator.stage_manager.export_current_recipe()
        connection.send_result(msg["id"], {"yaml_text": yaml_text})
    except Exception as exc:  # noqa: BLE001
        connection.send_error(msg["id"], "export_failed", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_IMPORT_RECIPE,
        vol.Required("entry_id"): str,
        vol.Required("yaml_text"): str,
    }
)
@websocket_api.async_response
async def ws_import_recipe(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Validate and apply a pasted recipe YAML, persisting each stage's
    resolved values to the config entry options under the
    `stage_targets_{stage}` key pattern."""
    entry: Optional[ConfigEntry] = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    try:
        coordinator.stage_manager.import_recipe(msg["yaml_text"])
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_recipe", str(exc))
        return

    # Persist each imported stage's targets to the config entry so they
    # survive a reload (import_recipe() only updated in-memory config).
    new_options: dict[str, Any] = dict(entry.options)
    from .const import STAGE_SEQUENCE

    for stage in STAGE_SEQUENCE:
        key = f"stage_targets_{stage}"
        val = coordinator.stage_manager._config.get(key)
        if val is not None:
            new_options[key] = val
    hass.config_entries.async_update_entry(entry, options=new_options)

    connection.send_result(msg["id"], {"ok": True})


def _async_register_zone_device_ws_commands(hass: HomeAssistant) -> None:
    """Register the zone-device WebSocket commands (idempotent across reloads)."""
    if hass.data.get(DOMAIN, {}).get("_zone_ws_registered"):
        return
    try:
        websocket_api.async_register_command(hass, ws_update_zone_devices)
        websocket_api.async_register_command(hass, ws_get_config_summary)
        websocket_api.async_register_command(hass, ws_update_stage_targets)
        websocket_api.async_register_command(hass, ws_toggle_drying_lock)
        websocket_api.async_register_command(hass, ws_close_out_harvest)
        websocket_api.async_register_command(hass, ws_export_recipe)
        websocket_api.async_register_command(hass, ws_import_recipe)
        hass.data.setdefault(DOMAIN, {})["_zone_ws_registered"] = True
        _LOGGER.info("Helix Cultivate: zone-device WebSocket commands registered")
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Helix Cultivate: error registering zone-device WebSocket commands"
        )


# ── Setup ─────────────────────────────────────────────────────────────────────

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Helix Cultivate from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Instantiate the coordinator
    coordinator = HelixCoordinator(hass, entry)

    # Perform initial data fetch — raises ConfigEntryNotReady on failure
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as exc:
        raise ConfigEntryNotReady(
            f"Helix Cultivate coordinator failed initial refresh: {exc}"
        ) from exc

    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Initialise journal store + register WebSocket commands (idempotent on reload)
    await async_setup_journal(hass)

    # Register zone hardware-mapping WebSocket commands (idempotent on reload)
    _async_register_zone_device_ws_commands(hass)

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the options flow update listener so the coordinator reloads
    # when the user changes settings via the options flow — no restart needed.
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # ── Register frontend static path & sidebar panel ─────────────────────────
    await _async_register_panel(hass)

    return True


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the Helix Cultivate LitElement sidebar panel."""
    try:
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    url_path="/helix_cultivate_www",
                    path=hass.config.path("custom_components/helix_cultivate/www"),
                    cache_headers=False,
                )
            ]
        )
    except RuntimeError:
        # Static path is already registered — expected on hot-reload, safe to ignore.
        _LOGGER.debug(
            "Helix Cultivate: static path /helix_cultivate_www already registered"
        )
    except Exception:
        _LOGGER.exception(
            "Helix Cultivate: unexpected error registering static path"
        )

    module_url = (
        f"/helix_cultivate_www/helix-panel.js"
        f"?v={CONFIG_VERSION}.{CONFIG_MINOR_VERSION}"
    )

    try:
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="Helix Cultivate",
            sidebar_icon="mdi:sprout",
            frontend_url_path="helix-cultivate-panel",
            config={
                "_panel_custom": {
                    "name": "helix-panel",
                    "module_url": module_url,
                    "embed_iframe": False,
                    "trust_external_script": True,
                }
            },
            require_admin=False,
        )
    except ValueError:
        # Panel is already registered — expected on hot-reload, safe to ignore.
        _LOGGER.debug(
            "Helix Cultivate: panel helix-cultivate-panel already registered"
        )
    except Exception:
        _LOGGER.exception(
            "Helix Cultivate: unexpected error registering sidebar panel"
        )

    # ── Register the standalone glance card as an extra Lovelace module ───────
    # This makes <helix-glance-card> available on all dashboards (not just the
    # built-in sidebar panel) without requiring the user to add it manually as
    # a Lovelace resource.
    glance_card_url = (
        f"/helix_cultivate_www/helix-glance-card.js"
        f"?v={CONFIG_VERSION}.{CONFIG_MINOR_VERSION}"
    )
    try:
        add_extra_js_url(hass, glance_card_url)
    except Exception:
        _LOGGER.exception(
            "Helix Cultivate: unexpected error registering helix-glance-card module URL"
        )


# ── Options reload listener ───────────────────────────────────────────────────

async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when the user updates options.

    This triggers a full teardown + re-setup so the coordinator picks up
    new device mappings without a manual HA restart.
    """
    _LOGGER.debug("Helix Cultivate: options updated, reloading entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


# ── Teardown ──────────────────────────────────────────────────────────────────

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Helix Cultivate config entry."""
    # Cancel any running breeze tasks inside the coordinator
    coordinator: HelixCoordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator is not None:
        await coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
