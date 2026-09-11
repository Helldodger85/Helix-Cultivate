"""Constants for the Helix Cultivate integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

# ── Integration identity ─────────────────────────────────────────────────────
DOMAIN: str = "helix_cultivate"
CONFIG_VERSION: int = 1
CONFIG_MINOR_VERSION: int = 5

# ── Coordinator ──────────────────────────────────────────────────────────────
COORDINATOR_UPDATE_INTERVAL: timedelta = timedelta(seconds=30)

# Debounce window for persistent number/select setters writing to config-entry
# options. Batches rapid successive slider drags into a single options write
# (and therefore a single reload), instead of one reload per change.
OPTIONS_WRITE_DEBOUNCE_SEC: float = 1.5

# Continuous minutes leaf VPD may sit outside [vpd_target_min, vpd_target_max]
# before it's treated as chronic/sustained drift (as opposed to an instant
# threshold breach) and fires helix_cultivate_chronic_drift_detected.
CHRONIC_VPD_DRIFT_DWELL_MIN: float = 240.0  # 4 hours

# ── Canopy uniformity diagnostic ─────────────────────────────────────────────
# Spread (max - min) across active sensor *layers* (upper, plus mid/lower if
# their sensor toggle is enabled) that counts as a gradient worth flagging,
# once sustained for CANOPY_UNIFORMITY_DWELL_MIN.
CANOPY_UNIFORMITY_TEMP_DELTA_C: float = 2.0
CANOPY_UNIFORMITY_RH_DELTA_PCT: float = 8.0
CANOPY_UNIFORMITY_DWELL_MIN: float = 15.0

# ── Topology modes ───────────────────────────────────────────────────────────
TOPOLOGY_COORDINATED: str = "coordinated"
TOPOLOGY_STANDALONE: str = "standalone"

TOPOLOGY_OPTIONS: list[str] = [TOPOLOGY_COORDINATED, TOPOLOGY_STANDALONE]

TOPOLOGY_LABELS: dict[str, str] = {
    TOPOLOGY_COORDINATED: "Coordinated (Primary Grow Space + Conditioning Room)",
    TOPOLOGY_STANDALONE: "Standalone (Primary Grow Space Only)",
}

# ── Zone identifiers ─────────────────────────────────────────────────────────
ZONE_LUNG: str = "zone_lung"
ZONE_TENT: str = "zone_tent"

# ── Zone types (Phase 1 active; Phase 2 stubs for forward-compatibility) ─────
ZONE_TYPE_CLIMATE: str = "climate"
ZONE_TYPE_FERTIGATION_INDOOR: str = "fertigation"  # Phase 2 stub
ZONE_TYPE_IRRIGATION_OUTDOOR: str = "irrigation"   # Phase 2 stub

# ── Zone profile types ────────────────────────────────────────────────────────
ZONE_PROFILE_CULTIVATION: str = "cultivation"    # Primary grow spaces
ZONE_PROFILE_CONDITIONING: str = "conditioning"  # Conditioning / lung room
ZONE_PROFILE_DRYING: str = "drying"              # Dedicated drying room

# ── Feature flags ────────────────────────────────────────────────────────────
FEATURE_CLIMATE: str = "climate"
FEATURE_FERTIGATION: str = "fertigation"  # Phase 2 stub

# ── Control algorithms ───────────────────────────────────────────────────────
ALGO_BANG_BANG: str = "bang_bang"
ALGO_PID: str = "pid"

ALGO_OPTIONS: list[str] = [ALGO_BANG_BANG, ALGO_PID]

ALGO_LABELS: dict[str, str] = {
    ALGO_BANG_BANG: "Bang-Bang (Hysteresis)",
    ALGO_PID: "True PID Control",
}

# ── Fan tiers ────────────────────────────────────────────────────────────────
FAN_TIER_UPPER: str = "upper"
FAN_TIER_MID: str = "mid"
FAN_TIER_LOWER: str = "lower"

FAN_TIERS: list[str] = [FAN_TIER_UPPER, FAN_TIER_MID, FAN_TIER_LOWER]

# ── Fan control modes ────────────────────────────────────────────────────────
FAN_CONTROL_PWM_10STEP: str = "pwm_10step"
FAN_CONTROL_CONTINUOUS: str = "continuous"
FAN_CONTROL_BANG_BANG: str = "bang_bang"

FAN_CONTROL_OPTIONS: list[str] = [
    FAN_CONTROL_PWM_10STEP,
    FAN_CONTROL_CONTINUOUS,
    FAN_CONTROL_BANG_BANG,
]

FAN_CONTROL_LABELS: dict[str, str] = {
    FAN_CONTROL_PWM_10STEP: "PWM 10-Step (10% increments)",
    FAN_CONTROL_CONTINUOUS: "Continuous 0–100%",
    FAN_CONTROL_BANG_BANG: "Bang-Bang Switched Relay",
}

# ── Breeze engine parameters ─────────────────────────────────────────────────
BREEZE_INTERVAL_MIN_SEC: int = 8
BREEZE_INTERVAL_MAX_SEC: int = 25

# ── Grow stages ──────────────────────────────────────────────────────────────
STAGE_GERMINATION: str = "germination"
STAGE_SEEDLING: str = "seedling"
STAGE_EARLY_VEG: str = "early_veg"
STAGE_LATE_VEG: str = "late_veg"
STAGE_STRETCH: str = "stretch"
STAGE_PEAK_FLOWER: str = "peak_flower"
STAGE_RIPENING: str = "ripening"
STAGE_DRYING: str = "drying"

STAGE_SEQUENCE: list[str] = [
    STAGE_GERMINATION,
    STAGE_SEEDLING,
    STAGE_EARLY_VEG,
    STAGE_LATE_VEG,
    STAGE_STRETCH,
    STAGE_PEAK_FLOWER,
    STAGE_RIPENING,
    STAGE_DRYING,
]

STAGE_LABELS: dict[str, str] = {
    STAGE_GERMINATION: "Germination",
    STAGE_SEEDLING: "Seedling",
    STAGE_EARLY_VEG: "Early Veg",
    STAGE_LATE_VEG: "Late Veg",
    STAGE_STRETCH: "Stretch / Pre-Flower",
    STAGE_PEAK_FLOWER: "Peak Flower",
    STAGE_RIPENING: "Ripening / Flush",
    STAGE_DRYING: "Drying",
}

# Default stage durations (days) used when no recipe is loaded
STAGE_DEFAULT_DURATIONS: dict[str, int] = {
    STAGE_GERMINATION: 4,
    STAGE_SEEDLING: 10,
    STAGE_EARLY_VEG: 14,
    STAGE_LATE_VEG: 14,
    STAGE_STRETCH: 14,
    STAGE_PEAK_FLOWER: 28,
    STAGE_RIPENING: 14,
    STAGE_DRYING: 10,
}

# ── Day/Night environmental targets per stage (Phase 5) ───────────────────────
STAGE_DAYNIGHT_DEFAULTS: dict[str, dict[str, Any]] = {
    STAGE_GERMINATION: {
        "day_temp_c": 24.0, "night_temp_c": 22.0,
        "day_vpd_min": 0.35, "day_vpd_max": 0.50,
        "night_vpd_min": 0.30, "night_vpd_max": 0.45,
        "light_intensity_pct": 50, "photoperiod_h": 20.0,
        "fan_speed_pct": 25,
    },
    STAGE_SEEDLING: {
        "day_temp_c": 23.5, "night_temp_c": 21.0,
        "day_vpd_min": 0.50, "day_vpd_max": 0.70,
        "night_vpd_min": 0.40, "night_vpd_max": 0.60,
        "light_intensity_pct": 60, "photoperiod_h": 20.0,
        "fan_speed_pct": 30,
    },
    STAGE_EARLY_VEG: {
        "day_temp_c": 24.0, "night_temp_c": 20.0,
        "day_vpd_min": 0.60, "day_vpd_max": 0.90,
        "night_vpd_min": 0.45, "night_vpd_max": 0.65,
        "light_intensity_pct": 70, "photoperiod_h": 18.0,
        "fan_speed_pct": 35,
    },
    STAGE_LATE_VEG: {
        "day_temp_c": 24.0, "night_temp_c": 20.0,
        "day_vpd_min": 0.80, "day_vpd_max": 1.05,
        "night_vpd_min": 0.60, "night_vpd_max": 0.80,
        "light_intensity_pct": 80, "photoperiod_h": 18.0,
        "fan_speed_pct": 40,
    },
    STAGE_STRETCH: {
        "day_temp_c": 25.0, "night_temp_c": 21.0,
        "day_vpd_min": 0.90, "day_vpd_max": 1.15,
        "night_vpd_min": 0.70, "night_vpd_max": 0.90,
        "light_intensity_pct": 90, "photoperiod_h": 12.0,
        "fan_speed_pct": 45,
    },
    STAGE_PEAK_FLOWER: {
        "day_temp_c": 26.0, "night_temp_c": 22.0,
        "day_vpd_min": 1.10, "day_vpd_max": 1.40,
        "night_vpd_min": 0.85, "night_vpd_max": 1.10,
        "light_intensity_pct": 100, "photoperiod_h": 12.0,
        "fan_speed_pct": 50,
    },
    STAGE_RIPENING: {
        "day_temp_c": 24.0, "night_temp_c": 18.0,
        "day_vpd_min": 1.30, "day_vpd_max": 1.55,
        "night_vpd_min": 1.00, "night_vpd_max": 1.25,
        "light_intensity_pct": 85, "photoperiod_h": 12.0,
        "fan_speed_pct": 45,
    },
    STAGE_DRYING: {
        "day_temp_c": 15.5, "night_temp_c": 15.5,
        "day_vpd_min": 1.05, "day_vpd_max": 1.15,
        "night_vpd_min": 1.05, "night_vpd_max": 1.15,
        "light_intensity_pct": 0, "photoperiod_h": 0.0,
        "fan_speed_pct": 40,
    },
}

# ── Progression modes ────────────────────────────────────────────────────────
PROG_MANUAL: str = "manual"
PROG_TIMEFRAME: str = "timeframe"

PROG_OPTIONS: list[str] = [PROG_MANUAL, PROG_TIMEFRAME]

PROG_LABELS: dict[str, str] = {
    PROG_MANUAL: "Manual (locked until changed)",
    PROG_TIMEFRAME: "Timeframe Managed (auto-advance)",
}

# ── Light types ───────────────────────────────────────────────────────────────
LIGHT_LED: str = "led"
LIGHT_FULL_SPECTRUM: str = "full_spectrum_led"
LIGHT_HID: str = "hid_ballast"
LIGHT_SUPPLEMENTAL: str = "supplemental"

LIGHT_TYPE_OPTIONS: list[str] = [
    LIGHT_LED,
    LIGHT_FULL_SPECTRUM,
    LIGHT_HID,
    LIGHT_SUPPLEMENTAL,
]

LIGHT_TYPE_LABELS: dict[str, str] = {
    LIGHT_LED: "LED",
    LIGHT_FULL_SPECTRUM: "Full Spectrum LED",
    LIGHT_HID: "HID / Ballast",
    LIGHT_SUPPLEMENTAL: "Supplemental",
}

# Default leaf-temperature offset per fixture type (°C, leaf below air temp).
# Applied automatically based on zone2_light_type; overridden unconditionally
# by a manually-persisted CONF_LEAF_TEMP_OFFSET_C (see
# HelixCoordinator.effective_leaf_temp_offset_c).
FIXTURE_LEAF_OFFSET_DEFAULTS: dict[str, float] = {
    LIGHT_LED: -2.0,
    LIGHT_FULL_SPECTRUM: -2.5,
    LIGHT_HID: -4.0,
    LIGHT_SUPPLEMENTAL: -1.0,
}

# Default photosynthetic efficacy per fixture type (μmol/J), used by the DLI
# estimation fallback (B7) when no physical PAR/DLI sensor is mapped.
FIXTURE_EFFICACY_UMOL_PER_J: dict[str, float] = {
    LIGHT_LED: 2.7,
    LIGHT_FULL_SPECTRUM: 2.5,
    LIGHT_HID: 1.7,
    LIGHT_SUPPLEMENTAL: 2.0,
}

# Minutes an HID/ballast fixture must stay off before it may be re-struck —
# real HID arc tubes need to cool before they can reliably restrike. Reuses
# the anti-short-cycle dwell-timer pattern (see _last_compressor_off).
DEFAULT_HID_RESTRIKE_LOCKOUT_MIN: float = 15.0

# ── Growth mode (autoflower vs. photoperiod) ─────────────────────────────────
CONF_GROWTH_MODE: str = "growth_mode"
GROWTH_MODE_AUTOFLOWER: str = "autoflower"
GROWTH_MODE_PHOTOPERIOD: str = "photoperiod"
GROWTH_MODE_OPTIONS: list[str] = [GROWTH_MODE_AUTOFLOWER, GROWTH_MODE_PHOTOPERIOD]
GROWTH_MODE_LABELS: dict[str, str] = {
    GROWTH_MODE_AUTOFLOWER: "Autoflower (constant schedule)",
    GROWTH_MODE_PHOTOPERIOD: "Photoperiod (Veg / Flower schedules)",
}
DEFAULT_GROWTH_MODE: str = GROWTH_MODE_PHOTOPERIOD

# Autoflower: one constant schedule for the entire grow, regardless of stage.
CONF_AF_LIGHT_HOURS: str = "af_light_hours"
DEFAULT_AF_LIGHT_HOURS: float = 18.0
CONF_AF_LIGHTS_ON_TIME: str = "af_lights_on_time"
DEFAULT_AF_LIGHTS_ON_TIME: str = "06:00"

# Photoperiod: separate Vegetative and Flowering schedules. The stage-group
# mapping below is fixed horticultural consensus, not user-configurable —
# Stretch is the plant's response *after* the light flip, so it belongs to
# the Flowering group. Users wanting a different mapping can still do so via
# recipe export/import YAML.
CONF_PP_VEG_HOURS: str = "pp_veg_hours"
DEFAULT_PP_VEG_HOURS: float = 18.0
CONF_PP_VEG_LIGHTS_ON_TIME: str = "pp_veg_lights_on_time"
DEFAULT_PP_VEG_LIGHTS_ON_TIME: str = "06:00"

CONF_PP_FLOWER_HOURS: str = "pp_flower_hours"
DEFAULT_PP_FLOWER_HOURS: float = 12.0
CONF_PP_FLOWER_LIGHTS_ON_TIME: str = "pp_flower_lights_on_time"
DEFAULT_PP_FLOWER_LIGHTS_ON_TIME: str = "06:00"

PHOTOPERIOD_VEG_STAGES: frozenset[str] = frozenset({
    STAGE_GERMINATION, STAGE_SEEDLING, STAGE_EARLY_VEG, STAGE_LATE_VEG,
})
PHOTOPERIOD_FLOWER_STAGES: frozenset[str] = frozenset({
    STAGE_STRETCH, STAGE_PEAK_FLOWER, STAGE_RIPENING,
})

# ── Sunrise/sunset dimming ramp ───────────────────────────────────────────────
CONF_RAMP_ENABLED: str = "ramp_enabled"
DEFAULT_RAMP_ENABLED: bool = True

CONF_RAMP_PRESET: str = "ramp_preset"
RAMP_PRESET_GENTLE: str = "gentle"
RAMP_PRESET_STANDARD: str = "standard"
RAMP_PRESET_FAST: str = "fast"
RAMP_PRESET_CUSTOM: str = "custom"
RAMP_PRESET_OPTIONS: list[str] = [
    RAMP_PRESET_GENTLE, RAMP_PRESET_STANDARD, RAMP_PRESET_FAST, RAMP_PRESET_CUSTOM,
]
RAMP_PRESET_LABELS: dict[str, str] = {
    RAMP_PRESET_GENTLE: "Gentle (~30 min)",
    RAMP_PRESET_STANDARD: "Standard (~15 min)",
    RAMP_PRESET_FAST: "Fast (~5 min)",
    RAMP_PRESET_CUSTOM: "Custom",
}
# Fixed durations for the named presets; "custom" instead uses the existing
# CONF_SUNRISE_RAMP_MIN number value.
RAMP_PRESET_MINUTES: dict[str, float] = {
    RAMP_PRESET_GENTLE: 30.0,
    RAMP_PRESET_STANDARD: 15.0,
    RAMP_PRESET_FAST: 5.0,
}
DEFAULT_RAMP_PRESET: str = RAMP_PRESET_STANDARD

# ── DLI estimation fallback (used only when no CONF_DLI_SENSOR is mapped) ────
CONF_LIGHT_WATTAGE_W: str = "light_wattage_w"
DEFAULT_LIGHT_WATTAGE_W: float = 600.0
CONF_LIGHT_EFFICACY_UMOL_PER_J: str = "light_efficacy_umol_per_j"

# ── Drying zone fixed targets ────────────────────────────────────────────────
DRYING_TARGET_TEMP_C: float = 15.5   # Fixed 60/60 drying profile target temp
DRYING_TARGET_RH_PCT: float = 60.0   # Fixed 60/60 drying profile target RH
DRYING_CYCLE_EXHAUST_PCT: float = 25.0  # Gentle cyclic exhaust for drying zone

# ── Safety defaults ───────────────────────────────────────────────────────────
DEFAULT_HEATER_CUTOFF_C: float = 26.0
DEFAULT_THERMAL_RUNAWAY_C: float = 32.0
DEFAULT_ANTI_SHORT_CYCLE_MIN: int = 3
DEFAULT_LEAF_TEMP_OFFSET_C: float = -2.5
DEFAULT_EXHAUST_MIN_PCT: int = 10
DEFAULT_SENSOR_DROPOUT_MIN: int = 30
DEFAULT_EXHAUST_SAFE_FLOOR_PCT: int = 30
DEFAULT_VPD_TARGET_KPA: float = 1.0
DEFAULT_TEMP_SETPOINT_C: float = 24.0
DEFAULT_RH_SETPOINT_PCT: float = 65.0
DEFAULT_SUNRISE_RAMP_MIN: int = 20
DEFAULT_FAN_SPEED_PCT: int = 50
DEFAULT_FAN_VARIANCE_PCT: int = 20
DEFAULT_LIGHT_INTENSITY_PCT: int = 100
DEFAULT_BACKUP_HEATER_THRESHOLD_C: float = 5.0

# Stratification thresholds
STRATIFICATION_TEMP_DELTA_C: float = 2.0
STRATIFICATION_RH_DELTA_PCT: float = 8.0
LIGHTS_OFF_PURGE_DURATION_MIN: int = 30
FEEDFORWARD_PRECONDITIONING_MIN: int = 40  # midpoint of 30–45 min window

# Sensor rolling median buffer size
SENSOR_MEDIAN_BUFFER_SIZE: int = 3

# ── Coordinator data namespaces ───────────────────────────────────────────────
NS_CLIMATE: str = "climate"
NS_LIGHTING: str = "lighting"
NS_ENERGY: str = "energy"
NS_FERTIGATION: str = "fertigation"  # Phase 2 stub

# ── Config Entry keys ─────────────────────────────────────────────────────────

# Topology & primary canopy sensor pair (REQUIRED in old flow; now in options)
CONF_TOPOLOGY: str = "topology"
CONF_PRIMARY_TEMP_SENSOR: str = "primary_temp_sensor"
CONF_PRIMARY_HUMIDITY_SENSOR: str = "primary_humidity_sensor"

# ── Module enable flags (derived from topology at setup; user-editable in options) ───
# True when the Conditioning Room zone and tab should be active
CONF_ENABLE_CONDITIONING_ROOM: str = "enable_conditioning_room"
# True when the Drying Environment zone and tab should be active
CONF_ENABLE_DRYING_ENVIRONMENT: str = "enable_drying_environment"

# ── Sensor calibration offsets (per-zone, native hardware drift correction) ───
CONF_PRIMARY_TEMP_OFFSET: str = "primary_temp_offset"
CONF_PRIMARY_HUMIDITY_OFFSET: str = "primary_humidity_offset"
CONF_LUNG_TEMP_OFFSET: str = "lung_temp_offset"
CONF_LUNG_HUMIDITY_OFFSET: str = "lung_humidity_offset"
CONF_UPPER_TEMP_OFFSET: str = "upper_temp_offset"
CONF_UPPER_HUMIDITY_OFFSET: str = "upper_humidity_offset"
CONF_MID_TEMP_OFFSET: str = "mid_temp_offset"
CONF_MID_HUMIDITY_OFFSET: str = "mid_humidity_offset"
CONF_LOWER_TEMP_OFFSET: str = "lower_temp_offset"
CONF_LOWER_HUMIDITY_OFFSET: str = "lower_humidity_offset"
CONF_DRYING_TEMP_OFFSET: str = "drying_temp_offset"
CONF_DRYING_HUMIDITY_OFFSET: str = "drying_humidity_offset"

# ── Zone dimension & plant metadata ──────────────────────────────────────────
CONF_ZONE2_WIDTH_M: str = "zone2_width_m"
CONF_ZONE2_DEPTH_M: str = "zone2_depth_m"
CONF_ZONE2_HEIGHT_M: str = "zone2_height_m"
CONF_ZONE2_PLANT_COUNT: str = "zone2_plant_count"

# ── Safety interlock ceilings ─────────────────────────────────────────────────
CONF_SAFETY_HIGH_TEMP_C: str = "safety_high_temp_c"
CONF_SAFETY_LOW_TEMP_C: str = "safety_low_temp_c"
CONF_SAFETY_HIGH_RH_PCT: str = "safety_high_rh_pct"
CONF_SAFETY_LOW_RH_PCT: str = "safety_low_rh_pct"
CONF_SENSOR_DROPOUT_MIN: str = "sensor_dropout_min"

# Safety defaults
DEFAULT_SAFETY_HIGH_TEMP_C: float = 32.0
DEFAULT_SAFETY_LOW_TEMP_C: float = 15.0
DEFAULT_SAFETY_HIGH_RH_PCT: float = 85.0
DEFAULT_SAFETY_LOW_RH_PCT: float = 30.0
DEFAULT_SENSOR_DROPOUT_MIN_CFG: int = 30

# ── Zone display names (user-customisable) ────────────────────────────────────
CONF_ZONE1_NAME: str = "zone1_name"
CONF_ZONE2_NAME: str = "zone2_name"
CONF_DRYING_ZONE_NAME: str = "drying_zone_name"
CONF_DRYING_ENABLED: str = "drying_enabled"

# Default zone display names
DEFAULT_ZONE1_NAME: str = "Primary Grow Space 1"
DEFAULT_ZONE2_NAME: str = "Conditioning Room"
DEFAULT_DRYING_ZONE_NAME: str = "Drying Room"

# Zone 1 — Lung Room sensor pair (optional)
CONF_LUNG_TEMP_SENSOR: str = "lung_temp_sensor"
CONF_LUNG_HUMIDITY_SENSOR: str = "lung_humidity_sensor"

# Zone 2 — Additional canopy sensor pairs (all optional)
CONF_UPPER_CANOPY_TEMP_SENSOR: str = "upper_canopy_temp_sensor"
CONF_UPPER_CANOPY_HUMIDITY_SENSOR: str = "upper_canopy_humidity_sensor"
CONF_MID_CANOPY_TEMP_SENSOR: str = "mid_canopy_temp_sensor"
CONF_MID_CANOPY_HUMIDITY_SENSOR: str = "mid_canopy_humidity_sensor"
CONF_LOWER_CANOPY_TEMP_SENSOR: str = "lower_canopy_temp_sensor"
CONF_LOWER_CANOPY_HUMIDITY_SENSOR: str = "lower_canopy_humidity_sensor"

# Independent sensor/fan layer toggles — sensor placement and fan placement
# are separate hardware decisions and must never be assumed to move
# together. Upper canopy has no toggle for either — it's the mandatory
# primary layer for both. All default True so existing installs see no
# change on upgrade.
CONF_MID_CANOPY_SENSOR_ENABLED: str = "mid_canopy_sensor_enabled"
CONF_LOWER_CANOPY_SENSOR_ENABLED: str = "lower_canopy_sensor_enabled"
CONF_MID_CANOPY_FAN_ENABLED: str = "mid_canopy_fan_enabled"
CONF_LOWER_CANOPY_FAN_ENABLED: str = "lower_canopy_fan_enabled"

# Optional outdoor weather entity for feedforward MPC. Global — configurable
# and used regardless of topology (Zone 2/Primary Grow Space always exists).
CONF_OUTDOOR_WEATHER_ENTITY: str = "outdoor_weather_entity"

# Optional local weather station entity — a ground-truth override for
# *current* conditions (temperature/humidity) only. The forecast entity
# above still drives outlook/feedforward regardless of whether this is set;
# same override precedence as a canopy sensor tier (prefer the more direct
# local reading over the broader area forecast entity's "current" reading).
CONF_LOCAL_WEATHER_STATION_ENTITY: str = "local_weather_station_entity"

# Exhaust
CONF_EXHAUST_FAN: str = "exhaust_fan"

# Zone 1 = Conditioning Room (Lung Room). Zone 2 = Primary Grow Space (Tent/Cultivation).
# ── Zone 1 appliances (all Optional → None) ───────────────────────────────────
CONF_ZONE1_HEATER: str = "zone1_heater"
CONF_ZONE1_AC: str = "zone1_ac"
# When True the zone1_ac entity is a reverse-cycle heat pump — drives heat+cool via hvac_mode
CONF_ZONE1_IS_REVERSE_CYCLE: str = "zone1_is_reverse_cycle"
CONF_ZONE1_HUMIDIFIER: str = "zone1_humidifier"
CONF_ZONE1_DEHUMIDIFIER: str = "zone1_dehumidifier"
# Zone 1 secondary / backup heater staged on low outdoor temp — optional
# When is_reverse_cycle=True the main heater entity BECOMES the backup heater
CONF_ZONE1_BACKUP_HEATER: str = "zone1_backup_heater"
# Outside air temperature threshold (°C) below which backup heater may stage on
CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C: str = "zone1_backup_heater_threshold_c"
# Legacy key kept for backward-compat (separate climate entity)
CONF_ZONE1_REVERSE_CYCLE: str = "zone1_reverse_cycle"

# ── Zone 2 appliances (all Optional → None) ───────────────────────────────────
CONF_ZONE2_HEATER: str = "zone2_heater"
CONF_ZONE2_AC: str = "zone2_ac"
# When True the zone2_ac entity is a reverse-cycle heat pump
CONF_ZONE2_IS_REVERSE_CYCLE: str = "zone2_is_reverse_cycle"
CONF_ZONE2_HUMIDIFIER: str = "zone2_humidifier"
CONF_ZONE2_DEHUMIDIFIER: str = "zone2_dehumidifier"
# Legacy key kept for backward-compat
CONF_ZONE2_REVERSE_CYCLE: str = "zone2_reverse_cycle"

# ── Drying Zone hardware mapping (all optional → None) ───────────────────────
CONF_DRYING_TEMP_SENSOR: str = "drying_temp_sensor"
CONF_DRYING_HUMIDITY_SENSOR: str = "drying_humidity_sensor"
CONF_DRYING_EXHAUST_FAN: str = "drying_exhaust_fan"
CONF_DRYING_CIRCULATION_FAN: str = "drying_circulation_fan"
CONF_DRYING_DEHUMIDIFIER: str = "drying_dehumidifier"
CONF_DRYING_AC: str = "drying_ac"
CONF_DRYING_IS_REVERSE_CYCLE: str = "drying_is_reverse_cycle"
CONF_DRYING_HEATER: str = "drying_heater"
CONF_DRYING_LIGHT: str = "drying_light"

# ── Drying zone lock (Phase 8) ────────────────────────────────────────────────
CONF_DRYING_CUSTOM_UNLOCKED: str = "drying_custom_unlocked"
DEFAULT_DRYING_CUSTOM_UNLOCKED: bool = False

# Fixed cure-profile values used when drying zone is locked
DRYING_LOCKED_TEMP_C: float = 15.5
DRYING_LOCKED_RH_PCT: float = 60.0

# Fan matrix — lists of up to 4 entity IDs or None per slot
CONF_UPPER_FANS: str = "upper_fans"
CONF_MID_FANS: str = "mid_fans"
CONF_LOWER_FANS: str = "lower_fans"
CONF_FAN_CONTROL_MODE: str = "fan_control_mode"
CONF_BREEZE_ENABLED: str = "breeze_enabled"
CONF_BREEZE_VARIANCE: str = "breeze_variance"

# Lighting
CONF_ZONE2_GROW_LIGHT: str = "zone2_grow_light"
CONF_ZONE2_LIGHT_TYPE: str = "zone2_light_type"
CONF_LIGHT_DIMMABLE: str = "light_dimmable"
CONF_SUNRISE_RAMP_MIN: str = "sunrise_ramp_min"
CONF_DLI_SENSOR: str = "dli_sensor"
CONF_GROW_CAMERA: str = "grow_camera"

# Daily automated time-lapse still, captured via CONF_GROW_CAMERA if mapped.
# Value is either the literal "solar_noon" (default — a consistent clock
# time that tracks the actual local solar noon day to day) or a fixed
# "HH:MM" 24-hour local time string.
CONF_TIMELAPSE_CAPTURE_TIME: str = "timelapse_capture_time"
DEFAULT_TIMELAPSE_CAPTURE_TIME: str = "solar_noon"

# Control algorithm & safety parameters
CONF_CONTROL_ALGORITHM: str = "control_algorithm"
CONF_HEATER_CUTOFF_C: str = "heater_cutoff_c"
CONF_THERMAL_RUNAWAY_C: str = "thermal_runaway_c"
CONF_ANTI_SHORT_CYCLE_MIN: str = "anti_short_cycle_min"
CONF_LEAF_TEMP_OFFSET_C: str = "leaf_temp_offset_c"
CONF_EXHAUST_MIN_PCT: str = "exhaust_min_pct"

# Energy
CONF_ELECTRICITY_RATE: str = "electricity_rate"

# Stage management
CONF_PROGRESSION_MODE: str = "progression_mode"
CONF_STAGE_START_DATE: str = "stage_start_date"
CONF_SMOOTH_GLIDES: str = "smooth_glides"
CONF_RECIPE_FILE: str = "recipe_file"

# ── Entity unique ID suffixes ─────────────────────────────────────────────────
SENSOR_UPPER_CANOPY_TEMP: str = "upper_canopy_temp"
SENSOR_UPPER_CANOPY_RH: str = "upper_canopy_rh"
SENSOR_MID_CANOPY_TEMP: str = "mid_canopy_temp"
SENSOR_MID_CANOPY_RH: str = "mid_canopy_rh"
SENSOR_LOWER_CANOPY_TEMP: str = "lower_canopy_temp"
SENSOR_LOWER_CANOPY_RH: str = "lower_canopy_rh"
SENSOR_LUNG_TEMP: str = "lung_temp"
SENSOR_LUNG_RH: str = "lung_rh"
SENSOR_LEAF_VPD: str = "leaf_vpd"
SENSOR_UPPER_ENTHALPY: str = "upper_enthalpy"
SENSOR_LUNG_ENTHALPY: str = "lung_enthalpy"
SENSOR_EXHAUST_SPEED: str = "exhaust_speed"
SENSOR_DLI_TODAY: str = "dli_today"
SENSOR_CYCLE_COST: str = "cycle_cost"
SENSOR_CYCLE_KWH: str = "cycle_kwh"
SENSOR_GROW_STAGE: str = "grow_stage"
SENSOR_STAGE_DAY: str = "stage_day"

SWITCH_SMOOTH_GLIDES: str = "smooth_glides"
SWITCH_BREEZE_UPPER: str = "breeze_upper"
SWITCH_BREEZE_MID: str = "breeze_mid"
SWITCH_BREEZE_LOWER: str = "breeze_lower"
SWITCH_DLI_EXTENSION: str = "dli_extension"

NUMBER_VPD_TARGET: str = "vpd_target"
NUMBER_TEMP_SETPOINT: str = "temp_setpoint"
NUMBER_RH_SETPOINT: str = "rh_setpoint"
NUMBER_HEATER_CUTOFF: str = "heater_cutoff"
NUMBER_THERMAL_RUNAWAY: str = "thermal_runaway"
NUMBER_ANTI_SHORT_CYCLE: str = "anti_short_cycle"
NUMBER_EXHAUST_MIN_PCT: str = "exhaust_min_pct"
NUMBER_LEAF_TEMP_OFFSET: str = "leaf_temp_offset"
NUMBER_UPPER_FAN_SPEED: str = "upper_fan_speed"
NUMBER_MID_FAN_SPEED: str = "mid_fan_speed"
NUMBER_LOWER_FAN_SPEED: str = "lower_fan_speed"
NUMBER_UPPER_FAN_VARIANCE: str = "upper_fan_variance"
NUMBER_MID_FAN_VARIANCE: str = "mid_fan_variance"
NUMBER_LOWER_FAN_VARIANCE: str = "lower_fan_variance"
NUMBER_LIGHT_INTENSITY: str = "light_intensity"
NUMBER_SUNRISE_RAMP_MIN: str = "sunrise_ramp_min"
NUMBER_ELECTRICITY_RATE: str = "electricity_rate"

SELECT_TOPOLOGY: str = "topology"
SELECT_GROW_STAGE: str = "grow_stage"
SELECT_PROGRESSION_MODE: str = "progression_mode"
SELECT_CONTROL_ALGORITHM: str = "control_algorithm"
SELECT_UPPER_FAN_CONTROL: str = "upper_fan_control"
SELECT_MID_FAN_CONTROL: str = "mid_fan_control"
SELECT_LOWER_FAN_CONTROL: str = "lower_fan_control"
SELECT_LIGHT_TYPE: str = "light_type"

# ── Energy / Tariff ───────────────────────────────────────────────────────────
TARIFF_ANYTIME: str = "anytime"
TARIFF_DUAL: str = "dual"
TARIFF_TRIPLE: str = "triple"
TARIFF_OPTIONS: list[str] = [TARIFF_ANYTIME, TARIFF_DUAL, TARIFF_TRIPLE]

CONF_TARIFF_MODE: str = "tariff_mode"
CONF_TARIFF_ANYTIME: str = "tariff_anytime"           # $/kWh — always rate
CONF_TARIFF_PEAK: str = "tariff_peak"                 # $/kWh — peak window
CONF_TARIFF_SHOULDER: str = "tariff_shoulder"         # $/kWh — shoulder window
CONF_TARIFF_OFFPEAK: str = "tariff_offpeak"           # $/kWh — off-peak
CONF_TARIFF_PEAK_START: str = "tariff_peak_start"     # "HH:MM" 24-hour string
CONF_TARIFF_PEAK_END: str = "tariff_peak_end"
CONF_TARIFF_SHOULDER_START: str = "tariff_shoulder_start"
CONF_TARIFF_SHOULDER_END: str = "tariff_shoulder_end"

CONF_HARVEST_VALUE_PER_OZ: str = "harvest_value_per_oz"

# Entity selector value: a notify.* service name (e.g. "notify.mobile_app_iphone")
CONF_NOTIFY_TARGET: str = "notify_target"

DEFAULT_TARIFF_MODE: str = TARIFF_ANYTIME
DEFAULT_TARIFF_ANYTIME: float = 0.28
DEFAULT_TARIFF_PEAK: float = 0.45
DEFAULT_TARIFF_SHOULDER: float = 0.30
DEFAULT_TARIFF_OFFPEAK: float = 0.15
DEFAULT_TARIFF_PEAK_START: str = "07:00"
DEFAULT_TARIFF_PEAK_END: str = "21:00"
DEFAULT_TARIFF_SHOULDER_START: str = "07:00"
DEFAULT_TARIFF_SHOULDER_END: str = "10:00"
DEFAULT_HARVEST_VALUE: float = 300.0

# EM sensor slot keys — expanded in schema, collapsed to list on save
# Pattern identical to upper/mid/lower fan slot keys
CONF_EM_ZONE1_S1: str = "em_zone1_s1"
CONF_EM_ZONE1_S2: str = "em_zone1_s2"
CONF_EM_ZONE1_S3: str = "em_zone1_s3"
CONF_EM_ZONE1_S4: str = "em_zone1_s4"
CONF_EM_ZONE2_S1: str = "em_zone2_s1"
CONF_EM_ZONE2_S2: str = "em_zone2_s2"
CONF_EM_ZONE2_S3: str = "em_zone2_s3"
CONF_EM_ZONE2_S4: str = "em_zone2_s4"
CONF_EM_DRYING_S1: str = "em_drying_s1"
CONF_EM_DRYING_S2: str = "em_drying_s2"
CONF_EM_DRYING_S3: str = "em_drying_s3"
CONF_EM_DRYING_S4: str = "em_drying_s4"
CONF_EM_GLOBAL_S1: str = "em_global_s1"
CONF_EM_GLOBAL_S2: str = "em_global_s2"
CONF_EM_GLOBAL_S3: str = "em_global_s3"
CONF_EM_GLOBAL_S4: str = "em_global_s4"

# Collapsed list keys (stored in options after save)
CONF_EM_ZONE1_SENSORS: str = "em_zone1_sensors"
CONF_EM_ZONE2_SENSORS: str = "em_zone2_sensors"
CONF_EM_DRYING_SENSORS: str = "em_drying_sensors"
CONF_EM_GLOBAL_SENSORS: str = "em_global_sensors"

# ── Water / Nitrogen baseline ─────────────────────────────────────────────────
CONF_WATER_BASELINE_EC: str = "water_baseline_ec"
DEFAULT_WATER_BASELINE_EC: float = 0.0
NITROGEN_WATCH_EC_THRESHOLD: float = 0.1
NITROGEN_WATCH_STAGES: list[str] = [STAGE_EARLY_VEG, STAGE_LATE_VEG]

# ── Light leak detection ──────────────────────────────────────────────────────
CONF_LIGHT_LEAK_PPFD: str = "light_leak_threshold_ppfd"
CONF_LIGHT_LEAK_TRIGGER_MIN: str = "light_leak_trigger_min"
DEFAULT_LIGHT_LEAK_PPFD: float = 1.0
DEFAULT_LIGHT_LEAK_MIN: int = 2

# ── HA Persistent notification IDs ───────────────────────────────────────────
NOTIFICATION_LIGHT_LEAK: str = "helix_light_leak"
NOTIFICATION_BASE_SIEGE: str = "helix_base_siege"

# ── WebSocket command names (frontend → backend) ──────────────────────────────
WS_CMD_JOURNAL_GET: str = "helix_cultivate/journal/get"
WS_CMD_JOURNAL_ADD: str = "helix_cultivate/journal/add_entry"
WS_CMD_JOURNAL_MAINTENANCE: str = "helix_cultivate/journal/mark_maintenance"
WS_CMD_JOURNAL_IPM: str = "helix_cultivate/journal/add_ipm"

# ── Whitelist for ws_update_zone_devices WebSocket command ───────────────────
# Prevents arbitrary key injection into config entry options.
ALL_VALID_ZONE_DEVICE_KEYS: frozenset[str] = frozenset({
    # Zone 2 — Primary Grow Space
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_PRIMARY_HUMIDITY_SENSOR,
    CONF_UPPER_CANOPY_TEMP_SENSOR,
    CONF_UPPER_CANOPY_HUMIDITY_SENSOR,
    CONF_MID_CANOPY_TEMP_SENSOR,
    CONF_MID_CANOPY_HUMIDITY_SENSOR,
    CONF_LOWER_CANOPY_TEMP_SENSOR,
    CONF_LOWER_CANOPY_HUMIDITY_SENSOR,
    CONF_EXHAUST_FAN,
    CONF_ZONE2_HEATER,
    CONF_ZONE2_AC,
    CONF_ZONE2_IS_REVERSE_CYCLE,
    CONF_ZONE2_HUMIDIFIER,
    CONF_ZONE2_DEHUMIDIFIER,
    CONF_ZONE2_GROW_LIGHT,
    CONF_DLI_SENSOR,
    CONF_GROW_CAMERA,
    CONF_OUTDOOR_WEATHER_ENTITY,
    CONF_LOCAL_WEATHER_STATION_ENTITY,
    # Zone 1 — Conditioning Room
    CONF_LUNG_TEMP_SENSOR,
    CONF_LUNG_HUMIDITY_SENSOR,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_AC,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE1_HUMIDIFIER,
    CONF_ZONE1_DEHUMIDIFIER,
    CONF_ZONE1_BACKUP_HEATER,
    # Drying Zone
    CONF_DRYING_TEMP_SENSOR,
    CONF_DRYING_HUMIDITY_SENSOR,
    CONF_DRYING_EXHAUST_FAN,
    CONF_DRYING_CIRCULATION_FAN,
    CONF_DRYING_DEHUMIDIFIER,
    CONF_DRYING_AC,
    CONF_DRYING_IS_REVERSE_CYCLE,
    CONF_DRYING_HEATER,
    CONF_DRYING_LIGHT,
})
