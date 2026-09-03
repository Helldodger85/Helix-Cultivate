"""Helix Cultivate — Number platform (17 number entities)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DEFAULT_ANTI_SHORT_CYCLE_MIN,
    DEFAULT_EXHAUST_MIN_PCT,
    DEFAULT_FAN_SPEED_PCT,
    DEFAULT_FAN_VARIANCE_PCT,
    DEFAULT_HEATER_CUTOFF_C,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DEFAULT_LIGHT_INTENSITY_PCT,
    DEFAULT_RH_SETPOINT_PCT,
    DEFAULT_SUNRISE_RAMP_MIN,
    DEFAULT_TEMP_SETPOINT_C,
    DEFAULT_THERMAL_RUNAWAY_C,
    DEFAULT_VPD_TARGET_KPA,
    DOMAIN,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    NUMBER_ANTI_SHORT_CYCLE,
    NUMBER_ELECTRICITY_RATE,
    NUMBER_EXHAUST_MIN_PCT,
    NUMBER_HEATER_CUTOFF,
    NUMBER_LEAF_TEMP_OFFSET,
    NUMBER_LIGHT_INTENSITY,
    NUMBER_LOWER_FAN_SPEED,
    NUMBER_LOWER_FAN_VARIANCE,
    NUMBER_MID_FAN_SPEED,
    NUMBER_MID_FAN_VARIANCE,
    NUMBER_RH_SETPOINT,
    NUMBER_SUNRISE_RAMP_MIN,
    NUMBER_TEMP_SETPOINT,
    NUMBER_THERMAL_RUNAWAY,
    NUMBER_UPPER_FAN_SPEED,
    NUMBER_UPPER_FAN_VARIANCE,
    NUMBER_VPD_TARGET,
)
from .coordinator import HelixCoordinator


@dataclass(frozen=True)
class HelixNumberDescription(NumberEntityDescription):
    """Extended number entity description."""

    # Getter: returns the current value from coordinator
    value_fn: Callable[["HelixCoordinator"], float] = field(default=lambda c: 0.0)
    # Setter: applies a new value to coordinator
    set_fn: Callable[["HelixCoordinator", float], None] = field(default=lambda c, v: None)


def _fan_speed_getter(tier: str) -> Callable[[HelixCoordinator], float]:
    return lambda c: c.get_fan_speed(tier)


def _fan_speed_setter(tier: str) -> Callable[[HelixCoordinator, float], None]:
    return lambda c, v: c.set_fan_speed(tier, v)


def _fan_variance_getter(tier: str) -> Callable[[HelixCoordinator], float]:
    return lambda c: float(c._config.get(f"breeze_variance_{tier}", DEFAULT_FAN_VARIANCE_PCT))


def _persistent_setter(
    config_key: str, coerce: Callable[[float], Any] = float
) -> Callable[[HelixCoordinator, float], None]:
    """Build a setter that mutates in-memory config AND persists to the config entry."""

    def _set(c: HelixCoordinator, v: float) -> None:
        coerced = coerce(v)
        c._config[config_key] = coerced
        c.queue_option_write(config_key, coerced)

    return _set


def _fan_variance_setter(tier: str) -> Callable[[HelixCoordinator, float], None]:
    return _persistent_setter(f"breeze_variance_{tier}", float)


NUMBER_DESCRIPTIONS: tuple[HelixNumberDescription, ...] = (
    # ── Environmental setpoints ──────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_VPD_TARGET,
        name="VPD Target",
        native_unit_of_measurement="kPa",
        native_min_value=0.4,
        native_max_value=1.8,
        native_step=0.05,
        mode=NumberMode.SLIDER,
        icon="mdi:water-percent",
        value_fn=lambda c: c.vpd_target,
        set_fn=lambda c, v: setattr(c, "vpd_target", v),
    ),
    HelixNumberDescription(
        key=NUMBER_TEMP_SETPOINT,
        name="Temperature Setpoint",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=15.0,
        native_max_value=35.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        value_fn=lambda c: c.temp_setpoint,
        set_fn=lambda c, v: setattr(c, "temp_setpoint", v),
    ),
    HelixNumberDescription(
        key=NUMBER_RH_SETPOINT,
        name="Humidity Setpoint",
        native_unit_of_measurement="%",
        device_class=NumberDeviceClass.HUMIDITY,
        native_min_value=30.0,
        native_max_value=90.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        value_fn=lambda c: c.rh_setpoint,
        set_fn=lambda c, v: setattr(c, "rh_setpoint", v),
    ),
    # ── Safety cutoffs ────────────────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_HEATER_CUTOFF,
        name="Heater Over-Temp Cutoff",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=22.0,
        native_max_value=30.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        icon="mdi:thermometer-alert",
        value_fn=lambda c: float(c._config.get("heater_cutoff_c", DEFAULT_HEATER_CUTOFF_C)),
        set_fn=_persistent_setter("heater_cutoff_c", float),
    ),
    HelixNumberDescription(
        key=NUMBER_THERMAL_RUNAWAY,
        name="Thermal Runaway Guard",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=28.0,
        native_max_value=36.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        icon="mdi:fire-alert",
        value_fn=lambda c: float(c._config.get("thermal_runaway_c", DEFAULT_THERMAL_RUNAWAY_C)),
        set_fn=_persistent_setter("thermal_runaway_c", float),
    ),
    HelixNumberDescription(
        key=NUMBER_ANTI_SHORT_CYCLE,
        name="Anti-Short-Cycle Dwell",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        native_min_value=3.0,
        native_max_value=10.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:timer-pause-outline",
        value_fn=lambda c: float(c._config.get("anti_short_cycle_min", DEFAULT_ANTI_SHORT_CYCLE_MIN)),
        set_fn=_persistent_setter("anti_short_cycle_min", int),
    ),
    HelixNumberDescription(
        key=NUMBER_EXHAUST_MIN_PCT,
        name="Exhaust Minimum Floor",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=30.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:fan-minus",
        value_fn=lambda c: float(c._config.get("exhaust_min_pct", DEFAULT_EXHAUST_MIN_PCT)),
        set_fn=_persistent_setter("exhaust_min_pct", int),
    ),
    HelixNumberDescription(
        key=NUMBER_LEAF_TEMP_OFFSET,
        name="Leaf Temp Offset",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=NumberDeviceClass.TEMPERATURE,
        native_min_value=-5.0,
        native_max_value=0.0,
        native_step=0.5,
        mode=NumberMode.SLIDER,
        icon="mdi:leaf-circle-outline",
        value_fn=lambda c: float(c._config.get("leaf_temp_offset_c", DEFAULT_LEAF_TEMP_OFFSET_C)),
        set_fn=_persistent_setter("leaf_temp_offset_c", float),
    ),
    # ── Fan speeds ────────────────────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_UPPER_FAN_SPEED,
        name="Upper Canopy Fan Speed",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:fan",
        value_fn=_fan_speed_getter(FAN_TIER_UPPER),
        set_fn=_fan_speed_setter(FAN_TIER_UPPER),
    ),
    HelixNumberDescription(
        key=NUMBER_MID_FAN_SPEED,
        name="Mid Canopy Fan Speed",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:fan",
        value_fn=_fan_speed_getter(FAN_TIER_MID),
        set_fn=_fan_speed_setter(FAN_TIER_MID),
    ),
    HelixNumberDescription(
        key=NUMBER_LOWER_FAN_SPEED,
        name="Lower Canopy Fan Speed",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:fan",
        value_fn=_fan_speed_getter(FAN_TIER_LOWER),
        set_fn=_fan_speed_setter(FAN_TIER_LOWER),
    ),
    # ── Fan variances ─────────────────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_UPPER_FAN_VARIANCE,
        name="Upper Canopy Breeze Variance",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:weather-windy",
        value_fn=_fan_variance_getter(FAN_TIER_UPPER),
        set_fn=_fan_variance_setter(FAN_TIER_UPPER),
    ),
    HelixNumberDescription(
        key=NUMBER_MID_FAN_VARIANCE,
        name="Mid Canopy Breeze Variance",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:weather-windy",
        value_fn=_fan_variance_getter(FAN_TIER_MID),
        set_fn=_fan_variance_setter(FAN_TIER_MID),
    ),
    HelixNumberDescription(
        key=NUMBER_LOWER_FAN_VARIANCE,
        name="Lower Canopy Breeze Variance",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=50.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:weather-windy",
        value_fn=_fan_variance_getter(FAN_TIER_LOWER),
        set_fn=_fan_variance_setter(FAN_TIER_LOWER),
    ),
    # ── Lighting ──────────────────────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_LIGHT_INTENSITY,
        name="Grow Light Intensity",
        native_unit_of_measurement="%",
        native_min_value=0.0,
        native_max_value=100.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:lightbulb-on",
        value_fn=lambda c: c.light_intensity_pct,
        set_fn=lambda c, v: setattr(c, "light_intensity_pct", v),
    ),
    HelixNumberDescription(
        key=NUMBER_SUNRISE_RAMP_MIN,
        name="Sunrise / Sunset Ramp",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        device_class=NumberDeviceClass.DURATION,
        native_min_value=15.0,
        native_max_value=30.0,
        native_step=1.0,
        mode=NumberMode.SLIDER,
        icon="mdi:weather-sunset",
        value_fn=lambda c: float(c._config.get("sunrise_ramp_min", DEFAULT_SUNRISE_RAMP_MIN)),
        set_fn=_persistent_setter("sunrise_ramp_min", int),
    ),
    # ── Energy ────────────────────────────────────────────────────────────────
    HelixNumberDescription(
        key=NUMBER_ELECTRICITY_RATE,
        name="Electricity Rate",
        native_unit_of_measurement="$/kWh",
        native_min_value=0.0,
        native_max_value=5.0,
        native_step=0.001,
        mode=NumberMode.BOX,
        icon="mdi:currency-usd",
        value_fn=lambda c: float(c._config.get("electricity_rate", 0.282)),
        set_fn=_persistent_setter("electricity_rate", lambda v: round(float(v), 4)),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Helix Cultivate number entities from a config entry."""
    coordinator: HelixCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HelixNumber(coordinator, description) for description in NUMBER_DESCRIPTIONS
    )


class HelixNumber(CoordinatorEntity[HelixCoordinator], NumberEntity):
    """A single Helix Cultivate number entity."""

    entity_description: HelixNumberDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HelixCoordinator,
        description: HelixNumberDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator._entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._entry.entry_id)},
            "name": "Helix Cultivate",
            "manufacturer": "Helix Cultivate",
            "model": "Environmental Controller",
            "sw_version": "1.0.0",
        }

    @property
    def native_value(self) -> float:
        """Return the current value from coordinator."""
        try:
            return self.entity_description.value_fn(self.coordinator)
        except Exception:  # noqa: BLE001
            return self.entity_description.native_min_value or 0.0

    async def async_set_native_value(self, value: float) -> None:
        """Apply a new value via the coordinator setter."""
        try:
            self.entity_description.set_fn(self.coordinator, value)
            # Set manual override flag so smooth glides don't clobber user input
            key = self.entity_description.key
            if key == NUMBER_VPD_TARGET:
                self.coordinator.vpd_target_manual_override = True
            elif key == NUMBER_TEMP_SETPOINT:
                self.coordinator.temp_setpoint_manual_override = True
            elif key == NUMBER_RH_SETPOINT:
                self.coordinator.rh_setpoint_manual_override = True
        except Exception:  # noqa: BLE001
            pass
        self.async_write_ha_state()
        if hasattr(self.coordinator, "async_update_listeners"):
            self.coordinator.async_update_listeners()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
