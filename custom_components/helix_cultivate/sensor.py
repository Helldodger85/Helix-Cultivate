"""Helix Cultivate — Sensor platform (17 sensors)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    NS_CLIMATE,
    NS_ENERGY,
    NS_LIGHTING,
    SENSOR_CYCLE_COST,
    SENSOR_CYCLE_KWH,
    SENSOR_DLI_TODAY,
    SENSOR_EXHAUST_SPEED,
    SENSOR_GROW_STAGE,
    SENSOR_LEAF_VPD,
    SENSOR_LOWER_CANOPY_RH,
    SENSOR_LOWER_CANOPY_TEMP,
    SENSOR_LUNG_ENTHALPY,
    SENSOR_LUNG_RH,
    SENSOR_LUNG_TEMP,
    SENSOR_MID_CANOPY_RH,
    SENSOR_MID_CANOPY_TEMP,
    SENSOR_STAGE_DAY,
    SENSOR_UPPER_CANOPY_RH,
    SENSOR_UPPER_CANOPY_TEMP,
    SENSOR_UPPER_ENTHALPY,
    STAGE_LABELS,
)
from .coordinator import HelixCoordinator


@dataclass(frozen=True)
class HelixSensorDescription(SensorEntityDescription):
    """Extended sensor description with coordinator data accessor."""

    value_fn: Callable[[dict[str, Any], "HelixCoordinator"], Any] = lambda d, c: None


def _climate(key: str) -> Callable[[dict, Any], Any]:
    return lambda data, coord: data.get(NS_CLIMATE, {}).get(key)


def _energy(key: str) -> Callable[[dict, Any], Any]:
    return lambda data, coord: data.get(NS_ENERGY, {}).get(key)


def _lighting(key: str) -> Callable[[dict, Any], Any]:
    return lambda data, coord: data.get(NS_LIGHTING, {}).get(key)


def _grow_stage(data: dict, coord: HelixCoordinator) -> Optional[str]:
    stage = coord.stage_manager.current_stage
    return STAGE_LABELS.get(stage, stage)


def _stage_day(data: dict, coord: HelixCoordinator) -> int:
    return coord.stage_manager.elapsed_days


def _cycle_cost(data: dict, coord: HelixCoordinator) -> Optional[float]:
    cost = data.get(NS_ENERGY, {}).get("cycle_cost_usd")
    if cost is None:
        return None
    return float(cost)


SENSOR_DESCRIPTIONS: tuple[HelixSensorDescription, ...] = (
    # ── Zone 2 — Upper canopy ────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_UPPER_CANOPY_TEMP,
        name="Upper Canopy Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("upper_temp_c"),
    ),
    HelixSensorDescription(
        key=SENSOR_UPPER_CANOPY_RH,
        name="Upper Canopy Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("upper_rh_pct"),
    ),
    # ── Zone 2 — Mid canopy ──────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_MID_CANOPY_TEMP,
        name="Mid Canopy Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("mid_temp_c"),
    ),
    HelixSensorDescription(
        key=SENSOR_MID_CANOPY_RH,
        name="Mid Canopy Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("mid_rh_pct"),
    ),
    # ── Zone 2 — Lower canopy ────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_LOWER_CANOPY_TEMP,
        name="Lower Canopy Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("lower_temp_c"),
    ),
    HelixSensorDescription(
        key=SENSOR_LOWER_CANOPY_RH,
        name="Lower Canopy Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("lower_rh_pct"),
    ),
    # ── Zone 1 — Lung Room ───────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_LUNG_TEMP,
        name="Lung Room Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("lung_temp_c"),
    ),
    HelixSensorDescription(
        key=SENSOR_LUNG_RH,
        name="Lung Room Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_climate("lung_rh_pct"),
    ),
    # ── Derived climate values ───────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_LEAF_VPD,
        name="Leaf VPD",
        native_unit_of_measurement="kPa",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_climate("leaf_vpd_kpa"),
    ),
    HelixSensorDescription(
        key=SENSOR_UPPER_ENTHALPY,
        name="Upper Canopy Enthalpy",
        native_unit_of_measurement="kJ/kg",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_climate("upper_enthalpy"),
    ),
    HelixSensorDescription(
        key=SENSOR_LUNG_ENTHALPY,
        name="Lung Room Enthalpy",
        native_unit_of_measurement="kJ/kg",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_climate("lung_enthalpy"),
    ),
    HelixSensorDescription(
        key=SENSOR_EXHAUST_SPEED,
        name="Exhaust Speed",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=_climate("exhaust_pct"),
    ),
    # ── Lighting / DLI ───────────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_DLI_TODAY,
        name="DLI Today",
        native_unit_of_measurement="mol/m²/d",
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=lambda data, coord: data.get(NS_ENERGY, {}).get("dli_today_mol"),
    ),
    # ── Energy / Cost ────────────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_CYCLE_COST,
        name="Cycle Cost",
        native_unit_of_measurement="USD",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=_cycle_cost,
    ),
    HelixSensorDescription(
        key=SENSOR_CYCLE_KWH,
        name="Cycle Energy",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        suggested_display_precision=2,
        value_fn=_energy("cycle_kwh"),
    ),
    # ── Stage tracking ───────────────────────────────────────────────────────
    HelixSensorDescription(
        key=SENSOR_GROW_STAGE,
        name="Grow Stage",
        device_class=SensorDeviceClass.ENUM,
        options=list(STAGE_LABELS.values()),
        value_fn=_grow_stage,
    ),
    HelixSensorDescription(
        key=SENSOR_STAGE_DAY,
        name="Stage Day",
        native_unit_of_measurement="d",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_stage_day,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Helix Cultivate sensors from a config entry."""
    coordinator: HelixCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HelixSensor(coordinator, description) for description in SENSOR_DESCRIPTIONS
    )


class HelixSensor(CoordinatorEntity[HelixCoordinator], SensorEntity):
    """A single Helix Cultivate sensor entity."""

    entity_description: HelixSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HelixCoordinator,
        description: HelixSensorDescription,
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
    def native_value(self) -> Any:
        """Return the current value from coordinator data."""
        if self.coordinator.data is None:
            return None
        try:
            val = self.entity_description.value_fn(self.coordinator.data, self.coordinator)
            if isinstance(val, float):
                return round(val, 4)
            return val
        except Exception:  # noqa: BLE001
            return None

    @property
    def available(self) -> bool:
        """Return True when coordinator data is present."""
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose additional diagnostic attributes on the sensor."""
        attrs: dict[str, Any] = {}
        key = self.entity_description.key
        climate = (self.coordinator.data or {}).get(NS_CLIMATE, {})

        if key == "leaf_vpd":
            attrs["vpd_target_kpa"] = self.coordinator.vpd_target
            attrs["vpd_target_min"] = getattr(self.coordinator, "vpd_target_min", None)
            attrs["vpd_target_max"] = getattr(self.coordinator, "vpd_target_max", None)
            attrs["smooth_glides"] = self.coordinator.smooth_glides_enabled
            attrs["grow_stage"] = self.coordinator.stage_manager.current_stage

        if key in ("upper_canopy_temp", "upper_canopy_rh"):
            attrs["sensor_dropout"] = climate.get("sensor_dropout", False)
            attrs["primary_sensor_ok"] = climate.get("primary_sensor_ok", True)

        if key == "exhaust_speed":
            attrs["thermal_runaway_active"] = climate.get("thermal_runaway", False)
            attrs["lights_on"] = climate.get("lights_on", False)

        if key == "cycle_cost":
            attrs["cycle_kwh"] = (self.coordinator.data or {}).get(NS_ENERGY, {}).get("cycle_kwh", 0.0)
            attrs["electricity_rate"] = self.coordinator._get("electricity_rate", 0.282)

        if key == "grow_stage":
            attrs["cycle_complete"] = self.coordinator.stage_manager.cycle_complete
            attrs["stage_duration"] = self.coordinator.stage_manager.stage_duration
            attrs["stage_durations_planned"] = (
                self.coordinator.stage_manager.planned_stage_durations()
            )

        return attrs
