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
    # Outdoor conditions
    CONF_OUTDOOR_WEATHER_ENTITY,
    CONF_LOCAL_WEATHER_STATION_ENTITY,
    # Sensor dropout Repairs detail (Part 2.1)
    CONF_PRIMARY_TEMP_SENSOR,
    # Lighting & DLI engine (Phase 1.5)
    CONF_ZONE2_GROW_LIGHT,
    CONF_ZONE2_LIGHT_TYPE,
    LIGHT_LED,
    CONF_GROWTH_MODE,
    DEFAULT_GROWTH_MODE,
    CONF_AF_LIGHT_HOURS,
    DEFAULT_AF_LIGHT_HOURS,
    CONF_AF_LIGHTS_ON_TIME,
    DEFAULT_AF_LIGHTS_ON_TIME,
    CONF_PP_VEG_HOURS,
    DEFAULT_PP_VEG_HOURS,
    CONF_PP_VEG_LIGHTS_ON_TIME,
    DEFAULT_PP_VEG_LIGHTS_ON_TIME,
    CONF_PP_FLOWER_HOURS,
    DEFAULT_PP_FLOWER_HOURS,
    CONF_PP_FLOWER_LIGHTS_ON_TIME,
    DEFAULT_PP_FLOWER_LIGHTS_ON_TIME,
    CONF_RAMP_ENABLED,
    DEFAULT_RAMP_ENABLED,
    CONF_RAMP_PRESET,
    DEFAULT_RAMP_PRESET,
    CONF_LIGHT_WATTAGE_W,
    DEFAULT_LIGHT_WATTAGE_W,
    # Supplemental Lighting (independent second light)
    CONF_ZONE2_SUPPLEMENTAL_LIGHT,
    CONF_SUPPLEMENTAL_LIGHT_TYPE,
    CONF_SUPPLEMENTAL_MODE,
    DEFAULT_SUPPLEMENTAL_MODE,
    CONF_SUPPLEMENTAL_TARGET_STAGES,
    CONF_SUPPLEMENTAL_ON_TIME,
    DEFAULT_SUPPLEMENTAL_ON_TIME,
    CONF_SUPPLEMENTAL_DURATION_HOURS,
    DEFAULT_SUPPLEMENTAL_DURATION_HOURS,
    # DLI target alerting
    CONF_DLI_ALERT_THRESHOLD_PCT,
    DEFAULT_DLI_ALERT_THRESHOLD_PCT,
    # Drying-stage airflow strategy (Part 2)
    CONF_DRYING_EXHAUST_MIN_PCT,
    DEFAULT_DRYING_EXHAUST_MIN_PCT,
    CONF_DRYING_HUMIDITY_CEILING_PCT,
    DEFAULT_DRYING_HUMIDITY_CEILING_PCT,
    CONF_DRYING_AIRFLOW_MODE,
    DEFAULT_DRYING_AIRFLOW_MODE,
    CONF_DRYING_CYCLE_ON_MIN,
    DEFAULT_DRYING_CYCLE_ON_MIN,
    CONF_DRYING_CYCLE_OFF_MIN,
    DEFAULT_DRYING_CYCLE_OFF_MIN,
    # Energy & ROI — per-zone EM entity slots + enable toggles
    CONF_EM_ZONE1_S1, CONF_EM_ZONE1_S2, CONF_EM_ZONE1_S3, CONF_EM_ZONE1_S4,
    CONF_EM_ZONE2_S1, CONF_EM_ZONE2_S2, CONF_EM_ZONE2_S3, CONF_EM_ZONE2_S4,
    CONF_EM_DRYING_S1, CONF_EM_DRYING_S2, CONF_EM_DRYING_S3, CONF_EM_DRYING_S4,
    CONF_EM_GLOBAL_S1, CONF_EM_GLOBAL_S2, CONF_EM_GLOBAL_S3, CONF_EM_GLOBAL_S4,
    CONF_EM_ZONE1_ENABLED, CONF_EM_ZONE2_ENABLED, CONF_EM_DRYING_ENABLED,
    DEFAULT_EM_ZONE_ENABLED,
    # Energy & ROI — tariff editing + harvest ROI target
    CONF_TARIFF_MODE, DEFAULT_TARIFF_MODE,
    CONF_TARIFF_ANYTIME, DEFAULT_TARIFF_ANYTIME,
    CONF_TARIFF_PEAK, DEFAULT_TARIFF_PEAK,
    CONF_TARIFF_SHOULDER, DEFAULT_TARIFF_SHOULDER,
    CONF_TARIFF_OFFPEAK, DEFAULT_TARIFF_OFFPEAK,
    CONF_TARIFF_PEAK_START, DEFAULT_TARIFF_PEAK_START,
    CONF_TARIFF_PEAK_END, DEFAULT_TARIFF_PEAK_END,
    CONF_TARIFF_SHOULDER_START, DEFAULT_TARIFF_SHOULDER_START,
    CONF_TARIFF_SHOULDER_END, DEFAULT_TARIFF_SHOULDER_END,
    CONF_HARVEST_VALUE_PER_OZ, DEFAULT_HARVEST_VALUE,
    # Cycle lifecycle (Part 1)
    CONF_CYCLE_STATE,
    # v1.2.8 feature settings, now exposed for editing (Part 3)
    CONF_LIGHT_HIGH_TEMP_DIM_C, DEFAULT_LIGHT_HIGH_TEMP_DIM_C,
    CONF_WIND_SWEEP_ENABLED, DEFAULT_WIND_SWEEP_ENABLED,
    CONF_DEW_POINT_MARGIN_C, DEFAULT_DEW_POINT_MARGIN_C,
    CONF_PREHEAT_LEAD_MIN, DEFAULT_PREHEAT_LEAD_MIN,
    CONF_STAGE_WARNING_LEAD_DAYS, DEFAULT_STAGE_WARNING_LEAD_DAYS,
    # Part 1 — Safety tab sliders
    CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C,
    CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C,
    CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT,
    CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT,
    CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG,
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
        # Pin entity_id to the stable description key rather than letting HA
        # derive it from the human-readable `name` (which the frontend's
        # sensor.helix_cultivate_{key} lookups don't match for most sensors —
        # e.g. "Lung Room Temperature" slugifies to a different string than
        # the "lung_temp" key). Setting entity_id before the entity is added
        # is what entity_platform reads to derive its suggested object_id;
        # note this only takes effect for entities newly created in the
        # registry — see the v1.3 migration in __init__.py for entities that
        # already exist under the old, name-derived entity_id.
        self.entity_id = f"sensor.{DOMAIN}_{description.key}"
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
            # Part 2.1 — the specific currently-flagged sensor(s), sourced
            # from the same state backing the "primary_sensor_dropout"
            # Repairs issue, so the dashboard badge's popover shows real
            # detail instead of just a boolean.
            attrs["sensor_dropout_entities"] = (
                [self.coordinator._get(CONF_PRIMARY_TEMP_SENSOR)]
                if climate.get("sensor_dropout", False)
                and self.coordinator._get(CONF_PRIMARY_TEMP_SENSOR)
                else []
            )
            attrs["primary_sensor_ok"] = climate.get("primary_sensor_ok", True)
            # Part 1.2 — actuator dropout (heater/AC/exhaust unavailable),
            # surfaced separately from the sensor dropout above so the
            # dashboard badge can escalate to red: losing control of
            # hardware is more urgent than losing a passive reading.
            actuator_dropout, actuator_entities = self.coordinator._actuator_dropout_status()
            attrs["actuator_dropout"] = actuator_dropout
            attrs["actuator_dropout_entities"] = actuator_entities

        if key == "exhaust_speed":
            attrs["thermal_runaway_active"] = climate.get("thermal_runaway", False)
            attrs["lights_on"] = climate.get("lights_on", False)
            attrs["mid_canopy_sensor_enabled"] = climate.get("mid_canopy_sensor_enabled", True)
            attrs["lower_canopy_sensor_enabled"] = climate.get("lower_canopy_sensor_enabled", True)
            attrs["mid_canopy_fan_enabled"] = climate.get("mid_canopy_fan_enabled", True)
            attrs["lower_canopy_fan_enabled"] = climate.get("lower_canopy_fan_enabled", True)
            attrs["canopy_temp_spread_c"] = climate.get("canopy_temp_spread_c")
            attrs["canopy_rh_spread_pct"] = climate.get("canopy_rh_spread_pct")
            attrs["canopy_uniformity_insight"] = climate.get("canopy_uniformity_insight")
            attrs["zone2_width_m"] = self.coordinator._get("zone2_width_m", 1.2)
            attrs["zone2_depth_m"] = self.coordinator._get("zone2_depth_m", 1.2)
            attrs["zone2_height_m"] = self.coordinator._get("zone2_height_m", 2.0)
            attrs["zone2_plant_count"] = self.coordinator._get("zone2_plant_count", 4)
            # Reverse Cycle Unit toggles (v1.4.0 Part 5.2) — one per zone,
            # read here so the gear-icon form's checkbox reflects the
            # actually-persisted state when it opens.
            attrs["zone1_is_reverse_cycle"] = self.coordinator._get("zone1_is_reverse_cycle", False)
            attrs["zone2_is_reverse_cycle"] = self.coordinator._get("zone2_is_reverse_cycle", False)
            attrs["drying_is_reverse_cycle"] = self.coordinator._get("drying_is_reverse_cycle", False)
            # Cross-zone dependency flags (v1.4.0 Part 3.1)
            attrs["zone2_depends_on_conditioning"] = self.coordinator._get(
                "zone2_depends_on_conditioning", True
            )
            attrs["drying_depends_on_conditioning"] = self.coordinator._get(
                "drying_depends_on_conditioning", True
            )
            # Environmental Learning System (v1.4.0 Parts 7-10)
            attrs["thermal_learning_enabled"] = self.coordinator._get(
                "thermal_learning_enabled", False
            )
            attrs["thermal_learning_duration_days"] = self.coordinator._get(
                "thermal_learning_duration_days", 18
            )
            attrs["thermal_learning_export_enabled"] = self.coordinator._get(
                "thermal_learning_export_enabled", False
            )
            attrs["thermal_learning_export_url"] = self.coordinator._get(
                "thermal_learning_export_url", ""
            )
            # Zone occupancy (v1.4.0 Part 4) — drives "Space Now Empty" and
            # "Harvest Complete" (dedicated Drying Room) visibility.
            attrs["zone2_occupied"] = self.coordinator.is_zone2_occupied()
            attrs["drying_occupied"] = self.coordinator.is_drying_occupied()
            # v1.4.1 Part 3: live day-count for a Drying-Room batch,
            # recomputed on every read from its own unchanging
            # drying_stage_start_date — never a value frozen at the moment
            # "Space Now Empty" was pressed.
            attrs["drying_batch_elapsed_days"] = self.coordinator.drying_batch_elapsed_days()
            # Outdoor conditions (local weather station override applied
            # server-side if mapped)
            attrs["outdoor_weather_entity"] = self.coordinator._get(CONF_OUTDOOR_WEATHER_ENTITY)
            attrs["local_weather_station_entity"] = self.coordinator._get(
                CONF_LOCAL_WEATHER_STATION_ENTITY
            )
            attrs["outdoor_temp_c"] = climate.get("outdoor_temp_c")
            attrs["outdoor_rh_pct"] = climate.get("outdoor_rh_pct")
            # Lighting & DLI engine (Phase 1.5)
            attrs["zone2_grow_light"] = self.coordinator._get(CONF_ZONE2_GROW_LIGHT)
            attrs["zone2_light_type"] = self.coordinator._get(CONF_ZONE2_LIGHT_TYPE, LIGHT_LED)
            attrs["light_applied_pct"] = climate.get("light_applied_pct")
            attrs["growth_mode"] = self.coordinator._get(CONF_GROWTH_MODE, DEFAULT_GROWTH_MODE)
            attrs["af_light_hours"] = self.coordinator._get(
                CONF_AF_LIGHT_HOURS, DEFAULT_AF_LIGHT_HOURS
            )
            attrs["af_lights_on_time"] = self.coordinator._get(
                CONF_AF_LIGHTS_ON_TIME, DEFAULT_AF_LIGHTS_ON_TIME
            )
            attrs["pp_veg_hours"] = self.coordinator._get(
                CONF_PP_VEG_HOURS, DEFAULT_PP_VEG_HOURS
            )
            attrs["pp_veg_lights_on_time"] = self.coordinator._get(
                CONF_PP_VEG_LIGHTS_ON_TIME, DEFAULT_PP_VEG_LIGHTS_ON_TIME
            )
            attrs["pp_flower_hours"] = self.coordinator._get(
                CONF_PP_FLOWER_HOURS, DEFAULT_PP_FLOWER_HOURS
            )
            attrs["pp_flower_lights_on_time"] = self.coordinator._get(
                CONF_PP_FLOWER_LIGHTS_ON_TIME, DEFAULT_PP_FLOWER_LIGHTS_ON_TIME
            )
            attrs["ramp_enabled"] = self.coordinator._get(CONF_RAMP_ENABLED, DEFAULT_RAMP_ENABLED)
            attrs["ramp_preset"] = self.coordinator._get(CONF_RAMP_PRESET, DEFAULT_RAMP_PRESET)
            attrs["light_wattage_w"] = self.coordinator._get(
                CONF_LIGHT_WATTAGE_W, DEFAULT_LIGHT_WATTAGE_W
            )
            # Supplemental Lighting (independent second light)
            attrs["zone2_supplemental_light"] = self.coordinator._get(CONF_ZONE2_SUPPLEMENTAL_LIGHT)
            attrs["supplemental_light_type"] = self.coordinator._get(
                CONF_SUPPLEMENTAL_LIGHT_TYPE, LIGHT_LED
            )
            attrs["supplemental_mode"] = self.coordinator._get(
                CONF_SUPPLEMENTAL_MODE, DEFAULT_SUPPLEMENTAL_MODE
            )
            attrs["supplemental_target_stages"] = self.coordinator._get(
                CONF_SUPPLEMENTAL_TARGET_STAGES, []
            )
            attrs["supplemental_on_time"] = self.coordinator._get(
                CONF_SUPPLEMENTAL_ON_TIME, DEFAULT_SUPPLEMENTAL_ON_TIME
            )
            attrs["supplemental_duration_hours"] = self.coordinator._get(
                CONF_SUPPLEMENTAL_DURATION_HOURS, DEFAULT_SUPPLEMENTAL_DURATION_HOURS
            )
            attrs["supplemental_applied_pct"] = self.coordinator._supplemental_applied_pct
            # DLI target alerting
            attrs["dli_alert_threshold_pct"] = self.coordinator._get(
                CONF_DLI_ALERT_THRESHOLD_PCT, DEFAULT_DLI_ALERT_THRESHOLD_PCT
            )
            attrs["target_dli_mol"] = self.coordinator.stage_manager._profile(
                self.coordinator.stage_manager.current_stage
            ).get("target_dli_mol", 0.0)
            # Drying-stage airflow strategy (Part 2)
            attrs["drying_exhaust_min_pct"] = self.coordinator._get(
                CONF_DRYING_EXHAUST_MIN_PCT, DEFAULT_DRYING_EXHAUST_MIN_PCT
            )
            attrs["drying_humidity_ceiling_pct"] = self.coordinator._get(
                CONF_DRYING_HUMIDITY_CEILING_PCT, DEFAULT_DRYING_HUMIDITY_CEILING_PCT
            )
            attrs["drying_airflow_mode"] = self.coordinator._get(
                CONF_DRYING_AIRFLOW_MODE, DEFAULT_DRYING_AIRFLOW_MODE
            )
            attrs["drying_cycle_on_min"] = self.coordinator._get(
                CONF_DRYING_CYCLE_ON_MIN, DEFAULT_DRYING_CYCLE_ON_MIN
            )
            attrs["drying_cycle_off_min"] = self.coordinator._get(
                CONF_DRYING_CYCLE_OFF_MIN, DEFAULT_DRYING_CYCLE_OFF_MIN
            )
            attrs["drying_airflow_applied_pct"] = self.coordinator._drying_airflow_applied_pct
            attrs["drying_humidity_override_active"] = (
                self.coordinator._drying_humidity_override_active
            )
            # Energy & ROI — per-zone EM entity mappings + enable toggles.
            # Exposed here (in addition to hw_map, which the gear-icon form
            # reads for Save/edit prefill) so the live dashboard grid can
            # read each slot's entity id directly, same dual-exposure
            # pattern as zone2_grow_light above.
            attrs["em_zone1_s1"] = self.coordinator._get(CONF_EM_ZONE1_S1)
            attrs["em_zone1_s2"] = self.coordinator._get(CONF_EM_ZONE1_S2)
            attrs["em_zone1_s3"] = self.coordinator._get(CONF_EM_ZONE1_S3)
            attrs["em_zone1_s4"] = self.coordinator._get(CONF_EM_ZONE1_S4)
            attrs["em_zone2_s1"] = self.coordinator._get(CONF_EM_ZONE2_S1)
            attrs["em_zone2_s2"] = self.coordinator._get(CONF_EM_ZONE2_S2)
            attrs["em_zone2_s3"] = self.coordinator._get(CONF_EM_ZONE2_S3)
            attrs["em_zone2_s4"] = self.coordinator._get(CONF_EM_ZONE2_S4)
            attrs["em_drying_s1"] = self.coordinator._get(CONF_EM_DRYING_S1)
            attrs["em_drying_s2"] = self.coordinator._get(CONF_EM_DRYING_S2)
            attrs["em_drying_s3"] = self.coordinator._get(CONF_EM_DRYING_S3)
            attrs["em_drying_s4"] = self.coordinator._get(CONF_EM_DRYING_S4)
            attrs["em_global_s1"] = self.coordinator._get(CONF_EM_GLOBAL_S1)
            attrs["em_global_s2"] = self.coordinator._get(CONF_EM_GLOBAL_S2)
            attrs["em_global_s3"] = self.coordinator._get(CONF_EM_GLOBAL_S3)
            attrs["em_global_s4"] = self.coordinator._get(CONF_EM_GLOBAL_S4)
            attrs["em_zone1_enabled"] = self.coordinator._get(
                CONF_EM_ZONE1_ENABLED, DEFAULT_EM_ZONE_ENABLED
            )
            attrs["em_zone2_enabled"] = self.coordinator._get(
                CONF_EM_ZONE2_ENABLED, DEFAULT_EM_ZONE_ENABLED
            )
            attrs["em_drying_enabled"] = self.coordinator._get(
                CONF_EM_DRYING_ENABLED, DEFAULT_EM_ZONE_ENABLED
            )
            # Energy & ROI — tariff editing + harvest ROI target
            attrs["tariff_mode"] = self.coordinator._get(CONF_TARIFF_MODE, DEFAULT_TARIFF_MODE)
            attrs["tariff_anytime_rate"] = self.coordinator._get(
                CONF_TARIFF_ANYTIME, DEFAULT_TARIFF_ANYTIME
            )
            attrs["tariff_peak_rate"] = self.coordinator._get(CONF_TARIFF_PEAK, DEFAULT_TARIFF_PEAK)
            attrs["tariff_shoulder_rate"] = self.coordinator._get(
                CONF_TARIFF_SHOULDER, DEFAULT_TARIFF_SHOULDER
            )
            attrs["tariff_offpeak_rate"] = self.coordinator._get(
                CONF_TARIFF_OFFPEAK, DEFAULT_TARIFF_OFFPEAK
            )
            attrs["tariff_peak_start"] = self.coordinator._get(
                CONF_TARIFF_PEAK_START, DEFAULT_TARIFF_PEAK_START
            )
            attrs["tariff_peak_end"] = self.coordinator._get(
                CONF_TARIFF_PEAK_END, DEFAULT_TARIFF_PEAK_END
            )
            attrs["tariff_shoulder_start"] = self.coordinator._get(
                CONF_TARIFF_SHOULDER_START, DEFAULT_TARIFF_SHOULDER_START
            )
            attrs["tariff_shoulder_end"] = self.coordinator._get(
                CONF_TARIFF_SHOULDER_END, DEFAULT_TARIFF_SHOULDER_END
            )
            attrs["harvest_value_per_oz"] = self.coordinator._get(
                CONF_HARVEST_VALUE_PER_OZ, DEFAULT_HARVEST_VALUE
            )
            # v1.2.8 feature settings, now exposed for editing (Part 3) —
            # each pre-fills its gear-icon/settings control with the
            # already-coded default until a grower changes it.
            attrs["light_high_temp_dim_c"] = self.coordinator._get(
                CONF_LIGHT_HIGH_TEMP_DIM_C, DEFAULT_LIGHT_HIGH_TEMP_DIM_C
            )
            attrs["wind_sweep_enabled"] = self.coordinator._get(
                CONF_WIND_SWEEP_ENABLED, DEFAULT_WIND_SWEEP_ENABLED
            )
            attrs["dew_point_margin_c"] = self.coordinator._get(
                CONF_DEW_POINT_MARGIN_C, DEFAULT_DEW_POINT_MARGIN_C
            )
            attrs["preheat_lead_min"] = self.coordinator._get(
                CONF_PREHEAT_LEAD_MIN, DEFAULT_PREHEAT_LEAD_MIN
            )
            # Part 1 — Safety tab sliders now write to real live number
            # entities, but the panel's own dashboard reads its displayed
            # values from these attributes (not the entity states directly),
            # so without exposing them here a reload would always show the
            # coded default regardless of what was actually persisted.
            attrs["safety_high_temp_c"] = self.coordinator._get(
                CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C
            )
            attrs["safety_low_temp_c"] = self.coordinator._get(
                CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C
            )
            attrs["safety_high_rh_pct"] = self.coordinator._get(
                CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT
            )
            attrs["safety_low_rh_pct"] = self.coordinator._get(
                CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT
            )
            attrs["sensor_dropout_min"] = self.coordinator._get(
                CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG
            )

        if key == "cycle_cost":
            attrs["cycle_kwh"] = (self.coordinator.data or {}).get(NS_ENERGY, {}).get("cycle_kwh", 0.0)
            attrs["electricity_rate"] = self.coordinator._get("electricity_rate", 0.282)

        if key == "grow_stage":
            attrs["cycle_complete"] = self.coordinator.stage_manager.cycle_complete
            attrs["stage_duration"] = self.coordinator.stage_manager.stage_duration
            attrs["stage_durations_planned"] = (
                self.coordinator.stage_manager.planned_stage_durations()
            )
            # Cycle lifecycle (Part 1) — "not_started" or "active". Drives
            # the dashboard's "No Active Cycle" empty state.
            attrs["cycle_state"] = self.coordinator.stage_manager.cycle_state
            attrs["stage_warning_lead_days"] = self.coordinator._get(
                CONF_STAGE_WARNING_LEAD_DAYS, DEFAULT_STAGE_WARNING_LEAD_DAYS
            )

        return attrs
