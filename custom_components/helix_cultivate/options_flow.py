"""Options flow for Helix Cultivate — live reconfiguration without restart.

All hardware mapping lives here. Onboarding (config_flow) is instant; every
device selector, safety parameter, and zone management action is handled in
these steps.

Safe config lookup pattern:
    entry.options.get(KEY, entry.data.get(KEY, DEFAULT))
ensures updates never wipe previously saved values.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    ALGO_BANG_BANG,
    ALGO_OPTIONS,
    CONF_ANTI_SHORT_CYCLE_MIN,
    CONF_BREEZE_ENABLED,
    CONF_BREEZE_VARIANCE,
    CONF_CONTROL_ALGORITHM,
    CONF_DLI_SENSOR,
    CONF_DRYING_AC,
    CONF_DRYING_CIRCULATION_FAN,
    CONF_DRYING_DEHUMIDIFIER,
    CONF_DRYING_ENABLED,
    CONF_DRYING_EXHAUST_FAN,
    CONF_DRYING_HEATER,
    CONF_DRYING_HUMIDITY_OFFSET,
    CONF_DRYING_HUMIDITY_SENSOR,
    CONF_DRYING_IS_REVERSE_CYCLE,
    CONF_DRYING_LIGHT,
    CONF_DRYING_TEMP_OFFSET,
    CONF_DRYING_TEMP_SENSOR,
    CONF_DRYING_ZONE_NAME,
    CONF_ELECTRICITY_RATE,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_EXHAUST_FAN,
    CONF_EXHAUST_MIN_PCT,
    CONF_FAN_CONTROL_MODE,
    CONF_GROW_CAMERA,
    CONF_GROW_LIGHT,
    CONF_HEATER_CUTOFF_C,
    CONF_LEAF_TEMP_OFFSET_C,
    CONF_NOTIFY_TARGET,
    CONF_LIGHT_DIMMABLE,
    CONF_LIGHT_TYPE,
    CONF_LOWER_CANOPY_HUMIDITY_SENSOR,
    CONF_LOWER_CANOPY_TEMP_SENSOR,
    CONF_LOWER_FANS,
    CONF_LOWER_HUMIDITY_OFFSET,
    CONF_LOWER_TEMP_OFFSET,
    CONF_LUNG_HUMIDITY_OFFSET,
    CONF_LUNG_HUMIDITY_SENSOR,
    CONF_LUNG_TEMP_OFFSET,
    CONF_LUNG_TEMP_SENSOR,
    CONF_MID_CANOPY_HUMIDITY_SENSOR,
    CONF_MID_CANOPY_TEMP_SENSOR,
    CONF_MID_FANS,
    CONF_MID_HUMIDITY_OFFSET,
    CONF_MID_TEMP_OFFSET,
    CONF_OUTDOOR_WEATHER_ENTITY,
    CONF_PRIMARY_HUMIDITY_OFFSET,
    CONF_PRIMARY_HUMIDITY_SENSOR,
    CONF_PRIMARY_TEMP_OFFSET,
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_PROGRESSION_MODE,
    CONF_RECIPE_FILE,
    CONF_SAFETY_HIGH_RH_PCT,
    CONF_SAFETY_HIGH_TEMP_C,
    CONF_SAFETY_LOW_RH_PCT,
    CONF_SAFETY_LOW_TEMP_C,
    CONF_SENSOR_DROPOUT_MIN,
    CONF_SMOOTH_GLIDES,
    CONF_STAGE_START_DATE,
    CONF_SUNRISE_RAMP_MIN,
    CONF_THERMAL_RUNAWAY_C,
    CONF_TOPOLOGY,
    CONF_UPPER_CANOPY_HUMIDITY_SENSOR,
    CONF_UPPER_CANOPY_TEMP_SENSOR,
    CONF_UPPER_FANS,
    CONF_UPPER_HUMIDITY_OFFSET,
    CONF_UPPER_TEMP_OFFSET,
    CONF_ZONE1_AC,
    CONF_ZONE1_BACKUP_HEATER,
    CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C,
    CONF_ZONE1_DEHUMIDIFIER,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_HUMIDIFIER,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE1_NAME,
    CONF_ZONE1_REVERSE_CYCLE,
    CONF_ZONE2_AC,
    CONF_ZONE2_DEHUMIDIFIER,
    CONF_ZONE2_HEATER,
    CONF_ZONE2_HUMIDIFIER,
    CONF_ZONE2_IS_REVERSE_CYCLE,
    CONF_ZONE2_NAME,
    CONF_ZONE2_PLANT_COUNT,
    CONF_ZONE2_REVERSE_CYCLE,
    CONF_ZONE2_WIDTH_M,
    CONF_ZONE2_DEPTH_M,
    CONF_ZONE2_HEIGHT_M,
    DEFAULT_ANTI_SHORT_CYCLE_MIN,
    DEFAULT_BACKUP_HEATER_THRESHOLD_C,
    DEFAULT_DRYING_ZONE_NAME,
    DEFAULT_EXHAUST_MIN_PCT,
    DEFAULT_HEATER_CUTOFF_C,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DEFAULT_SAFETY_HIGH_RH_PCT,
    DEFAULT_SAFETY_HIGH_TEMP_C,
    DEFAULT_SAFETY_LOW_RH_PCT,
    DEFAULT_SAFETY_LOW_TEMP_C,
    DEFAULT_SENSOR_DROPOUT_MIN_CFG,
    DEFAULT_SUNRISE_RAMP_MIN,
    DEFAULT_THERMAL_RUNAWAY_C,
    DEFAULT_ZONE1_NAME,
    DEFAULT_ZONE2_NAME,
    DOMAIN,
    FAN_CONTROL_CONTINUOUS,
    FAN_CONTROL_OPTIONS,
    LIGHT_LED,
    LIGHT_TYPE_OPTIONS,
    PROG_MANUAL,
    PROG_OPTIONS,
    STAGE_GERMINATION,
    STAGE_SEQUENCE,
    TOPOLOGY_COORDINATED,
    TOPOLOGY_OPTIONS,
    TOPOLOGY_STANDALONE,
    CONF_TARIFF_MODE,
    CONF_TARIFF_ANYTIME,
    CONF_TARIFF_PEAK,
    CONF_TARIFF_SHOULDER,
    CONF_TARIFF_OFFPEAK,
    CONF_TARIFF_PEAK_START,
    CONF_TARIFF_PEAK_END,
    CONF_TARIFF_SHOULDER_START,
    CONF_TARIFF_SHOULDER_END,
    CONF_EM_ZONE1_S1,
    CONF_EM_ZONE1_S2,
    CONF_EM_ZONE1_S3,
    CONF_EM_ZONE1_S4,
    CONF_EM_ZONE2_S1,
    CONF_EM_ZONE2_S2,
    CONF_EM_ZONE2_S3,
    CONF_EM_ZONE2_S4,
    CONF_EM_DRYING_S1,
    CONF_EM_DRYING_S2,
    CONF_EM_DRYING_S3,
    CONF_EM_DRYING_S4,
    CONF_EM_GLOBAL_S1,
    CONF_EM_GLOBAL_S2,
    CONF_EM_GLOBAL_S3,
    CONF_EM_GLOBAL_S4,
    CONF_EM_ZONE1_SENSORS,
    CONF_EM_ZONE2_SENSORS,
    CONF_EM_DRYING_SENSORS,
    CONF_EM_GLOBAL_SENSORS,
    CONF_HARVEST_VALUE_PER_OZ,
    CONF_WATER_BASELINE_EC,
    TARIFF_OPTIONS,
    TARIFF_ANYTIME,
    TARIFF_DUAL,
    DEFAULT_TARIFF_MODE,
    DEFAULT_TARIFF_ANYTIME,
    DEFAULT_TARIFF_PEAK,
    DEFAULT_TARIFF_SHOULDER,
    DEFAULT_TARIFF_OFFPEAK,
    DEFAULT_TARIFF_PEAK_START,
    DEFAULT_TARIFF_PEAK_END,
    DEFAULT_TARIFF_SHOULDER_START,
    DEFAULT_TARIFF_SHOULDER_END,
    DEFAULT_HARVEST_VALUE,
    DEFAULT_WATER_BASELINE_EC,
)

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Selector helpers
# ─────────────────────────────────────────────────────────────────────────────

def _select_sel(options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _topology_sel() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {
                    "value": TOPOLOGY_COORDINATED,
                    "label": "Coordinated — Primary Grow Space + Conditioning Room",
                },
                {
                    "value": TOPOLOGY_STANDALONE,
                    "label": "Standalone — Primary Grow Space Only",
                },
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _temp_sensor_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
    )


def _humidity_sensor_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
    )


def _appliance_sel() -> selector.EntitySelector:
    """Switch or climate entity — heaters, ACs, humidifiers, dehumidifiers."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["switch", "climate"])
    )


def _ac_sel() -> selector.EntitySelector:
    """AC / Cooler — includes climate entities and relay-switched units."""
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["climate", "switch"])
    )


def _fan_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["fan", "switch"])
    )


def _light_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain=["light", "switch"])
    )


def _par_sensor_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor")
    )


def _weather_sel() -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="weather")
    )


def _text_sel() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )


def _bool_sel() -> selector.BooleanSelector:
    return selector.BooleanSelector()


def _number_slider(
    min_val: float,
    max_val: float,
    step: float = 1.0,
    unit: str = "",
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_val,
            max=max_val,
            step=step,
            mode=selector.NumberSelectorMode.SLIDER,
            unit_of_measurement=unit,
        )
    )


def _number_box(
    min_val: float,
    max_val: float,
    step: float = 0.001,
    unit: str = "",
) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=min_val,
            max=max_val,
            step=step,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# vol.Optional entity helper
# Using description={"suggested_value": val} prevents voluptuous from injecting
# None into the EntitySelector validator when a field is left blank.
# ─────────────────────────────────────────────────────────────────────────────

def _opt_entity(key: str, val: Optional[str]) -> vol.Optional:
    """Return vol.Optional with UI pre-population when val is truthy."""
    if val:
        return vol.Optional(key, description={"suggested_value": val})
    return vol.Optional(key)


def _collect_entity_keys(
    user_input: dict[str, Any],
    keys: tuple[str, ...],
) -> dict[str, Optional[str]]:
    """Normalise every entity key to None when absent from user_input."""
    return {k: (user_input.get(k) or None) for k in keys}


# ─────────────────────────────────────────────────────────────────────────────
# Per-step entity key sets
# ─────────────────────────────────────────────────────────────────────────────

_PRIMARY_SENSOR_KEYS: tuple[str, ...] = (
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_PRIMARY_HUMIDITY_SENSOR,
)

_ZONE1_ENTITY_KEYS: tuple[str, ...] = (
    CONF_LUNG_TEMP_SENSOR,
    CONF_LUNG_HUMIDITY_SENSOR,
    CONF_ZONE1_AC,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_BACKUP_HEATER,
    CONF_ZONE1_REVERSE_CYCLE,
    CONF_ZONE1_HUMIDIFIER,
    CONF_ZONE1_DEHUMIDIFIER,
)

_ZONE2_ENTITY_KEYS: tuple[str, ...] = (
    CONF_ZONE2_AC,
    CONF_ZONE2_HEATER,
    CONF_ZONE2_REVERSE_CYCLE,
    CONF_ZONE2_HUMIDIFIER,
    CONF_ZONE2_DEHUMIDIFIER,
    CONF_OUTDOOR_WEATHER_ENTITY,
    CONF_UPPER_CANOPY_TEMP_SENSOR,
    CONF_UPPER_CANOPY_HUMIDITY_SENSOR,
    CONF_MID_CANOPY_TEMP_SENSOR,
    CONF_MID_CANOPY_HUMIDITY_SENSOR,
    CONF_LOWER_CANOPY_TEMP_SENSOR,
    CONF_LOWER_CANOPY_HUMIDITY_SENSOR,
    CONF_EXHAUST_FAN,
)

_DRYING_ENTITY_KEYS: tuple[str, ...] = (
    CONF_DRYING_TEMP_SENSOR,
    CONF_DRYING_HUMIDITY_SENSOR,
    CONF_DRYING_EXHAUST_FAN,
    CONF_DRYING_CIRCULATION_FAN,
    CONF_DRYING_DEHUMIDIFIER,
    CONF_DRYING_AC,
    CONF_DRYING_HEATER,
    CONF_DRYING_LIGHT,
)

_LIGHTING_ENTITY_KEYS: tuple[str, ...] = (
    CONF_GROW_LIGHT,
    CONF_DLI_SENSOR,
    CONF_GROW_CAMERA,
)

_FAN_SLOT_KEYS: tuple[str, ...] = (
    "upper_fan_1", "upper_fan_2", "upper_fan_3", "upper_fan_4",
    "mid_fan_1",   "mid_fan_2",   "mid_fan_3",   "mid_fan_4",
    "lower_fan_1", "lower_fan_2", "lower_fan_3", "lower_fan_4",
)


# ─────────────────────────────────────────────────────────────────────────────
# Fan slot expansion / collapse
# ─────────────────────────────────────────────────────────────────────────────

def _expand_fan_slots(current: dict[str, Any], tier: str, conf_key: str) -> dict[str, Any]:
    stored: list[Optional[str]] = current.get(conf_key) or []
    result: dict[str, Any] = {}
    for i in range(1, 5):
        result[f"{tier}_fan_{i}"] = (stored[i - 1] if i - 1 < len(stored) else None) or None
    return result


def _collapse_fan_slots(data: dict[str, Any], tier: str) -> list[Optional[str]]:
    slots: list[Optional[str]] = []
    for i in range(1, 5):
        val = data.pop(f"{tier}_fan_{i}", None) or None
        slots.append(val)
    return slots


# ─────────────────────────────────────────────────────────────────────────────
# Options Flow
# ─────────────────────────────────────────────────────────────────────────────

class HelixOptionsFlow(config_entries.OptionsFlow):
    """Full options flow — hardware mapping, zone management, safety, energy, stages.

    Uses safe dict lookups throughout:
        entry.options.get(KEY, entry.data.get(KEY, DEFAULT))
    so that integration updates on disk never wipe previously saved configs.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        # Merge data + options so options always take precedence over original data
        self._current: dict[str, Any] = {
            **config_entry.data,
            **config_entry.options,
        }
        self._pending: dict[str, Any] = {}

    def _c(self, key: str, default: Any = None) -> Any:
        """Safe merged config lookup: options → data → default."""
        return self._entry.options.get(
            key, self._entry.data.get(key, self._current.get(key, default))
        )

    # ── Step 0: Entry point → zone management ─────────────────────────────────

    async def async_step_init(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        return await self.async_step_zone_management(user_input)

    # ── Step 1: Zone management ───────────────────────────────────────────────

    async def async_step_zone_management(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Rename zones, toggle module enables, set operating mode.

        The enable_conditioning_room and enable_drying_environment flags are the
        canonical source of truth for tab visibility in the frontend and for
        which control loops the climate engine executes. They default from
        the topology choice made during initial setup but can be changed freely
        in the options flow without altering the topology selector.
        """
        if user_input is not None:
            self._pending.update(user_input)
            # Keep topology in sync with enable_conditioning_room for legacy compat
            if CONF_ENABLE_CONDITIONING_ROOM in user_input:
                conditioning_on = bool(user_input[CONF_ENABLE_CONDITIONING_ROOM])
                self._pending.setdefault(
                    CONF_TOPOLOGY,
                    TOPOLOGY_COORDINATED if conditioning_on else TOPOLOGY_STANDALONE,
                )
            # Sync drying_enabled legacy flag
            if CONF_ENABLE_DRYING_ENVIRONMENT in user_input:
                self._pending[CONF_DRYING_ENABLED] = bool(
                    user_input[CONF_ENABLE_DRYING_ENVIRONMENT]
                )
            return await self.async_step_primary_sensors()

        topology = self._c(CONF_TOPOLOGY, TOPOLOGY_COORDINATED)
        # Derive current module flag states (options override data override topology)
        conditioning_on = bool(
            self._c(
                CONF_ENABLE_CONDITIONING_ROOM,
                topology == TOPOLOGY_COORDINATED,
            )
        )
        drying_on = bool(
            self._c(
                CONF_ENABLE_DRYING_ENVIRONMENT,
                self._c(CONF_DRYING_ENABLED, False),
            )
        )

        schema_dict: dict[Any, Any] = {
            vol.Required(
                CONF_TOPOLOGY,
                default=topology,
            ): _topology_sel(),
            # ── Zone display names ─────────────────────────────────────────────
            vol.Optional(
                CONF_ZONE1_NAME,
                default=self._c(CONF_ZONE1_NAME, DEFAULT_ZONE1_NAME),
            ): _text_sel(),
            vol.Optional(
                CONF_ZONE2_NAME,
                default=self._c(CONF_ZONE2_NAME, DEFAULT_ZONE2_NAME),
            ): _text_sel(),
            # ── Module Registry ────────────────────────────────────────────────
            vol.Optional(
                CONF_ENABLE_CONDITIONING_ROOM,
                default=conditioning_on,
            ): _bool_sel(),
            vol.Optional(
                CONF_ENABLE_DRYING_ENVIRONMENT,
                default=drying_on,
            ): _bool_sel(),
            vol.Optional(
                CONF_DRYING_ZONE_NAME,
                default=self._c(CONF_DRYING_ZONE_NAME, DEFAULT_DRYING_ZONE_NAME),
            ): _text_sel(),
        }

        return self.async_show_form(
            step_id="zone_management",
            data_schema=vol.Schema(schema_dict),
            errors={},
            description_placeholders={
                "tip": (
                    "Enable Conditioning Room activates Zone 1 climate control and the "
                    "Conditioning Room tab in the dashboard. "
                    "Enable Drying Environment activates the 60/60 cure profile tab. "
                    "Zone names that match Home Assistant Areas group entities automatically."
                ),
            },
        )

    # ── Step 2: Primary sensors (required) ────────────────────────────────────

    async def async_step_primary_sensors(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Required primary canopy temperature + humidity sensors for Zone 1."""
        errors: dict[str, str] = {}

        if user_input is not None:
            temp_id = user_input.get(CONF_PRIMARY_TEMP_SENSOR, "")
            hum_id = user_input.get(CONF_PRIMARY_HUMIDITY_SENSOR, "")

            if temp_id:
                state = self.hass.states.get(temp_id)
                if state is None:
                    errors[CONF_PRIMARY_TEMP_SENSOR] = "entity_not_found"
            else:
                errors[CONF_PRIMARY_TEMP_SENSOR] = "entity_required"

            if hum_id:
                state = self.hass.states.get(hum_id)
                if state is None:
                    errors[CONF_PRIMARY_HUMIDITY_SENSOR] = "entity_not_found"
            else:
                errors[CONF_PRIMARY_HUMIDITY_SENSOR] = "entity_required"

            if not errors:
                self._pending.update(user_input)
                return await self.async_step_zone2_devices()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRIMARY_TEMP_SENSOR,
                    default=self._c(CONF_PRIMARY_TEMP_SENSOR, ""),
                ): _temp_sensor_sel(),
                vol.Required(
                    CONF_PRIMARY_HUMIDITY_SENSOR,
                    default=self._c(CONF_PRIMARY_HUMIDITY_SENSOR, ""),
                ): _humidity_sensor_sel(),
            }
        )

        return self.async_show_form(
            step_id="primary_sensors",
            data_schema=schema,
            errors=errors,
        )

    # ── Step 3: Zone 2 — Primary Grow Space hardware (always active) ─────────

    async def async_step_zone2_devices(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Zone 2 (Primary Grow Space) hardware mapping — canopy sensors, exhaust, HVAC.

        HVAC model: one AC/Cooler selector + is_reverse_cycle checkbox + one Heater selector.
        When is_reverse_cycle=True:
          - The AC entity is the unified heat pump → driven via climate.set_hvac_mode
          - The Heater entity becomes a secondary / backup heating stage
        When is_reverse_cycle=False:
          - AC entity is a discrete cooler (switch/relay)
          - Heater entity is a discrete heater (switch/relay)
        """
        if user_input is not None:
            # Collect all entity keys
            self._pending.update(_collect_entity_keys(user_input, _ZONE2_ENTITY_KEYS))
            # Boolean and number fields pass through directly
            self._pending[CONF_ZONE2_IS_REVERSE_CYCLE] = bool(
                user_input.get(CONF_ZONE2_IS_REVERSE_CYCLE, False)
            )
            conditioning_on = self._pending.get(
                CONF_ENABLE_CONDITIONING_ROOM,
                self._c(
                    CONF_ENABLE_CONDITIONING_ROOM,
                    self._c(CONF_TOPOLOGY, TOPOLOGY_COORDINATED) == TOPOLOGY_COORDINATED,
                ),
            )
            if conditioning_on:
                return await self.async_step_zone1_devices()
            return await self._next_after_zone1()

        c = self._c
        is_rc = bool(c(CONF_ZONE2_IS_REVERSE_CYCLE, False))

        schema = vol.Schema(
            {
                # ── Additional canopy sensor pairs (optional) ─────────────────
                _opt_entity(CONF_UPPER_CANOPY_TEMP_SENSOR, c(CONF_UPPER_CANOPY_TEMP_SENSOR)):
                    _temp_sensor_sel(),
                _opt_entity(CONF_UPPER_CANOPY_HUMIDITY_SENSOR, c(CONF_UPPER_CANOPY_HUMIDITY_SENSOR)):
                    _humidity_sensor_sel(),
                _opt_entity(CONF_MID_CANOPY_TEMP_SENSOR, c(CONF_MID_CANOPY_TEMP_SENSOR)):
                    _temp_sensor_sel(),
                _opt_entity(CONF_MID_CANOPY_HUMIDITY_SENSOR, c(CONF_MID_CANOPY_HUMIDITY_SENSOR)):
                    _humidity_sensor_sel(),
                _opt_entity(CONF_LOWER_CANOPY_TEMP_SENSOR, c(CONF_LOWER_CANOPY_TEMP_SENSOR)):
                    _temp_sensor_sel(),
                _opt_entity(CONF_LOWER_CANOPY_HUMIDITY_SENSOR, c(CONF_LOWER_CANOPY_HUMIDITY_SENSOR)):
                    _humidity_sensor_sel(),
                # ── Exhaust fan ───────────────────────────────────────────────
                _opt_entity(CONF_EXHAUST_FAN, c(CONF_EXHAUST_FAN)):
                    _fan_sel(),
                # ── Air Conditioner / Cooler ──────────────────────────────────
                _opt_entity(CONF_ZONE2_AC, c(CONF_ZONE2_AC)):
                    _ac_sel(),
                # ── Reverse-cycle toggle ──────────────────────────────────────
                vol.Optional(
                    CONF_ZONE2_IS_REVERSE_CYCLE,
                    default=is_rc,
                ): _bool_sel(),
                # ── Heater (backup when RC, discrete when not RC) ─────────────
                _opt_entity(CONF_ZONE2_HEATER, c(CONF_ZONE2_HEATER)):
                    _appliance_sel(),
                # ── Humidifier / dehumidifier ─────────────────────────────────
                _opt_entity(CONF_ZONE2_HUMIDIFIER, c(CONF_ZONE2_HUMIDIFIER)):
                    _appliance_sel(),
                _opt_entity(CONF_ZONE2_DEHUMIDIFIER, c(CONF_ZONE2_DEHUMIDIFIER)):
                    _appliance_sel(),
                # ── Outdoor weather entity (for feedforward MPC) ──────────────
                _opt_entity(CONF_OUTDOOR_WEATHER_ENTITY, c(CONF_OUTDOOR_WEATHER_ENTITY)):
                    _weather_sel(),
            }
        )

        return self.async_show_form(
            step_id="zone2_devices",
            data_schema=schema,
            errors={},
            description_placeholders={
                "reverse_cycle_tip": (
                    "Check 'This unit is a Reverse-Cycle Heat Pump / Dual-Temp AC' "
                    "if your Air Conditioner can also heat. The Heater field becomes "
                    "a backup / staging heater when this is enabled."
                ),
            },
        )

    # ── Step 4: Zone 1 — Conditioning Room hardware (conditional) ────────────

    async def async_step_zone1_devices(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Zone 1 (Conditioning Room) sensors and hardware.

        Skipped automatically when enable_conditioning_room is False.
        HVAC model mirrors Zone 2: AC + is_reverse_cycle checkbox + heater.
        Includes an optional backup heater staged on low outdoor temperature.
        """
        # Use the enable flag as the canonical gate, fall back to topology for compat
        conditioning_on = self._pending.get(
            CONF_ENABLE_CONDITIONING_ROOM,
            self._c(
                CONF_ENABLE_CONDITIONING_ROOM,
                self._c(CONF_TOPOLOGY, TOPOLOGY_COORDINATED) == TOPOLOGY_COORDINATED,
            ),
        )

        if not conditioning_on:
            # Skip straight to drying / fan matrix
            return await self._next_after_zone1()

        if user_input is not None:
            self._pending.update(_collect_entity_keys(user_input, _ZONE1_ENTITY_KEYS))
            self._pending[CONF_ZONE1_IS_REVERSE_CYCLE] = bool(
                user_input.get(CONF_ZONE1_IS_REVERSE_CYCLE, False)
            )
            threshold = user_input.get(CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C)
            if threshold is not None:
                self._pending[CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C] = float(threshold)
            return await self._next_after_zone1()

        c = self._c
        schema = vol.Schema(
            {
                # ── Lung Room sensor pair ─────────────────────────────────────
                _opt_entity(CONF_LUNG_TEMP_SENSOR, c(CONF_LUNG_TEMP_SENSOR)):
                    _temp_sensor_sel(),
                _opt_entity(CONF_LUNG_HUMIDITY_SENSOR, c(CONF_LUNG_HUMIDITY_SENSOR)):
                    _humidity_sensor_sel(),
                # ── Air Conditioner / Cooler ──────────────────────────────────
                _opt_entity(CONF_ZONE1_AC, c(CONF_ZONE1_AC)):
                    _ac_sel(),
                # ── Reverse-cycle toggle ──────────────────────────────────────
                vol.Optional(
                    CONF_ZONE1_IS_REVERSE_CYCLE,
                    default=bool(c(CONF_ZONE1_IS_REVERSE_CYCLE, False)),
                ): _bool_sel(),
                # ── Heater (backup when RC, discrete when not RC) ─────────────
                _opt_entity(CONF_ZONE1_HEATER, c(CONF_ZONE1_HEATER)):
                    _appliance_sel(),
                # ── Backup heater threshold (always shown, only active when RC) ─
                vol.Optional(
                    CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C,
                    default=c(CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C, DEFAULT_BACKUP_HEATER_THRESHOLD_C),
                ): _number_slider(-10.0, 15.0, 0.5, "°C"),
                # ── Humidifier / dehumidifier ─────────────────────────────────
                _opt_entity(CONF_ZONE1_HUMIDIFIER, c(CONF_ZONE1_HUMIDIFIER)):
                    _appliance_sel(),
                _opt_entity(CONF_ZONE1_DEHUMIDIFIER, c(CONF_ZONE1_DEHUMIDIFIER)):
                    _appliance_sel(),
            }
        )

        return self.async_show_form(
            step_id="zone1_devices",
            data_schema=schema,
            errors={},
        )

    async def _next_after_zone1(self) -> config_entries.ConfigFlowResult:
        """Route to drying zone or fan matrix depending on enable_drying_environment flag."""
        drying_enabled = self._pending.get(
            CONF_ENABLE_DRYING_ENVIRONMENT,
            self._c(
                CONF_ENABLE_DRYING_ENVIRONMENT,
                self._c(CONF_DRYING_ENABLED, False),
            ),
        )
        if drying_enabled:
            return await self.async_step_drying_zone()
        return await self.async_step_fan_matrix()

    # ── Step 5: Drying Zone hardware (conditional) ────────────────────────────

    async def async_step_drying_zone(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Dedicated Drying Room hardware mapping.

        Sensors (temp + humidity) are required for the drying control loop.
        All appliance fields are optional.
        HVAC follows same AC + is_reverse_cycle + heater model.
        The drying climate engine targets a fixed 15.5°C / 60% RH profile.
        """
        if user_input is not None:
            self._pending.update(_collect_entity_keys(user_input, _DRYING_ENTITY_KEYS))
            self._pending[CONF_DRYING_IS_REVERSE_CYCLE] = bool(
                user_input.get(CONF_DRYING_IS_REVERSE_CYCLE, False)
            )
            return await self.async_step_fan_matrix()

        c = self._c
        schema = vol.Schema(
            {
                # ── Required sensors ──────────────────────────────────────────
                _opt_entity(CONF_DRYING_TEMP_SENSOR, c(CONF_DRYING_TEMP_SENSOR)):
                    _temp_sensor_sel(),
                _opt_entity(CONF_DRYING_HUMIDITY_SENSOR, c(CONF_DRYING_HUMIDITY_SENSOR)):
                    _humidity_sensor_sel(),
                # ── Airflow ───────────────────────────────────────────────────
                _opt_entity(CONF_DRYING_EXHAUST_FAN, c(CONF_DRYING_EXHAUST_FAN)):
                    _fan_sel(),
                _opt_entity(CONF_DRYING_CIRCULATION_FAN, c(CONF_DRYING_CIRCULATION_FAN)):
                    _fan_sel(),
                # ── Moisture control ──────────────────────────────────────────
                _opt_entity(CONF_DRYING_DEHUMIDIFIER, c(CONF_DRYING_DEHUMIDIFIER)):
                    _appliance_sel(),
                # ── AC / Cooler ───────────────────────────────────────────────
                _opt_entity(CONF_DRYING_AC, c(CONF_DRYING_AC)):
                    _ac_sel(),
                # ── Reverse-cycle toggle ──────────────────────────────────────
                vol.Optional(
                    CONF_DRYING_IS_REVERSE_CYCLE,
                    default=bool(c(CONF_DRYING_IS_REVERSE_CYCLE, False)),
                ): _bool_sel(),
                # ── Heater ────────────────────────────────────────────────────
                _opt_entity(CONF_DRYING_HEATER, c(CONF_DRYING_HEATER)):
                    _appliance_sel(),
                # ── Optional inspection light ─────────────────────────────────
                _opt_entity(CONF_DRYING_LIGHT, c(CONF_DRYING_LIGHT)):
                    _light_sel(),
            }
        )

        return self.async_show_form(
            step_id="drying_zone",
            data_schema=schema,
            errors={},
            description_placeholders={
                "drying_tip": (
                    "The Drying Zone runs a fixed 15.5°C / 60% RH profile "
                    "(60/60 cure). Hardware controls are governed by this target only."
                ),
            },
        )

    # ── Step 6: Fan matrix ────────────────────────────────────────────────────

    async def async_step_fan_matrix(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Circulation fan tier assignment and breeze settings."""
        if user_input is not None:
            data = dict(user_input)
            for slot_key in _FAN_SLOT_KEYS:
                data.setdefault(slot_key, None)
            self._pending[CONF_UPPER_FANS] = _collapse_fan_slots(data, "upper")
            self._pending[CONF_MID_FANS] = _collapse_fan_slots(data, "mid")
            self._pending[CONF_LOWER_FANS] = _collapse_fan_slots(data, "lower")
            self._pending.update(data)
            return await self.async_step_lighting()

        slot_defaults: dict[str, Any] = {}
        slot_defaults.update(_expand_fan_slots(self._current, "upper", CONF_UPPER_FANS))
        slot_defaults.update(_expand_fan_slots(self._current, "mid", CONF_MID_FANS))
        slot_defaults.update(_expand_fan_slots(self._current, "lower", CONF_LOWER_FANS))

        c = self._c
        schema = vol.Schema(
            {
                # Upper tier
                _opt_entity("upper_fan_1", slot_defaults.get("upper_fan_1")): _fan_sel(),
                _opt_entity("upper_fan_2", slot_defaults.get("upper_fan_2")): _fan_sel(),
                _opt_entity("upper_fan_3", slot_defaults.get("upper_fan_3")): _fan_sel(),
                _opt_entity("upper_fan_4", slot_defaults.get("upper_fan_4")): _fan_sel(),
                # Mid tier
                _opt_entity("mid_fan_1", slot_defaults.get("mid_fan_1")): _fan_sel(),
                _opt_entity("mid_fan_2", slot_defaults.get("mid_fan_2")): _fan_sel(),
                _opt_entity("mid_fan_3", slot_defaults.get("mid_fan_3")): _fan_sel(),
                _opt_entity("mid_fan_4", slot_defaults.get("mid_fan_4")): _fan_sel(),
                # Lower tier
                _opt_entity("lower_fan_1", slot_defaults.get("lower_fan_1")): _fan_sel(),
                _opt_entity("lower_fan_2", slot_defaults.get("lower_fan_2")): _fan_sel(),
                _opt_entity("lower_fan_3", slot_defaults.get("lower_fan_3")): _fan_sel(),
                _opt_entity("lower_fan_4", slot_defaults.get("lower_fan_4")): _fan_sel(),
                # Control mode + breeze
                vol.Optional(
                    CONF_FAN_CONTROL_MODE,
                    default=c(CONF_FAN_CONTROL_MODE, FAN_CONTROL_CONTINUOUS),
                ): _select_sel(FAN_CONTROL_OPTIONS),
                vol.Optional(
                    CONF_BREEZE_ENABLED,
                    default=bool(c(CONF_BREEZE_ENABLED, False)),
                ): _bool_sel(),
                vol.Optional(
                    CONF_BREEZE_VARIANCE,
                    default=c(CONF_BREEZE_VARIANCE, 20),
                ): _number_slider(0, 50, 1, "%"),
            }
        )

        return self.async_show_form(step_id="fan_matrix", data_schema=schema, errors={})

    # ── Step 7: Lighting ──────────────────────────────────────────────────────

    async def async_step_lighting(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Grow light configuration."""
        if user_input is not None:
            entity_data = _collect_entity_keys(user_input, _LIGHTING_ENTITY_KEYS)
            non_entity_data = {k: v for k, v in user_input.items() if k not in _LIGHTING_ENTITY_KEYS}
            self._pending.update(entity_data)
            self._pending.update(non_entity_data)
            return await self.async_step_safety_params()

        c = self._c
        schema = vol.Schema(
            {
                _opt_entity(CONF_GROW_LIGHT, c(CONF_GROW_LIGHT)):
                    _light_sel(),
                vol.Optional(
                    CONF_LIGHT_TYPE,
                    default=c(CONF_LIGHT_TYPE, LIGHT_LED),
                ): _select_sel(LIGHT_TYPE_OPTIONS),
                vol.Optional(
                    CONF_LIGHT_DIMMABLE,
                    default=bool(c(CONF_LIGHT_DIMMABLE, False)),
                ): _bool_sel(),
                vol.Optional(
                    CONF_SUNRISE_RAMP_MIN,
                    default=c(CONF_SUNRISE_RAMP_MIN, DEFAULT_SUNRISE_RAMP_MIN),
                ): _number_slider(15, 30, 1, "min"),
                _opt_entity(CONF_DLI_SENSOR, c(CONF_DLI_SENSOR)):
                    _par_sensor_sel(),
                _opt_entity(CONF_GROW_CAMERA, c(CONF_GROW_CAMERA)):
                    selector.EntitySelector(selector.EntitySelectorConfig(domain="camera")),
            }
        )

        return self.async_show_form(step_id="lighting", data_schema=schema, errors={})

    # ── Step 8: Safety parameters ─────────────────────────────────────────────

    async def async_step_safety_params(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Control algorithm, safety cutoffs, anti-short-cycle, leaf temp offset, sensor dropout."""
        if user_input is not None:
            self._pending.update(user_input)
            return await self.async_step_energy()

        c = self._c
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_CONTROL_ALGORITHM,
                    default=c(CONF_CONTROL_ALGORITHM, ALGO_BANG_BANG),
                ): _select_sel(ALGO_OPTIONS),
                vol.Optional(
                    CONF_HEATER_CUTOFF_C,
                    default=c(CONF_HEATER_CUTOFF_C, DEFAULT_HEATER_CUTOFF_C),
                ): _number_slider(22.0, 30.0, 0.5, "°C"),
                vol.Optional(
                    CONF_THERMAL_RUNAWAY_C,
                    default=c(CONF_THERMAL_RUNAWAY_C, DEFAULT_THERMAL_RUNAWAY_C),
                ): _number_slider(28.0, 36.0, 0.5, "°C"),
                vol.Optional(
                    CONF_ANTI_SHORT_CYCLE_MIN,
                    default=c(CONF_ANTI_SHORT_CYCLE_MIN, DEFAULT_ANTI_SHORT_CYCLE_MIN),
                ): _number_slider(3, 10, 1, "min"),
                vol.Optional(
                    CONF_LEAF_TEMP_OFFSET_C,
                    default=c(CONF_LEAF_TEMP_OFFSET_C, DEFAULT_LEAF_TEMP_OFFSET_C),
                ): _number_slider(-5.0, 0.0, 0.5, "°C"),
                vol.Optional(
                    CONF_EXHAUST_MIN_PCT,
                    default=c(CONF_EXHAUST_MIN_PCT, DEFAULT_EXHAUST_MIN_PCT),
                ): _number_slider(0, 30, 1, "%"),
                # ── Safety interlock ceilings ──────────────────────────────────
                vol.Optional(
                    CONF_SAFETY_HIGH_TEMP_C,
                    default=c(CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C),
                ): _number_slider(28.0, 40.0, 0.5, "°C"),
                vol.Optional(
                    CONF_SAFETY_LOW_TEMP_C,
                    default=c(CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C),
                ): _number_slider(5.0, 20.0, 0.5, "°C"),
                vol.Optional(
                    CONF_SAFETY_HIGH_RH_PCT,
                    default=c(CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT),
                ): _number_slider(60.0, 95.0, 1.0, "%"),
                vol.Optional(
                    CONF_SAFETY_LOW_RH_PCT,
                    default=c(CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT),
                ): _number_slider(15.0, 50.0, 1.0, "%"),
                # ── Sensor dropout failsafe ────────────────────────────────────
                vol.Optional(
                    CONF_SENSOR_DROPOUT_MIN,
                    default=c(CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG),
                ): _number_slider(5, 120, 1, "min"),
                # ── Mobile push notification target ────────────────────────────
                vol.Optional(
                    CONF_NOTIFY_TARGET,
                    default=c(CONF_NOTIFY_TARGET, ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="notify", multiple=False)
                ),
            }
        )

        return self.async_show_form(step_id="safety_params", data_schema=schema, errors={})

    # ── Step 9: Energy & Financial Engine ────────────────────────────────────

    async def async_step_energy(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Tariff configuration, energy monitoring sensor slots, ROI settings."""
        if user_input is not None:
            self._pending.update(user_input)
            # Collapse EM slot keys → lists for coordinator / frontend consumption
            for zone, slot_keys in (
                (CONF_EM_ZONE1_SENSORS, [CONF_EM_ZONE1_S1, CONF_EM_ZONE1_S2, CONF_EM_ZONE1_S3, CONF_EM_ZONE1_S4]),
                (CONF_EM_ZONE2_SENSORS, [CONF_EM_ZONE2_S1, CONF_EM_ZONE2_S2, CONF_EM_ZONE2_S3, CONF_EM_ZONE2_S4]),
                (CONF_EM_DRYING_SENSORS, [CONF_EM_DRYING_S1, CONF_EM_DRYING_S2, CONF_EM_DRYING_S3, CONF_EM_DRYING_S4]),
                (CONF_EM_GLOBAL_SENSORS, [CONF_EM_GLOBAL_S1, CONF_EM_GLOBAL_S2, CONF_EM_GLOBAL_S3, CONF_EM_GLOBAL_S4]),
            ):
                self._pending[zone] = [
                    self._pending.get(k) or None for k in slot_keys
                ]
            return await self.async_step_stage_setup()

        c = self._c

        # Expand saved list → individual slot keys for schema display
        def _em_expand(list_key: str, slot_keys: list[str]) -> dict[Any, Any]:
            saved: list[Optional[str]] = c(list_key, []) or []
            out: dict[Any, Any] = {}
            for i, sk in enumerate(slot_keys):
                out[vol.Optional(sk, default=c(sk, saved[i] if i < len(saved) else None))] = (
                    _appliance_sel()
                )
            return out

        em_z1 = _em_expand(CONF_EM_ZONE1_SENSORS, [CONF_EM_ZONE1_S1, CONF_EM_ZONE1_S2, CONF_EM_ZONE1_S3, CONF_EM_ZONE1_S4])
        em_z2 = _em_expand(CONF_EM_ZONE2_SENSORS, [CONF_EM_ZONE2_S1, CONF_EM_ZONE2_S2, CONF_EM_ZONE2_S3, CONF_EM_ZONE2_S4])
        em_dry = _em_expand(CONF_EM_DRYING_SENSORS, [CONF_EM_DRYING_S1, CONF_EM_DRYING_S2, CONF_EM_DRYING_S3, CONF_EM_DRYING_S4])
        em_glob = _em_expand(CONF_EM_GLOBAL_SENSORS, [CONF_EM_GLOBAL_S1, CONF_EM_GLOBAL_S2, CONF_EM_GLOBAL_S3, CONF_EM_GLOBAL_S4])

        schema_dict: dict[Any, Any] = {
            # ── Legacy flat rate (kept for backward-compat) ───────────────────
            vol.Optional(
                CONF_ELECTRICITY_RATE,
                default=c(CONF_ELECTRICITY_RATE, DEFAULT_TARIFF_ANYTIME),
            ): _number_box(0.0, 5.0, 0.001, "$/kWh"),
            # ── Tariff mode ───────────────────────────────────────────────────
            vol.Optional(
                CONF_TARIFF_MODE,
                default=c(CONF_TARIFF_MODE, DEFAULT_TARIFF_MODE),
            ): _select_sel(TARIFF_OPTIONS),
            # ── Always-rate ───────────────────────────────────────────────────
            vol.Optional(
                CONF_TARIFF_ANYTIME,
                default=c(CONF_TARIFF_ANYTIME, DEFAULT_TARIFF_ANYTIME),
            ): _number_box(0.01, 2.0, 0.001, "$/kWh"),
            # ── Peak / shoulder / off-peak rates ─────────────────────────────
            vol.Optional(
                CONF_TARIFF_PEAK,
                default=c(CONF_TARIFF_PEAK, DEFAULT_TARIFF_PEAK),
            ): _number_box(0.01, 2.0, 0.001, "$/kWh"),
            vol.Optional(
                CONF_TARIFF_SHOULDER,
                default=c(CONF_TARIFF_SHOULDER, DEFAULT_TARIFF_SHOULDER),
            ): _number_box(0.01, 2.0, 0.001, "$/kWh"),
            vol.Optional(
                CONF_TARIFF_OFFPEAK,
                default=c(CONF_TARIFF_OFFPEAK, DEFAULT_TARIFF_OFFPEAK),
            ): _number_box(0.01, 2.0, 0.001, "$/kWh"),
            # ── Time window boundaries (HH:MM strings) ───────────────────────
            vol.Optional(
                CONF_TARIFF_PEAK_START,
                default=c(CONF_TARIFF_PEAK_START, DEFAULT_TARIFF_PEAK_START),
            ): _text_sel(),
            vol.Optional(
                CONF_TARIFF_PEAK_END,
                default=c(CONF_TARIFF_PEAK_END, DEFAULT_TARIFF_PEAK_END),
            ): _text_sel(),
            vol.Optional(
                CONF_TARIFF_SHOULDER_START,
                default=c(CONF_TARIFF_SHOULDER_START, DEFAULT_TARIFF_SHOULDER_START),
            ): _text_sel(),
            vol.Optional(
                CONF_TARIFF_SHOULDER_END,
                default=c(CONF_TARIFF_SHOULDER_END, DEFAULT_TARIFF_SHOULDER_END),
            ): _text_sel(),
            # ── Harvest value & water baseline ────────────────────────────────
            vol.Optional(
                CONF_HARVEST_VALUE_PER_OZ,
                default=c(CONF_HARVEST_VALUE_PER_OZ, DEFAULT_HARVEST_VALUE),
            ): _number_slider(10, 2000, 10, "$/oz"),
            vol.Optional(
                CONF_WATER_BASELINE_EC,
                default=c(CONF_WATER_BASELINE_EC, DEFAULT_WATER_BASELINE_EC),
            ): _number_slider(0.0, 2.0, 0.01, "mS/cm"),
        }
        # Merge EM sensor slots
        schema_dict.update(em_z1)
        schema_dict.update(em_z2)
        schema_dict.update(em_dry)
        schema_dict.update(em_glob)

        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(schema_dict),
            errors={},
            description_placeholders={
                "tip": (
                    "Map up to 4 energy monitoring sensors per zone for live cycle cost "
                    "calculation. Tariff windows use HH:MM 24-hour format. "
                    "Midnight-crossing windows (e.g. 22:00–06:00) are not yet supported."
                ),
            },
        )

    # ── Step 10: Stage setup ──────────────────────────────────────────────────

    async def async_step_stage_setup(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Grow stage, progression mode, smooth glides, recipe file."""
        if user_input is not None:
            self._pending.update(user_input)
            merged: dict[str, Any] = {**self._current, **self._pending}
            return self.async_create_entry(title="", data=merged)

        c = self._c
        schema = vol.Schema(
            {
                vol.Optional(
                    "initial_stage",
                    default=c("initial_stage", STAGE_GERMINATION),
                ): _select_sel(STAGE_SEQUENCE),
                vol.Optional(
                    CONF_PROGRESSION_MODE,
                    default=c(CONF_PROGRESSION_MODE, PROG_MANUAL),
                ): _select_sel(PROG_OPTIONS),
                vol.Optional(
                    CONF_STAGE_START_DATE,
                    default=c(CONF_STAGE_START_DATE, None),
                ): selector.DateSelector(),
                vol.Optional(
                    CONF_SMOOTH_GLIDES,
                    default=bool(c(CONF_SMOOTH_GLIDES, True)),
                ): _bool_sel(),
                vol.Optional(
                    CONF_RECIPE_FILE,
                    default=c(CONF_RECIPE_FILE, ""),
                ): _text_sel(),
            }
        )

        return self.async_show_form(step_id="stage_setup", data_schema=schema, errors={})
