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
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONFIG_VERSION, CONFIG_MINOR_VERSION
from .coordinator import HelixCoordinator
from .intents import async_register_intents
from .journal_store import async_setup_journal
from .learning_store import async_setup_learning_store

_LOGGER = logging.getLogger(__name__)

WS_CMD_UPDATE_ZONE_DEVICES: str = "helix_cultivate/update_zone_devices"
WS_CMD_GET_CONFIG_SUMMARY: str = "helix_cultivate/get_config_summary"
WS_CMD_UPDATE_STAGE_TARGETS: str = "helix_cultivate/update_stage_targets"
WS_CMD_TOGGLE_DRYING_LOCK: str = "helix_cultivate/toggle_drying_lock"
WS_CMD_CLOSE_OUT_HARVEST: str = "helix_cultivate/close_out_harvest"
WS_CMD_EXPORT_RECIPE: str = "helix_cultivate/export_recipe"
WS_CMD_IMPORT_RECIPE: str = "helix_cultivate/import_recipe"
WS_CMD_UPDATE_SETTINGS_FIELDS: str = "helix_cultivate/update_settings_fields"
WS_CMD_RESET_ENERGY_CYCLE: str = "helix_cultivate/reset_energy_cycle"
WS_CMD_START_CYCLE: str = "helix_cultivate/start_cycle"
WS_CMD_ABORT_CYCLE: str = "helix_cultivate/abort_cycle"
WS_CMD_SPACE_NOW_EMPTY: str = "helix_cultivate/space_now_empty"
WS_CMD_HARVEST_COMPLETE_DRYING_BATCH: str = "helix_cultivate/harvest_complete_drying_batch"
WS_CMD_START_DEEP_CALIBRATION: str = "helix_cultivate/start_deep_calibration"
WS_CMD_START_LIVE_ACTUATOR_TEST: str = "helix_cultivate/start_live_actuator_test"
WS_CMD_GET_LEARNING_STATUS: str = "helix_cultivate/get_learning_status"
WS_CMD_APPLY_TEMPORARY_OVERRIDE: str = "helix_cultivate/apply_temporary_override"

VALID_STAGE_TARGET_KEYS: frozenset[str] = frozenset({
    "day_temp_c", "night_temp_c",
    "day_vpd_min", "day_vpd_max",
    "night_vpd_min", "night_vpd_max",
    "light_intensity_pct", "fan_speed_pct",
    "target_dli_mol",
    # v1.5.0 Part 3: the real value StageManager._duration() uses for
    # PROG_TIMEFRAME auto-advance and the stage-progression heads-up
    # warning — not a disconnected display number.
    "duration_days",
    # v1.5.0 Part 2: "photoperiod_h" deliberately removed from this set —
    # a stage's lighting-hours value is no longer independently editable;
    # it is always a live, read-only reflection of the real Growth-Mode-
    # computed schedule (growth_mode + af/pp hours), the single source of
    # truth for what's actually being scheduled.
})

# Static config-entry-backed settings fields with an explicit Save button in
# the frontend (as opposed to a live HA number/select entity) — Zone 2
# dimensions/plant count, plus the independent mid/lower canopy sensor+fan
# layer toggles saved from the same gear-icon hardware form. Extend this set
# for future draft-style settings forms.
VALID_SETTINGS_FIELD_KEYS: frozenset[str] = frozenset({
    "zone2_width_m", "zone2_depth_m", "zone2_height_m", "zone2_plant_count",
    "mid_canopy_sensor_enabled", "lower_canopy_sensor_enabled",
    "mid_canopy_fan_enabled", "lower_canopy_fan_enabled",
    # Lighting & DLI engine (Phase 1.5) — growth mode/schedule/ramp settings,
    # saved as a batch from the Grow Space card's Lighting & Growth Schedule
    # form rather than as live HA number/select entities.
    "growth_mode",
    "af_light_hours", "af_lights_on_time",
    "pp_veg_hours", "pp_veg_lights_on_time",
    "pp_flower_hours", "pp_flower_lights_on_time",
    "ramp_enabled", "ramp_preset",
    "light_wattage_w",
    # Supplemental Lighting — independent second light, its own schedule.
    "supplemental_light_type", "supplemental_mode",
    "supplemental_target_stages", "supplemental_on_time",
    "supplemental_duration_hours",
    # DLI target alerting
    "dli_alert_threshold_pct",
    # Drying-stage airflow strategy (Zone 2 and/or dedicated Drying Room)
    "drying_exhaust_min_pct", "drying_humidity_ceiling_pct",
    "drying_airflow_mode", "drying_cycle_on_min", "drying_cycle_off_min",
    # Energy & ROI — per-zone monitoring toggles, tariff editing, ROI target.
    # EM entity mappings themselves (em_zone1_s1 etc.) are hardware-mapping
    # keys saved via update_zone_devices/ALL_VALID_ZONE_DEVICE_KEYS instead.
    "em_zone1_enabled", "em_zone2_enabled", "em_drying_enabled",
    "tariff_mode", "tariff_anytime", "tariff_peak", "tariff_shoulder", "tariff_offpeak",
    "tariff_peak_start", "tariff_peak_end", "tariff_shoulder_start", "tariff_shoulder_end",
    # v1.2.8 feature settings, now exposed for editing (Part 3) — previously
    # backend-only with no settings-flow or gear-icon control surface.
    "light_high_temp_dim_c", "wind_sweep_enabled", "dew_point_margin_c",
    "preheat_lead_min", "stage_warning_lead_days",
    # Cross-zone dependency flags (v1.4.0 Part 3.1) — explicit, confirmed
    # per-zone toggles, never silently inferred.
    "zone2_depends_on_conditioning", "drying_depends_on_conditioning",
    # Reverse Cycle Unit toggles (v1.4.0 Part 5.2) — one boolean per zone,
    # beside that zone's AirCon entity picker; the mapped entity itself
    # stays a single hardware-mapping key (zone1_ac/zone2_ac/drying_ac),
    # this only changes how it's controlled.
    "zone1_is_reverse_cycle", "zone2_is_reverse_cycle", "drying_is_reverse_cycle",
    # Environmental Learning System (v1.4.0 Parts 7-10)
    "thermal_learning_enabled", "thermal_learning_duration_days",
    "thermal_learning_export_enabled", "thermal_learning_export_url",
})

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
]


# ── Entry migration ───────────────────────────────────────────────────────────

def _rename_domain_entities_to_stable_key(
    hass: HomeAssistant, config_entry: ConfigEntry, domain: str
) -> int:
    """Rename every entity of `domain` on this config entry so its entity_id
    matches {domain}.{DOMAIN}_{key} — i.e. the stable entity_description key
    that HelixSensor, HelixSelect, HelixNumber, and HelixSwitch now all pin
    entity_id to directly, rather than whatever HA's name-derived slug
    happened to produce before that fix. Skips (with a warning, not an
    error) any rename whose target entity_id is already occupied. Only
    entity_id changes — unique_id, the registry row's internal id, and
    recorder history/statistics are preserved by entity_registry's
    async_update_entity. Returns the number of entities actually renamed.
    """
    ent_reg = er.async_get(hass)
    unique_id_prefix = f"{config_entry.entry_id}_"
    renamed = 0
    for entity_entry in list(
        er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)
    ):
        if (
            entity_entry.domain != domain
            or entity_entry.platform != DOMAIN
            or not entity_entry.unique_id.startswith(unique_id_prefix)
        ):
            continue
        key = entity_entry.unique_id[len(unique_id_prefix):]
        new_entity_id = f"{domain}.{DOMAIN}_{key}"
        if entity_entry.entity_id == new_entity_id:
            continue
        if ent_reg.async_get(new_entity_id) is not None:
            _LOGGER.warning(
                "Helix Cultivate: skipped renaming %s to %s — target "
                "entity_id is already in use",
                entity_entry.entity_id,
                new_entity_id,
            )
            continue
        ent_reg.async_update_entity(entity_entry.entity_id, new_entity_id=new_entity_id)
        renamed += 1
    return renamed


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

    v1.3 migration: sensor entity_ids used to be derived from each sensor's
    human-readable `name` (e.g. sensor.helix_cultivate_lung_room_temperature),
    which rarely matched the entity_id the frontend guesses from the sensor's
    stable key (e.g. sensor.helix_cultivate_lung_temp) — see HelixSensor in
    sensor.py. Pinning entity_id going forward only affects entities created
    fresh; entity_registry.async_get_or_create() keeps an existing entity's
    entity_id untouched when it already has a registry row for the same
    unique_id, so upgrading installs would otherwise keep the mismatched,
    "—"-forever entity_ids permanently. Rename them explicitly via the entity
    registry (entity_id only — unique_id/history/statistics are unaffected).

    v1.4 migration: CONF_GROW_LIGHT/CONF_LIGHT_TYPE renamed to
    CONF_ZONE2_GROW_LIGHT/CONF_ZONE2_LIGHT_TYPE for consistency with every
    other Zone 2 hardware key. Existing values are copied to the new keys.

    v1.5 migration: the same entity_id-pinning fix and rename as v1.3,
    extended to select entities (HelixSelect in select.py) — several of
    which have the identical name-vs-key slug mismatch sensors had.

    v1.6 migration: "supplemental" removed from Main Lighting's fixture-type
    options (it's now the independent Supplemental Lighting system) — any
    existing zone2_light_type=="supplemental" moves to "led".
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

        if current_minor < 3:
            # v1.2 → v1.3: rename sensor entity_ids in place to match the
            # stable object_id key (sensor.helix_cultivate_{key}) instead of
            # whatever the pre-fix, name-derived slug happened to be. Only
            # entity_id changes — unique_id, the registry row's internal id,
            # and recorder history/statistics are preserved.
            renamed = _rename_domain_entities_to_stable_key(hass, config_entry, "sensor")
            _LOGGER.warning(
                "Helix Cultivate: migrated entry to v1.3 — renamed %d sensor "
                "entity_id(s) to their stable key so dashboard cards find them "
                "again; history and statistics were preserved for each rename.",
                renamed,
            )

        if current_minor < 4:
            # v1.3 → v1.4: CONF_GROW_LIGHT/CONF_LIGHT_TYPE ("grow_light",
            # "light_type") renamed to CONF_ZONE2_GROW_LIGHT/
            # CONF_ZONE2_LIGHT_TYPE ("zone2_grow_light", "zone2_light_type")
            # for consistency with every other Zone 2 hardware key. Copy any
            # existing values across rather than dropping them — old keys are
            # left in place (harmless, unread by current code) rather than
            # deleted, since deleting is not needed for correctness here.
            for old_key, new_key in (
                ("grow_light", "zone2_grow_light"),
                ("light_type", "zone2_light_type"),
            ):
                if old_key in new_data and new_key not in new_data:
                    new_data[new_key] = new_data[old_key]
                if old_key in new_opts and new_key not in new_opts:
                    new_opts[new_key] = new_opts[old_key]
            _LOGGER.info(
                "Helix Cultivate: migrated entry to v1.4 — copied grow_light/"
                "light_type values to their zone2-prefixed key names."
            )

        if current_minor < 5:
            # v1.4 → v1.5: same entity_id-pinning fix as v1.3, extended to
            # select entities — several (progression_mode, light_type,
            # topology, per-tier fan control modes) have a `name` that
            # doesn't slugify back to their key, so the frontend's
            # select.helix_cultivate_{key} calls were silently hitting a
            # nonexistent entity. See HelixSelect in select.py.
            renamed = _rename_domain_entities_to_stable_key(hass, config_entry, "select")
            _LOGGER.warning(
                "Helix Cultivate: migrated entry to v1.5 — renamed %d select "
                "entity_id(s) to their stable key; history and statistics "
                "were preserved for each rename.",
                renamed,
            )

        if current_minor < 6:
            # v1.5 → v1.6: "supplemental" removed from Main Lighting's
            # fixture-type options — it's now its own independent
            # Supplemental Lighting system (CONF_ZONE2_SUPPLEMENTAL_LIGHT),
            # not a zone2_light_type value. Any existing entry using it for
            # the main light's fixture type moves to LED, the safest neutral
            # default (moderate efficacy/leaf-offset, not the outlier HID
            # values).
            from .const import LIGHT_LED, LIGHT_SUPPLEMENTAL

            migrated_supplemental = False
            for opts_dict in (new_data, new_opts):
                if opts_dict.get("zone2_light_type") == LIGHT_SUPPLEMENTAL:
                    opts_dict["zone2_light_type"] = LIGHT_LED
                    migrated_supplemental = True
            if migrated_supplemental:
                _LOGGER.warning(
                    "Helix Cultivate: migrated entry to v1.6 — zone2_light_type "
                    "was 'supplemental', which is no longer a valid Main "
                    "Lighting fixture type; moved to 'led'. Configure a "
                    "second light under Supplemental Lighting if that's what "
                    "this entity actually is."
                )
            else:
                _LOGGER.info("Helix Cultivate: migrated entry to v1.6 (no data changes)")

        if current_minor < 7:
            # v1.6 → v1.7: introduces a real cycle lifecycle state
            # (CONF_CYCLE_STATE — "not_started"/"active") that gates the
            # dashboard's "No Active Cycle" empty state. Critical: this
            # entry already exists, meaning it has a real, currently-tracked
            # stage and day-count — migrate it straight to "active" so
            # nothing already running is interrupted or reset. Only entries
            # created from v1.7 onward default to "not_started" (that
            # default lives in StageManager/DEFAULT_CYCLE_STATE, applied
            # when the key is simply absent — nothing to write here for
            # brand-new entries, since they never go through this migration
            # path at all).
            from .const import CONF_CYCLE_STATE, CYCLE_STATE_ACTIVE

            new_opts[CONF_CYCLE_STATE] = CYCLE_STATE_ACTIVE
            _LOGGER.warning(
                "Helix Cultivate: migrated entry to v1.7 — cycle_state set to "
                "'active', preserving this entry's current stage and "
                "day-count exactly as-is. Only new installs from this "
                "version onward start in the new 'not_started' state."
            )

        if current_minor < 8:
            # v1.7 → v1.8: same entity_id-pinning fix as v1.3 (sensor) and
            # v1.5 (select), extended to number and switch — HelixNumber and
            # HelixSwitch never pinned entity_id at all, so HA fell back to
            # deriving it from `name`, which for most entries (e.g. key
            # "temp_setpoint" vs name "Temperature Setpoint", key
            # "breeze_upper" vs name "Upper Canopy Breeze Mode") does not
            # slugify back to the key. Every number.set_value/switch.turn_on
            # call in the frontend targets number.helix_cultivate_{key} /
            # switch.helix_cultivate_{key} directly, so those calls were
            # silently hitting nonexistent entities — this is the actual
            # root cause behind sliders and toggles that appear to work but
            # never take effect.
            renamed_number = _rename_domain_entities_to_stable_key(hass, config_entry, "number")
            renamed_switch = _rename_domain_entities_to_stable_key(hass, config_entry, "switch")
            _LOGGER.warning(
                "Helix Cultivate: migrated entry to v1.8 — renamed %d number "
                "and %d switch entity_id(s) to their stable key so live "
                "sliders/toggles reach the entity they display; history and "
                "statistics were preserved for each rename.",
                renamed_number,
                renamed_switch,
            )

        if current_minor < 9:
            # v1.8 → v1.9: the v1.6 -> v1.7 migration above set cycle_state
            # to "active" for every already-existing entry but never wrote
            # CONF_STAGE_START_DATE into persisted options — its own comment
            # claimed day-count was preserved, but StageManager.__init__
            # re-reads this value fresh from config on every reload and
            # falls back to no start date (0 elapsed days) when absent, so
            # every reload since v1.7 shipped has silently reset an
            # already-affected install's day-count reference point. There is
            # no way to recover the true original start date retroactively
            # (it was never recorded) — this writes today, this migration's
            # execution date, as the new stable reference point so
            # day-counting starts working correctly from here on. Entries
            # that already have a real CONF_STAGE_START_DATE (new installs
            # via start_cycle(), or anything migrated after this fix ships)
            # are left untouched.
            from .const import CONF_STAGE_START_DATE

            if not new_opts.get(CONF_STAGE_START_DATE) and not new_data.get(CONF_STAGE_START_DATE):
                new_opts[CONF_STAGE_START_DATE] = dt_util.now().date().isoformat()
                _LOGGER.warning(
                    "Helix Cultivate: migrated entry to v1.9 — stage_start_date "
                    "was never persisted by the v1.7 migration, so day-count "
                    "has been silently frozen since; set to today (%s) as the "
                    "new reference point going forward. The true original "
                    "start date could not be recovered.",
                    new_opts[CONF_STAGE_START_DATE],
                )
            else:
                _LOGGER.info("Helix Cultivate: migrated entry to v1.9 (no data changes)")

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

    # Previous-cycle Energy & ROI archive (2.7) — from the last Reset button
    # click or the last full harvest close-out, whichever is more recent;
    # None if neither has ever happened for this entry.
    previous_cycle_energy: Optional[dict[str, Any]] = None
    journal = hass.data.get(DOMAIN, {}).get("journal_store")
    if journal is not None:
        previous_cycle_energy = journal.get_previous_cycle_energy(entry.entry_id)

    connection.send_result(
        msg["id"],
        {
            "entry_id": entry.entry_id,
            "hardware": hw_map,
            "is_drying_unlocked": bool(
                merged.get(CONF_DRYING_CUSTOM_UNLOCKED, DEFAULT_DRYING_CUSTOM_UNLOCKED)
            ),
            "previous_cycle_energy": previous_cycle_energy,
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

    v1.5.0 Part 5: also patches the live coordinator's in-memory `_config`
    immediately, the same way ws_update_settings_fields already does —
    verified directly (not assumed) that a save for the CURRENTLY ACTIVE
    stage was otherwise only picked up once the config-entry-triggered
    reload actually completed, rather than on the very next control-loop
    tick. StageManager._profile() has no caching of its own (recomputed
    fresh from this dict every call), so patching it here closes that gap
    without waiting on the reload at all.
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

    coordinator: Optional[HelixCoordinator] = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is not None:
        coordinator._config[key] = merged

    new_options: dict[str, Any] = {**entry.options, key: merged}
    hass.config_entries.async_update_entry(entry, options=new_options)
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_APPLY_TEMPORARY_OVERRIDE,
        vol.Required("context"): vol.In(["day", "night"]),
        vol.Required("kind"): vol.In(["temp", "vpd", "light"]),
        vol.Required("value"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_apply_temporary_override(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Part 4 (v1.5.0): set a live, temporary override on Primary Grow
    Space for one context/kind combination — in-memory only, never
    persisted, cleared automatically the moment the active stage changes.
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
        coordinator.apply_temporary_override(msg["context"], msg["kind"], msg["value"])
        connection.send_result(msg["id"], {"success": True})
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_UPDATE_SETTINGS_FIELDS,
        vol.Required("entry_id"): str,
        vol.Required("fields"): dict,
    }
)
@websocket_api.async_response
async def ws_update_settings_fields(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Persist explicit-Save static config fields (e.g. Zone 2 dimensions).

    Only keys present in VALID_SETTINGS_FIELD_KEYS are accepted. Routed
    through the coordinator's debounced queue_option_write() — the same path
    persistent number/select setters use — so a batch of fields saved
    together from one form coalesces into a single config-entry write (and
    therefore a single reload) rather than one per field.
    """
    entry: Optional[ConfigEntry] = hass.config_entries.async_get_entry(msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    coordinator: Optional[HelixCoordinator] = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "coordinator_not_found", "Coordinator not loaded")
        return

    validated: dict[str, Any] = {
        k: v for k, v in msg["fields"].items() if k in VALID_SETTINGS_FIELD_KEYS
    }
    # v1.5.0 Part 1.2: Growth Mode is locked server-side too, not just
    # disabled in the UI — the same defense-in-depth pattern already used
    # for space_now_empty()'s topology guard. Reused across BOTH surfaces
    # that can write growth_mode (Plant Cycle's toggle and Primary Grow
    # Space's own copy), since both route through this one handler.
    if "growth_mode" in validated and coordinator.is_zone2_occupied():
        connection.send_error(
            msg["id"], "growth_mode_locked",
            "Growth Mode is locked while a cycle occupies Primary Grow Space.",
        )
        return
    for field_key, field_value in validated.items():
        coordinator._config[field_key] = field_value
        coordinator.queue_option_write(field_key, field_value)
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
        vol.Required("type"): WS_CMD_RESET_ENERGY_CYCLE,
    }
)
@websocket_api.async_response
async def ws_reset_energy_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Archive the current cycle's energy totals as Previous Cycle and zero
    the live accumulators — a lighter-weight action than a full harvest
    close-out (2.6), for growers who want to start a fresh cost tally
    mid-cycle (e.g. after a mother-plant takes vs. what a full 12-week
    flower run cost) without archiving stage durations/yield/etc.

    Returns the archived previous-cycle record for the frontend.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    record = await coordinator.reset_energy_cycle()
    connection.send_result(msg["id"], {"previous_cycle_energy": record})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_START_CYCLE,
        vol.Required("growth_mode"): str,
        vol.Required("start_date"): str,
        vol.Required("starting_stage"): str,
    }
)
@websocket_api.async_response
async def ws_start_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """"Start New Cycle" (Part 1.2) — moves cycle_state from "not_started"
    to "active", with a possibly-backdated start_date and a possibly-
    non-default starting_stage.
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
        await coordinator.start_cycle(
            msg["growth_mode"], msg["start_date"], msg["starting_stage"]
        )
        connection.send_result(msg["id"], {"success": True})
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_ABORT_CYCLE,
    }
)
@websocket_api.async_response
async def ws_abort_cycle(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """"Abort Cycle" (Part 1.5) — a second, clearly-distinct destructive
    action from harvest close-out: no harvest record, no weight entry.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return

    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    await coordinator.abort_cycle()
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_SPACE_NOW_EMPTY,
    }
)
@websocket_api.async_response
async def ws_space_now_empty(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """"Harvest — Space Now Empty" (Part 4.2) — only meaningful with a
    dedicated Drying Room configured; coordinator.space_now_empty() raises
    ValueError otherwise, which this surfaces as invalid_input rather than
    letting the frontend's own topology check be the only guard.
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
        await coordinator.space_now_empty()
        connection.send_result(msg["id"], {"success": True})
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_HARVEST_COMPLETE_DRYING_BATCH,
        vol.Required("wet_weight_g"): vol.Coerce(float),
        vol.Required("dry_weight_g"): vol.Coerce(float),
    }
)
@websocket_api.async_response
async def ws_harvest_complete_drying_batch(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """"Harvest Complete" (Part 9) for the batch currently occupying the
    dedicated Drying Room — closes out CONF_DRYING_CYCLE_ID specifically,
    independent of whatever Primary Grow Space is doing concurrently.
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
        result = await coordinator.harvest_complete_drying_batch(
            msg["wet_weight_g"], msg["dry_weight_g"]
        )
        connection.send_result(msg["id"], result)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_START_DEEP_CALIBRATION,
        vol.Required("zone"): str,
    }
)
@websocket_api.async_response
async def ws_start_deep_calibration(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Part 7.4/7.10: start a Deep Calibration test for one zone
    ("zone2"/"drying"/"conditioning") — rejected with the specific reason
    if that zone isn't currently eligible.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return
    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    from .learning_engine import LearningEngine

    try:
        engine = LearningEngine(coordinator)
        current_temp = coordinator._current_zone_temp_for_learning(msg["zone"])
        outdoor_temp = (coordinator.data or {}).get("climate", {}).get("outdoor_temp_c")
        test = await engine.start_deep_calibration(msg["zone"], current_temp, outdoor_temp)
        connection.send_result(msg["id"], test)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_START_LIVE_ACTUATOR_TEST,
        vol.Required("zone"): str,
        vol.Optional("thermostat_controlled", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_start_live_actuator_test(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Part 7.4/7.10: start Live Actuator Response Testing for one zone —
    available regardless of occupancy."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return
    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    from .learning_engine import LearningEngine

    try:
        engine = LearningEngine(coordinator)
        current_temp = coordinator._current_zone_temp_for_learning(msg["zone"])
        dependent_temps: dict[str, float] = {}
        if msg["zone"] == "conditioning":
            for dependent in coordinator.conditioning_room_dependent_zones():
                dep_temp = coordinator._current_zone_temp_for_learning(dependent)
                if dep_temp is not None:
                    dependent_temps[dependent] = dep_temp
        test = await engine.start_live_actuator_test(
            msg["zone"], msg["thermostat_controlled"],
            current_temp=current_temp, dependent_temps=dependent_temps,
        )
        connection.send_result(msg["id"], test)
    except ValueError as exc:
        connection.send_error(msg["id"], "invalid_input", str(exc))


@websocket_api.websocket_command(
    {
        vol.Required("type"): WS_CMD_GET_LEARNING_STATUS,
    }
)
@websocket_api.async_response
async def ws_get_learning_status(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Returns the Environmental Learning Settings tab's display state:
    current learning_state, per-zone eligibility, and any active test."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        connection.send_error(msg["id"], "no_entry", "No Helix Cultivate config entry found")
        return
    coordinator = hass.data.get(DOMAIN, {}).get(entries[0].entry_id)
    if coordinator is None:
        connection.send_error(msg["id"], "no_coordinator", "Coordinator not initialised")
        return

    from .const import CONF_ENABLE_DRYING_ENVIRONMENT, CONF_LEARNING_STARTED_AT
    from .learning_engine import LearningEngine

    engine = LearningEngine(coordinator)
    store = hass.data.get(DOMAIN, {}).get("learning_store")
    connection.send_result(msg["id"], {
        "learning_state": engine.learning_state(),
        "started_at": coordinator._get(CONF_LEARNING_STARTED_AT),
        "zone2_occupied": coordinator.is_zone2_occupied(),
        "drying_occupied": coordinator.is_drying_occupied(),
        "drying_enabled": bool(coordinator._get(CONF_ENABLE_DRYING_ENVIRONMENT, False)),
        "conditioning_eligible": coordinator.is_conditioning_room_calibration_eligible(),
        "active_test": store.get_active_test() if store else None,
    })


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
        websocket_api.async_register_command(hass, ws_apply_temporary_override)
        websocket_api.async_register_command(hass, ws_toggle_drying_lock)
        websocket_api.async_register_command(hass, ws_close_out_harvest)
        websocket_api.async_register_command(hass, ws_export_recipe)
        websocket_api.async_register_command(hass, ws_import_recipe)
        websocket_api.async_register_command(hass, ws_update_settings_fields)
        websocket_api.async_register_command(hass, ws_reset_energy_cycle)
        websocket_api.async_register_command(hass, ws_start_cycle)
        websocket_api.async_register_command(hass, ws_abort_cycle)
        websocket_api.async_register_command(hass, ws_space_now_empty)
        websocket_api.async_register_command(hass, ws_harvest_complete_drying_batch)
        websocket_api.async_register_command(hass, ws_start_deep_calibration)
        websocket_api.async_register_command(hass, ws_start_live_actuator_test)
        websocket_api.async_register_command(hass, ws_get_learning_status)
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

    # Initialise Environmental Learning System store (idempotent on reload)
    await async_setup_learning_store(hass)

    # Register zone hardware-mapping WebSocket commands (idempotent on reload)
    _async_register_zone_device_ws_commands(hass)

    # Register Voice Assist intents (idempotent on reload)
    async_register_intents(hass)

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

    # Cache-busting tied to the actual manifest.json release version (e.g.
    # "1.2.8"), not CONFIG_VERSION/CONFIG_MINOR_VERSION — those only bump
    # when a config-entry schema migration is actually needed, which is far
    # less often than every release, so a browser could keep serving a
    # stale cached copy across several real releases in a row otherwise.
    try:
        integration = await async_get_integration(hass, DOMAIN)
        cache_bust = str(integration.version)
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Helix Cultivate: could not resolve manifest version for cache-busting; "
            "falling back to config schema version"
        )
        cache_bust = f"{CONFIG_VERSION}.{CONFIG_MINOR_VERSION}"

    module_url = f"/helix_cultivate_www/helix-panel.js?v={cache_bust}"

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
    glance_card_url = f"/helix_cultivate_www/helix-glance-card.js?v={cache_bust}"
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
