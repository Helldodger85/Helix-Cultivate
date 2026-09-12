"""Helix Cultivate — Central DataUpdateCoordinator."""
from __future__ import annotations

import asyncio
import logging
import random
from collections import deque
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.sun import get_astral_event_date
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    BREEZE_INTERVAL_MAX_SEC,
    BREEZE_INTERVAL_MIN_SEC,
    CONF_BREEZE_ENABLED,
    CONF_BREEZE_VARIANCE,
    CONF_DLI_SENSOR,
    CONF_DRYING_CUSTOM_UNLOCKED,
    CONF_DRYING_HUMIDITY_SENSOR,
    CONF_DRYING_TEMP_SENSOR,
    CONF_ELECTRICITY_RATE,
    CONF_EM_ZONE1_S1, CONF_EM_ZONE1_S2, CONF_EM_ZONE1_S3, CONF_EM_ZONE1_S4,
    CONF_EM_ZONE2_S1, CONF_EM_ZONE2_S2, CONF_EM_ZONE2_S3, CONF_EM_ZONE2_S4,
    CONF_EM_DRYING_S1, CONF_EM_DRYING_S2, CONF_EM_DRYING_S3, CONF_EM_DRYING_S4,
    CONF_EM_GLOBAL_S1, CONF_EM_GLOBAL_S2, CONF_EM_GLOBAL_S3, CONF_EM_GLOBAL_S4,
    CONF_EM_ZONE1_ENABLED, CONF_EM_ZONE2_ENABLED, CONF_EM_DRYING_ENABLED,
    DEFAULT_EM_ZONE_ENABLED,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_EXHAUST_FAN,
    CONF_EXHAUST_MIN_PCT,
    CONF_GROW_CAMERA,
    CONF_ZONE2_GROW_LIGHT,
    CONF_ZONE2_LIGHT_TYPE,
    CONF_HARVEST_VALUE_PER_OZ,
    CONF_LEAF_TEMP_OFFSET_C,
    CONF_LOWER_CANOPY_HUMIDITY_SENSOR,
    CONF_LOWER_CANOPY_TEMP_SENSOR,
    CONF_LOWER_FANS,
    CONF_LUNG_HUMIDITY_SENSOR,
    CONF_LUNG_TEMP_SENSOR,
    CONF_MID_CANOPY_HUMIDITY_SENSOR,
    CONF_MID_CANOPY_TEMP_SENSOR,
    CONF_MID_FANS,
    CONF_NOTIFY_TARGET,
    CONF_PRIMARY_HUMIDITY_SENSOR,
    CONF_PRIMARY_TEMP_SENSOR,
    CONF_TOPOLOGY,
    CONF_UPPER_CANOPY_HUMIDITY_SENSOR,
    CONF_UPPER_CANOPY_TEMP_SENSOR,
    CONF_UPPER_FANS,
    CONF_ZONE1_BACKUP_HEATER,
    CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_REVERSE_CYCLE,
    CONF_ZONE2_REVERSE_CYCLE,
    CANOPY_UNIFORMITY_DWELL_MIN,
    CANOPY_UNIFORMITY_RH_DELTA_PCT,
    CANOPY_UNIFORMITY_TEMP_DELTA_C,
    CHRONIC_VPD_DRIFT_DWELL_MIN,
    CONF_LOWER_CANOPY_FAN_ENABLED,
    CONF_LOWER_CANOPY_SENSOR_ENABLED,
    CONF_MID_CANOPY_FAN_ENABLED,
    CONF_MID_CANOPY_SENSOR_ENABLED,
    CONF_TIMELAPSE_CAPTURE_TIME,
    COORDINATOR_UPDATE_INTERVAL,
    CONF_TARIFF_MODE,
    CONF_TARIFF_ANYTIME,
    CONF_TARIFF_PEAK,
    CONF_TARIFF_SHOULDER,
    CONF_TARIFF_OFFPEAK,
    CONF_TARIFF_PEAK_START,
    CONF_TARIFF_PEAK_END,
    CONF_TARIFF_SHOULDER_START,
    CONF_TARIFF_SHOULDER_END,
    TARIFF_ANYTIME,
    TARIFF_TRIPLE,
    DEFAULT_TARIFF_MODE,
    DEFAULT_TARIFF_ANYTIME,
    DEFAULT_TARIFF_PEAK,
    DEFAULT_TARIFF_SHOULDER,
    DEFAULT_TARIFF_OFFPEAK,
    DEFAULT_TARIFF_PEAK_START,
    DEFAULT_TARIFF_PEAK_END,
    DEFAULT_TARIFF_SHOULDER_START,
    DEFAULT_TARIFF_SHOULDER_END,
    DEFAULT_TIMELAPSE_CAPTURE_TIME,
    DEFAULT_EXHAUST_SAFE_FLOOR_PCT,
    DEFAULT_FAN_SPEED_PCT,
    DEFAULT_HARVEST_VALUE,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DEFAULT_SENSOR_DROPOUT_MIN,
    DOMAIN,
    FAN_CONTROL_BANG_BANG,
    FAN_CONTROL_PWM_10STEP,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    NS_CLIMATE,
    NS_ENERGY,
    NS_FERTIGATION,
    NS_LIGHTING,
    OPTIONS_WRITE_DEBOUNCE_SEC,
    SENSOR_MEDIAN_BUFFER_SIZE,
    STAGE_SEQUENCE,
    TOPOLOGY_COORDINATED,
    # ── Lighting & DLI engine (Phase 1.5) ─────────────────────────────────────
    CONF_GROWTH_MODE,
    GROWTH_MODE_AUTOFLOWER,
    GROWTH_MODE_PHOTOPERIOD,
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
    PHOTOPERIOD_VEG_STAGES,
    PHOTOPERIOD_FLOWER_STAGES,
    CONF_RAMP_ENABLED,
    DEFAULT_RAMP_ENABLED,
    CONF_RAMP_PRESET,
    DEFAULT_RAMP_PRESET,
    RAMP_PRESET_CUSTOM,
    RAMP_PRESET_MINUTES,
    LIGHT_HID,
    LIGHT_LED,
    FIXTURE_LEAF_OFFSET_DEFAULTS,
    FIXTURE_EFFICACY_UMOL_PER_J,
    DEFAULT_HID_RESTRIKE_LOCKOUT_MIN,
    CONF_LIGHT_WATTAGE_W,
    DEFAULT_LIGHT_WATTAGE_W,
    CONF_LIGHT_EFFICACY_UMOL_PER_J,
    STAGE_DRYING,
    CONF_SUNRISE_RAMP_MIN,
    DEFAULT_SUNRISE_RAMP_MIN,
    STAGE_LABELS,
    # Supplemental Lighting (independent second light)
    CONF_ZONE2_SUPPLEMENTAL_LIGHT,
    CONF_SUPPLEMENTAL_LIGHT_TYPE,
    CONF_SUPPLEMENTAL_MODE,
    DEFAULT_SUPPLEMENTAL_MODE,
    SUPPLEMENTAL_MODE_SYNCED,
    CONF_SUPPLEMENTAL_TARGET_STAGES,
    CONF_SUPPLEMENTAL_ON_TIME,
    DEFAULT_SUPPLEMENTAL_ON_TIME,
    CONF_SUPPLEMENTAL_DURATION_HOURS,
    DEFAULT_SUPPLEMENTAL_DURATION_HOURS,
    # DLI target alerting
    CONF_DLI_ALERT_THRESHOLD_PCT,
    DEFAULT_DLI_ALERT_THRESHOLD_PCT,
)
from .stage_manager import StageManager

_LOGGER = logging.getLogger(__name__)


def _safe_float(value: Any) -> Optional[float]:
    """Safely cast a state value to float, returning None on failure."""
    if value is None:
        return None
    try:
        fval = float(value)
        if fval != fval:  # NaN check
            return None
        return fval
    except (ValueError, TypeError):
        return None


def _median_of_three(buf: deque) -> Optional[float]:
    """Return the median of up to 3 numeric samples in a deque."""
    values = [v for v in buf if v is not None]
    if not values:
        return None
    sorted_vals = sorted(values)
    return sorted_vals[len(sorted_vals) // 2]


def _parse_hhmm(value: Any, fallback: str) -> dtime:
    """Parse an "HH:MM" string into a time object, falling back to a known-
    good default string on any malformed input rather than raising."""
    for candidate in (value, fallback):
        try:
            hour_str, minute_str = str(candidate).split(":", 1)
            return dtime(int(hour_str), int(minute_str))
        except (ValueError, TypeError, AttributeError):
            continue
    return dtime(6, 0)


def _schedule_window_multiplier(
    now_t: dtime, on_time: dtime, hours: float, ramp_minutes: float
) -> float:
    """Pure on/ramp/off window math: 0-100, how far through the window "now"
    is. Standalone function (not a method on HelixCoordinator) specifically
    so Supplemental Lighting's independent Targeted-mode schedule can reuse
    the exact same midnight-safe math as the main light's
    _light_schedule_multiplier without that already-working method being
    touched at all — see HelixCoordinator._supplemental_targeted_pct.
    """
    if hours <= 0:
        return 0.0
    if hours >= 24:
        return 100.0
    on_minutes = on_time.hour * 60 + on_time.minute
    now_minutes = now_t.hour * 60 + now_t.minute
    elapsed = (now_minutes - on_minutes) % (24 * 60)
    duration = hours * 60.0
    if elapsed >= duration:
        return 0.0
    if ramp_minutes > 0:
        if elapsed < ramp_minutes:
            return round(100.0 * elapsed / ramp_minutes, 1)
        remaining = duration - elapsed
        if remaining < ramp_minutes:
            return round(100.0 * remaining / ramp_minutes, 1)
    return 100.0


class HelixCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinates all Helix Cultivate data, control decisions, and async tasks."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=COORDINATOR_UPDATE_INTERVAL,
        )
        self._entry = entry
        self._config: dict[str, Any] = {**entry.data, **entry.options}

        # ── Debounced config-entry option writes ──────────────────────────────
        # Persistent number/select setters queue writes here instead of calling
        # async_update_entry directly, so dragging several sliders in one
        # Settings session coalesces into a single write (and single reload).
        self._pending_options: dict[str, Any] = {}
        self._options_write_unsub: Optional[Any] = None

        # ── Rolling median buffers keyed by entity_id ─────────────────────────
        self._median_buffers: dict[str, deque] = {}

        # ── Breeze tasks per tier ─────────────────────────────────────────────
        self._breeze_tasks: dict[str, asyncio.Task] = {}

        # ── Fan speed state per tier (0–100) ──────────────────────────────────
        self._fan_speeds: dict[str, float] = {
            FAN_TIER_UPPER: float(DEFAULT_FAN_SPEED_PCT),
            FAN_TIER_MID: float(DEFAULT_FAN_SPEED_PCT),
            FAN_TIER_LOWER: float(DEFAULT_FAN_SPEED_PCT),
        }

        # ── Anti-short-cycle compressor timers ────────────────────────────────
        self._last_compressor_off: dict[str, Optional[datetime]] = {}

        # ── Last seen primary temperature sensor timestamp ────────────────────
        self._primary_last_seen: Optional[datetime] = None

        # ── Lights-off purge tracking ─────────────────────────────────────────
        self._lights_off_purge_until: Optional[datetime] = None
        # Previous-tick lights-on state, used by ClimateEngine._control_exhaust()
        # to detect the on->off transition that starts the dehumidification
        # purge window. Distinct from the time-lapse snapshot's own date-based
        # tracking (_last_snapshot_date) — do not conflate the two again.
        self._lights_state_prev: Optional[bool] = None

        # ── Energy session start ──────────────────────────────────────────────
        self._session_start: datetime = dt_util.utcnow()
        # self._cycle_kwh/_cycle_cost are the aggregated totals actually
        # displayed (Global's 2 summary cards) — sum of every currently-
        # enabled zone's own accumulator below, plus Global's own direct EM
        # slots, recomputed each tick in _accumulate_energy(). The per-zone
        # accumulators keep counting even while a zone is disabled, so
        # re-enabling it resumes with its true accumulated total rather than
        # a gap — only the aggregate's *inclusion* of it is gated.
        self._cycle_kwh: float = 0.0
        self._cycle_cost: float = 0.0
        self._zone1_cycle_kwh: float = 0.0
        self._zone2_cycle_kwh: float = 0.0
        self._drying_cycle_kwh: float = 0.0
        self._global_cycle_kwh: float = 0.0
        self._zone1_cycle_cost: float = 0.0
        self._zone2_cycle_cost: float = 0.0
        self._drying_cycle_cost: float = 0.0
        self._global_cycle_cost: float = 0.0
        self._last_energy_tick: Optional[datetime] = None

        # ── VPD trend history (timestamp, vpd) tuples — 6 × 30s = 3min window ──
        self._vpd_history: deque = deque(maxlen=6)

        # ── Temperature trend history (timestamp, temp_c) tuples — same window ─
        self._temp_history: deque = deque(maxlen=6)

        # ── Saturation tracking: zone label → datetime when appliance last
        #    turned ON continuously (Phase 9) ────────────────────────────────
        self._dehumid_on_since: dict[str, Optional[datetime]] = {
            "zone1": None, "zone2": None, "drying": None,
        }
        self._humid_on_since: dict[str, Optional[datetime]] = {
            "zone1": None, "zone2": None, "drying": None,
        }

        # ── Appliance dropout watchdog (Phase 10B) ────────────────────────────
        # Keys are role strings: "zone1_heater", "zone1_dehumid", etc.
        self._appliance_unavail_since: dict[str, Optional[datetime]] = {}

        # ── Stage manager ─────────────────────────────────────────────────────
        self.stage_manager = StageManager(hass, self._config)
        self.stage_manager.set_coordinator_ref(self)

        # ── Time-lapse snapshot tracking ────────────────────────────────────────
        # Tracks the calendar date (not a rolling timestamp) so the daily
        # capture lands on the configured clock time exactly once per day
        # regardless of coordinator restarts.
        self._last_snapshot_date: Optional[date] = None

        # ── Runtime setpoints (overridden by number entities) ─────────────────
        self.vpd_target: float = 1.0
        self.vpd_target_min: float = 0.8
        self.vpd_target_max: float = 1.2
        self.temp_setpoint: float = 24.0
        self.rh_setpoint: float = 65.0
        self.light_intensity_pct: float = 100.0
        self.smooth_glides_enabled: bool = bool(self._config.get("smooth_glides", True))
        self.dli_extension_enabled: bool = False
        self.breeze_upper_enabled: bool = bool(self._config.get(CONF_BREEZE_ENABLED, False))
        self.breeze_mid_enabled: bool = bool(self._config.get(CONF_BREEZE_ENABLED, False))
        self.breeze_lower_enabled: bool = bool(self._config.get(CONF_BREEZE_ENABLED, False))
        # ── Manual override flags (set by number entities, cleared on stage advance) ──
        self.temp_setpoint_manual_override: bool = False
        self.vpd_target_manual_override: bool = False
        self.rh_setpoint_manual_override: bool = False

        # ── Light schedule engine (Phase 1.5) ───────────────────────────────────
        # Actual last-applied grow-light brightness (0-100), distinct from
        # light_intensity_pct (the stage's configured ceiling when fully on)
        # — this is ceiling × the schedule's on/ramp/off multiplier, used by
        # the DLI estimation fallback so ramp windows integrate against real
        # applied brightness rather than a binary on/off assumption.
        self._light_applied_pct: float = 0.0
        # Continuous off-duration tracking for the HID/ballast hot-restrike
        # lockout — set the moment the entity is observed off (by us or
        # anyone else), cleared the moment it's observed on. Reused
        # anti-short-cycle-style dwell timer, see _apply_grow_light_schedule.
        self._light_off_since: Optional[datetime] = None
        self._hid_restrike_delay_logged: bool = False

        # ── Supplemental Lighting (independent second light) ───────────────────
        self._supplemental_applied_pct: float = 0.0
        self._supplemental_light_off_since: Optional[datetime] = None
        self._supplemental_hid_restrike_delay_logged: bool = False

        # ── Zone 2 drying-stage airflow strategy (Part 2) ───────────────────────
        # Dwell timer for the hard humidity-ceiling override (2.A4).
        self._drying_humidity_high_since: Optional[datetime] = None
        self._drying_humidity_override_alerted: bool = False
        # Cyclic-mode on/off phase tracking (2.A5) — exhaust and circulation
        # alternate together on this single timer.
        self._drying_cycle_phase_since: Optional[datetime] = None
        self._drying_cycle_is_on: bool = True
        # Exposed for the dashboard (2.B2).
        self._drying_airflow_applied_pct: float = 0.0
        self._drying_humidity_override_active: bool = False

    # ── Config helpers ────────────────────────────────────────────────────────

    def _get(self, key: str, default: Any = None) -> Any:
        """Retrieve a config value from the merged entry config."""
        return self._config.get(key, default)

    # ── Sensor median buffer ──────────────────────────────────────────────────

    def _read_sensor(self, entity_id: Optional[str]) -> Optional[float]:
        """Read a sensor state value through the rolling median filter."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        raw = _safe_float(state.state)
        if raw is None:
            return None
        buf = self._median_buffers.setdefault(
            entity_id, deque(maxlen=SENSOR_MEDIAN_BUFFER_SIZE)
        )
        buf.append(raw)
        return _median_of_three(buf)

    # ── Primary sensor dropout watchdog ──────────────────────────────────────

    def _check_sensor_dropout(self) -> bool:
        """Return True if the primary temperature sensor has been stale > dropout threshold."""
        primary_temp_id: Optional[str] = self._get(CONF_PRIMARY_TEMP_SENSOR)
        if not primary_temp_id:
            return True
        state = self.hass.states.get(primary_temp_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            if self._primary_last_seen is None:
                return True
            stale_secs = (dt_util.utcnow() - self._primary_last_seen).total_seconds()
            return stale_secs > DEFAULT_SENSOR_DROPOUT_MIN * 60
        self._primary_last_seen = dt_util.utcnow()
        return False

    # ── Repairs / issue_registry health checks (Phase 12B) ────────────────────

    def _check_repairs_issues(
        self, lung_temp: Optional[float], lung_rh: Optional[float]
    ) -> None:
        """Evaluate the four Repairs conditions and create/clear issues.

        Called once per coordinator tick. `ir.async_create_issue` is
        idempotent — repeated calls with the same issue_id update rather than
        duplicate. Issues are cleared as soon as their triggering condition
        no longer holds.
        """
        # ── 1. Conditioning room enabled but no lung sensors ──────────────────
        cond_enabled = self._get(CONF_ENABLE_CONDITIONING_ROOM)
        if cond_enabled is None:
            cond_enabled = self._get(CONF_TOPOLOGY, TOPOLOGY_COORDINATED) == TOPOLOGY_COORDINATED
        issue_id = "conditioning_room_no_lung_sensors"
        if bool(cond_enabled) and lung_temp is None and lung_rh is None:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=issue_id,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        # ── 2. Any stage's day_vpd_max implausible ────────────────────────────
        issue_id = "vpd_range_implausible"
        implausible = False
        for stage in STAGE_SEQUENCE:
            profile = self.stage_manager._profile(stage)
            vpd_min = profile.get("day_vpd_min")
            vpd_max = profile.get("day_vpd_max")
            if vpd_min is None or vpd_max is None:
                continue
            if vpd_max < vpd_min or vpd_max > 4.0:
                implausible = True
                break
        if implausible:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        # ── 3. Backup heater threshold set but no heater entity ───────────────
        issue_id = "backup_heater_no_entity"
        threshold = float(
            self._get(CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C, 0.0) or 0.0
        )
        heater_entity = self._get(CONF_ZONE1_BACKUP_HEATER) or self._get(CONF_ZONE1_HEATER)
        if threshold > 0 and not heater_entity:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        # ── 4. Drying zone unlocked but no temp/RH sensor ─────────────────────
        issue_id = "drying_unlocked_no_sensor"
        drying_unlocked = bool(self._get(CONF_DRYING_CUSTOM_UNLOCKED, False))
        drying_temp_id = self._get(CONF_DRYING_TEMP_SENSOR)
        drying_rh_id = self._get(CONF_DRYING_HUMIDITY_SENSOR)
        if drying_unlocked and (not drying_temp_id or not drying_rh_id):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=issue_id,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

        # ── 5. Primary sensor never configured (first-run) ────────────────────
        # A brand-new config entry completes onboarding without any hardware
        # mapped (deferred to the options flow), which otherwise looks
        # identical to a genuine sensor dropout — see _async_update_data,
        # which uses this same condition to suppress the critical alert for
        # this specific case and raise this quiet Repairs issue instead.
        issue_id = "primary_sensor_not_configured"
        if not self._get(CONF_PRIMARY_TEMP_SENSOR):
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=issue_id,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)

    # ── Enthalpy calculation ──────────────────────────────────────────────────

    @staticmethod
    def _calc_enthalpy(temp_c: float, rh_pct: float) -> float:
        """Calculate specific enthalpy of moist air [kJ/kg dry air]."""
        import math
        svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
        p_atm = 101.325  # kPa
        rh_frac = max(0.0, min(1.0, rh_pct / 100.0))
        actual_vp = rh_frac * svp
        denom = p_atm - actual_vp
        if denom <= 0:
            denom = 0.001
        humidity_ratio = 0.622 * actual_vp / denom
        enthalpy = 1.006 * temp_c + humidity_ratio * (2501.0 + 1.86 * temp_c)
        return enthalpy

    # ── Fixture-aware leaf temperature offset ─────────────────────────────────

    def effective_leaf_temp_offset_c(self) -> float:
        """Return the leaf-temperature offset actually in effect.

        A manually-persisted CONF_LEAF_TEMP_OFFSET_C (the user has touched
        the number.helix_cultivate_leaf_temp_offset slider at least once, for
        someone with a real leaf-clip sensor) always wins outright. Otherwise
        derive a sensible default from the mapped fixture type
        (zone2_light_type) — HID/ballast runs much hotter than modern LED, so
        one global default doesn't fit every fixture. Falls back to the
        historical flat default when no fixture type is set either.
        """
        if CONF_LEAF_TEMP_OFFSET_C in self._entry.options:
            return float(self._entry.options[CONF_LEAF_TEMP_OFFSET_C])
        light_type = self._get(CONF_ZONE2_LIGHT_TYPE)
        return float(
            FIXTURE_LEAF_OFFSET_DEFAULTS.get(light_type, DEFAULT_LEAF_TEMP_OFFSET_C)
        )

    # ── Leaf VPD calculation ──────────────────────────────────────────────────

    def _calc_leaf_vpd(self, temp_c: float, rh_pct: float) -> float:
        """Calculate Leaf VPD [kPa] using the effective leaf temperature offset."""
        import math
        offset = self.effective_leaf_temp_offset_c()
        t_leaf = temp_c + offset
        svp_leaf = 0.6108 * math.exp(17.27 * t_leaf / (t_leaf + 237.3))
        svp_air = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
        rh_frac = max(0.0, min(1.0, rh_pct / 100.0))
        vpd = svp_leaf - (rh_frac * svp_air)
        return max(0.0, vpd)

    # ── Lights state detection ────────────────────────────────────────────────

    def _lights_on(self) -> bool:
        """Return True if grow light entity is currently on."""
        light_id: Optional[str] = self._get(CONF_ZONE2_GROW_LIGHT)
        if not light_id:
            return False
        state = self.hass.states.get(light_id)
        return state is not None and state.state in ("on",)

    # ── Light schedule engine (Phase 1.5) ─────────────────────────────────────
    #
    # Helix Cultivate is the sole authority for the grow-light schedule.
    # Every method here is a pure function of (growth mode, current stage,
    # configured hours/on-time/ramp) — nothing here ever depends on whether a
    # DLI sensor is mapped, by design (B7: DLI presence must never gate
    # scheduling, growth mode, ramp, or lockout).

    def _light_schedule_params(self) -> tuple[float, dtime, str]:
        """Return (hours, on_time, schedule_key) for the schedule that
        applies RIGHT NOW, based on growth mode and the current stage.

        Recomputed fresh every call — a stage transition (auto-advance or
        manual) is reflected on the very next call with no interpolation,
        which is what makes the Veg->Flower transition a single instant
        switch rather than a gradual ramp (see _light_schedule_multiplier).
        """
        # Drying is a fixed dark period regardless of growth mode — it's a
        # post-harvest curing stage, not a live-plant photoperiod response,
        # so it overrides autoflower's constant schedule too. Checked before
        # branching on growth mode so this can never be shadowed by it.
        stage = self.stage_manager.current_stage
        if stage == STAGE_DRYING:
            return 0.0, dtime(0, 0), "drying"

        mode = self._get(CONF_GROWTH_MODE, DEFAULT_GROWTH_MODE)

        if mode == GROWTH_MODE_AUTOFLOWER:
            hours = float(self._get(CONF_AF_LIGHT_HOURS, DEFAULT_AF_LIGHT_HOURS))
            on_time = _parse_hhmm(
                self._get(CONF_AF_LIGHTS_ON_TIME, DEFAULT_AF_LIGHTS_ON_TIME),
                DEFAULT_AF_LIGHTS_ON_TIME,
            )
            return hours, on_time, "af"

        if stage in PHOTOPERIOD_FLOWER_STAGES:
            hours = float(self._get(CONF_PP_FLOWER_HOURS, DEFAULT_PP_FLOWER_HOURS))
            on_time = _parse_hhmm(
                self._get(CONF_PP_FLOWER_LIGHTS_ON_TIME, DEFAULT_PP_FLOWER_LIGHTS_ON_TIME),
                DEFAULT_PP_FLOWER_LIGHTS_ON_TIME,
            )
            return hours, on_time, "pp_flower"

        # PHOTOPERIOD_VEG_STAGES, or any future stage not yet categorised —
        # veg is the safer default (longer photoperiod, not flower-triggering).
        hours = float(self._get(CONF_PP_VEG_HOURS, DEFAULT_PP_VEG_HOURS))
        on_time = _parse_hhmm(
            self._get(CONF_PP_VEG_LIGHTS_ON_TIME, DEFAULT_PP_VEG_LIGHTS_ON_TIME),
            DEFAULT_PP_VEG_LIGHTS_ON_TIME,
        )
        return hours, on_time, "pp_veg"

    def _effective_ramp_minutes(self, light_id: Optional[str]) -> float:
        """Return the sunrise/sunset ramp duration in minutes, or 0.0 if the
        ramp is disabled or the mapped entity can't dim (switch domain)."""
        if not bool(self._get(CONF_RAMP_ENABLED, DEFAULT_RAMP_ENABLED)):
            return 0.0
        domain = light_id.split(".")[0] if light_id else ""
        if domain != "light":
            return 0.0  # switch-domain fixtures can't dim — auto-disabled
        preset = self._get(CONF_RAMP_PRESET, DEFAULT_RAMP_PRESET)
        if preset == RAMP_PRESET_CUSTOM:
            return float(self._get(CONF_SUNRISE_RAMP_MIN, DEFAULT_SUNRISE_RAMP_MIN))
        return RAMP_PRESET_MINUTES.get(
            preset, RAMP_PRESET_MINUTES[DEFAULT_RAMP_PRESET]
        )

    def _light_schedule_multiplier(self, light_id: Optional[str]) -> float:
        """Return 0-100: how far through the on/ramp/off window "now" is.

        100 = fully on, 0 = off (including the entire Drying stage — zero
        hours, always 0). In between during a sunrise/sunset ramp window.
        Multiplies against light_intensity_pct (the stage's brightness
        ceiling) to get the actually-applied brightness.
        """
        hours, on_time, _ = self._light_schedule_params()
        if hours <= 0:
            return 0.0
        if hours >= 24:
            return 100.0

        now_t = dt_util.now().time()
        on_minutes = on_time.hour * 60 + on_time.minute
        now_minutes = now_t.hour * 60 + now_t.minute
        # Minutes elapsed since on_time, correctly wrapping past midnight —
        # unlike the tariff windows' known limitation, a light schedule
        # commonly does cross midnight depending on the chosen on-time.
        elapsed = (now_minutes - on_minutes) % (24 * 60)
        duration = hours * 60.0
        if elapsed >= duration:
            return 0.0

        ramp_minutes = self._effective_ramp_minutes(light_id)
        if ramp_minutes > 0:
            if elapsed < ramp_minutes:
                return round(100.0 * elapsed / ramp_minutes, 1)
            remaining = duration - elapsed
            if remaining < ramp_minutes:
                return round(100.0 * remaining / ramp_minutes, 1)
        return 100.0

    async def _apply_grow_light_schedule(self, light_id: str, applied_pct: float) -> None:
        """Push a schedule-computed brightness to the grow light entity.

        Single choke point for every grow-light state change this loop
        makes, so the HID/ballast hot-restrike lockout can never be
        bypassed — applies to scheduled transitions and any other caller
        that routes through here alike.
        """
        state = self.hass.states.get(light_id)
        currently_on = state is not None and state.state == "on"

        now = dt_util.utcnow()
        if currently_on:
            self._light_off_since = None
        elif self._light_off_since is None:
            self._light_off_since = now

        wants_on = applied_pct > 0
        is_hid = self._get(CONF_ZONE2_LIGHT_TYPE) == LIGHT_HID

        if is_hid and wants_on and not currently_on and self._light_off_since is not None:
            elapsed_min = (now - self._light_off_since).total_seconds() / 60.0
            if elapsed_min < DEFAULT_HID_RESTRIKE_LOCKOUT_MIN:
                if not self._hid_restrike_delay_logged:
                    _LOGGER.warning(
                        "Helix Cultivate: delaying HID/ballast restrike for %s — "
                        "off for %.1f of %.0f required cool-down minutes. Will "
                        "retry once the lockout clears.",
                        light_id, elapsed_min, DEFAULT_HID_RESTRIKE_LOCKOUT_MIN,
                    )
                    self._hid_restrike_delay_logged = True
                return
        self._hid_restrike_delay_logged = False

        domain = light_id.split(".")[0]
        clamped = max(0.0, min(100.0, applied_pct))
        try:
            if domain == "light":
                if clamped <= 0:
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": light_id}
                    )
                else:
                    brightness = int(round(clamped / 100.0 * 255))
                    await self.hass.services.async_call(
                        "light", "turn_on",
                        {"entity_id": light_id, "brightness": brightness},
                    )
            elif domain == "switch":
                await self.hass.services.async_call(
                    "switch", "turn_on" if clamped >= 50 else "turn_off",
                    {"entity_id": light_id},
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to apply grow light schedule to %s: %s",
                light_id, exc,
            )
            return

        self._light_applied_pct = clamped

    async def _control_light_schedule(self) -> None:
        """Drive the grow-light on/off/ramp schedule for this tick."""
        light_id: Optional[str] = self._get(CONF_ZONE2_GROW_LIGHT)
        if not light_id:
            self._light_applied_pct = 0.0
            return
        multiplier = self._light_schedule_multiplier(light_id)
        applied_pct = round(self.light_intensity_pct * multiplier / 100.0, 1)
        await self._apply_grow_light_schedule(light_id, applied_pct)

    # ── Supplemental Lighting (independent second light) ────────────────────
    #
    # A distinct light from the main grow light — UV, far-red, etc. — with
    # its own entity mapping and its own scheduling mode. Deliberately does
    # NOT feed into _estimate_ppfd()/DLI accumulation anywhere: supplemental
    # fixtures' spectral characteristics don't fit the main-canopy efficacy
    # assumptions, so including them would reduce estimate accuracy, not
    # improve it. This is intentional — do not "fix" it later.

    def _supplemental_targeted_pct(self) -> float:
        """Targeted mode: fully independent schedule, decoupled from the
        main light entirely. Returns 0 (actively held off, not just
        "unmanaged") for any stage outside the configured target list, so a
        manual toggle outside the designated window doesn't silently
        persist uncorrected on the next tick.
        """
        target_stages = self._get(CONF_SUPPLEMENTAL_TARGET_STAGES, []) or []
        if self.stage_manager.current_stage not in target_stages:
            return 0.0

        on_time = _parse_hhmm(
            self._get(CONF_SUPPLEMENTAL_ON_TIME, DEFAULT_SUPPLEMENTAL_ON_TIME),
            DEFAULT_SUPPLEMENTAL_ON_TIME,
        )
        duration_h = float(
            self._get(CONF_SUPPLEMENTAL_DURATION_HOURS, DEFAULT_SUPPLEMENTAL_DURATION_HOURS)
        )
        supplemental_id = self._get(CONF_ZONE2_SUPPLEMENTAL_LIGHT)
        ramp_minutes = self._effective_ramp_minutes(supplemental_id)
        return _schedule_window_multiplier(dt_util.now().time(), on_time, duration_h, ramp_minutes)

    async def _apply_supplemental_light_schedule(self, light_id: str, applied_pct: float) -> None:
        """Push a schedule-computed brightness to the supplemental light
        entity. Structurally identical to _apply_grow_light_schedule (same
        HID hot-restrike lockout pattern) but with entirely separate state
        (_supplemental_light_off_since etc.) — the main and supplemental
        lights are independent physical fixtures that could each be HID or
        not, with independent off-durations, so their lockouts must never
        share state.
        """
        state = self.hass.states.get(light_id)
        currently_on = state is not None and state.state == "on"

        now = dt_util.utcnow()
        if currently_on:
            self._supplemental_light_off_since = None
        elif self._supplemental_light_off_since is None:
            self._supplemental_light_off_since = now

        wants_on = applied_pct > 0
        is_hid = self._get(CONF_SUPPLEMENTAL_LIGHT_TYPE) == LIGHT_HID

        if (
            is_hid and wants_on and not currently_on
            and self._supplemental_light_off_since is not None
        ):
            elapsed_min = (now - self._supplemental_light_off_since).total_seconds() / 60.0
            if elapsed_min < DEFAULT_HID_RESTRIKE_LOCKOUT_MIN:
                if not self._supplemental_hid_restrike_delay_logged:
                    _LOGGER.warning(
                        "Helix Cultivate: delaying supplemental HID/ballast "
                        "restrike for %s — off for %.1f of %.0f required "
                        "cool-down minutes. Will retry once the lockout clears.",
                        light_id, elapsed_min, DEFAULT_HID_RESTRIKE_LOCKOUT_MIN,
                    )
                    self._supplemental_hid_restrike_delay_logged = True
                return
        self._supplemental_hid_restrike_delay_logged = False

        domain = light_id.split(".")[0]
        clamped = max(0.0, min(100.0, applied_pct))
        try:
            if domain == "light":
                if clamped <= 0:
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": light_id}
                    )
                else:
                    brightness = int(round(clamped / 100.0 * 255))
                    await self.hass.services.async_call(
                        "light", "turn_on",
                        {"entity_id": light_id, "brightness": brightness},
                    )
            elif domain == "switch":
                await self.hass.services.async_call(
                    "switch", "turn_on" if clamped >= 50 else "turn_off",
                    {"entity_id": light_id},
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to apply supplemental light schedule "
                "to %s: %s", light_id, exc,
            )
            return

        self._supplemental_applied_pct = clamped

    async def _control_supplemental_light(self) -> None:
        """Drive the supplemental light for this tick — Synced (mirrors the
        main light's schedule via the same, untouched
        _light_schedule_multiplier) or Targeted (its own independent
        stage-gated schedule).
        """
        light_id: Optional[str] = self._get(CONF_ZONE2_SUPPLEMENTAL_LIGHT)
        if not light_id:
            self._supplemental_applied_pct = 0.0
            return

        mode = self._get(CONF_SUPPLEMENTAL_MODE, DEFAULT_SUPPLEMENTAL_MODE)
        if mode == SUPPLEMENTAL_MODE_SYNCED:
            applied_pct = self._light_schedule_multiplier(light_id)
        else:
            applied_pct = self._supplemental_targeted_pct()

        await self._apply_supplemental_light_schedule(light_id, applied_pct)

    # ── DLI target alerting ──────────────────────────────────────────────────

    async def _check_dli_target_and_reset(self) -> None:
        """At the lights-off transition — the end of this photoperiod's "day"
        for DLI purposes, not a calendar midnight, which would incorrectly
        split an overnight-crossing photoperiod's DLI across two days —
        compare the accumulated actual DLI against the active stage's
        target and reset the accumulator for the next cycle.

        The compared value is always the same one the DLI Today sensor
        shows: a real PAR/DLI sensor's reading when mapped, otherwise
        _estimate_ppfd()'s accumulation — never the supplemental light's
        contribution either way (see the Supplemental Lighting section
        above).
        """
        actual_dli = (self.data or {}).get(NS_ENERGY, {}).get("dli_today_mol", 0.0)
        stage = self.stage_manager.current_stage
        target_dli = float(self.stage_manager._profile(stage).get("target_dli_mol", 0.0))

        if target_dli > 0:
            deviation_pct = abs(actual_dli - target_dli) / target_dli * 100.0
            threshold = float(
                self._get(CONF_DLI_ALERT_THRESHOLD_PCT, DEFAULT_DLI_ALERT_THRESHOLD_PCT)
            )
            if deviation_pct > threshold:
                direction = "below" if actual_dli < target_dli else "above"
                self.hass.bus.async_fire(
                    "helix_cultivate_dli_target_alert",
                    {
                        "entry_id": self._entry.entry_id,
                        "stage": stage,
                        "actual_dli_mol": round(actual_dli, 1),
                        "target_dli_mol": target_dli,
                        "deviation_pct": round(deviation_pct, 1),
                    },
                )
                stage_label = STAGE_LABELS.get(stage, stage)
                # Informational/advisory, not safety-critical — level="info"
                # still raises a persistent_notification but skips the
                # mobile push a "critical" level would trigger.
                await self._notify_critical(
                    title="Helix Cultivate — DLI Target",
                    message=(
                        f"Today's DLI was {actual_dli:.1f}/{target_dli:.0f} mol, "
                        f"{deviation_pct:.0f}% {direction} target for {stage_label}."
                    ),
                    level="info",
                )

        if self.data:
            self.data[NS_ENERGY]["dli_today_mol"] = 0.0

    # ── DLI accumulation ─────────────────────────────────────────────────────

    def _estimate_ppfd(self) -> float:
        """Estimate current PPFD [μmol/m²/s] from wattage × efficacy ×
        dimming% ÷ canopy area — the DLI fallback used only when no physical
        PAR/DLI sensor is mapped (see _accumulate_dli). Integrates against
        the actual just-applied brightness (_light_applied_pct), so ramp
        windows contribute proportionally rather than as binary on/off.
        """
        wattage = float(self._get(CONF_LIGHT_WATTAGE_W, DEFAULT_LIGHT_WATTAGE_W))
        if wattage <= 0:
            return 0.0
        light_type = self._get(CONF_ZONE2_LIGHT_TYPE)
        default_efficacy = FIXTURE_EFFICACY_UMOL_PER_J.get(
            light_type, FIXTURE_EFFICACY_UMOL_PER_J[LIGHT_LED]
        )
        efficacy = float(self._get(CONF_LIGHT_EFFICACY_UMOL_PER_J, default_efficacy))
        area_m2 = float(self._get("zone2_width_m", 1.2)) * float(self._get("zone2_depth_m", 1.2))
        if area_m2 <= 0:
            return 0.0
        dimming_frac = max(0.0, min(1.0, self._light_applied_pct / 100.0))
        if dimming_frac <= 0:
            return 0.0
        total_umol_per_s = wattage * efficacy * dimming_frac
        return total_umol_per_s / area_m2

    def _accumulate_dli(self, interval_sec: float) -> None:
        """Accumulate DLI — always prefers a real PAR/DLI sensor when mapped;
        never overrides one with the estimate. Falls back to _estimate_ppfd()
        only when no sensor is mapped, so this feature works identically
        with or without one (B7)."""
        dli_sensor_id: Optional[str] = self._get(CONF_DLI_SENSOR)
        if dli_sensor_id:
            if not self._lights_on():
                return
            ppfd = self._read_sensor(dli_sensor_id)
            if ppfd is None:
                return
        else:
            ppfd = self._estimate_ppfd()
            if ppfd <= 0:
                return
        increment = ppfd * interval_sec / 1_000_000.0
        if self.data:
            self.data[NS_ENERGY]["dli_today_mol"] = (
                self.data[NS_ENERGY].get("dli_today_mol", 0.0) + increment
            )

    # ── Energy accumulation ───────────────────────────────────────────────────

    def _zone_em_watts(self, slot_keys: tuple[str, str, str, str]) -> float:
        """Sum instantaneous watt readings from one zone's 4 EM sensor slots.

        Reads the individual em_*_s1..s4 keys directly (not the collapsed
        em_*_sensors list the Options Flow also writes) — the gear-icon
        hardware-mapping form only ever writes the individual keys via
        update_zone_devices, so reading them directly keeps both entry paths
        (initial Options Flow setup and later gear-icon edits) consistent.
        Returns 0.0 when no sensors are configured or all readings are
        unavailable.
        """
        total = 0.0
        for key in slot_keys:
            entity_id = self._get(key)
            if not entity_id:
                continue
            watts = self._safe_read_watts(entity_id)
            if watts is not None:
                total += watts
        return total

    def _safe_read_watts(self, entity_id: str) -> Optional[float]:
        """Read a raw watt value from an entity state without median filtering
        (energy monitor readings should not be smoothed — instantaneous power
        draw is expected to be spiky and the Riemann sum already integrates
        over time)."""
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            return None
        return _safe_float(state.state)

    def _current_tariff_rate(self) -> float:
        """Resolve the currently-active electricity rate from the tariff config.

        Honours CONF_TARIFF_MODE (anytime / dual / triple) and the configured
        peak/shoulder/off-peak windows. Falls back to the legacy flat
        CONF_ELECTRICITY_RATE when tariff_mode is "anytime" (or unset) so
        existing installs that never touched the Energy step keep working
        exactly as before.

        Note: mirrors the options-flow-documented limitation that
        midnight-crossing windows (e.g. 22:00-06:00) are not yet supported —
        a window where start > end is treated as never active.
        """
        mode = self._get(CONF_TARIFF_MODE, DEFAULT_TARIFF_MODE)
        if mode == TARIFF_ANYTIME:
            return float(
                self._get(
                    CONF_TARIFF_ANYTIME,
                    self._get(CONF_ELECTRICITY_RATE, DEFAULT_TARIFF_ANYTIME),
                )
            )

        def _in_window(start_str: Any, end_str: Any) -> bool:
            try:
                sh, sm = (int(p) for p in str(start_str).split(":"))
                eh, em = (int(p) for p in str(end_str).split(":"))
                start, end = dtime(sh, sm), dtime(eh, em)
            except (ValueError, TypeError, AttributeError):
                return False
            if start > end:
                return False  # midnight-crossing windows not yet supported
            return start <= dt_util.now().time() < end

        if _in_window(
            self._get(CONF_TARIFF_PEAK_START, DEFAULT_TARIFF_PEAK_START),
            self._get(CONF_TARIFF_PEAK_END, DEFAULT_TARIFF_PEAK_END),
        ):
            return float(self._get(CONF_TARIFF_PEAK, DEFAULT_TARIFF_PEAK))

        if mode == TARIFF_TRIPLE and _in_window(
            self._get(CONF_TARIFF_SHOULDER_START, DEFAULT_TARIFF_SHOULDER_START),
            self._get(CONF_TARIFF_SHOULDER_END, DEFAULT_TARIFF_SHOULDER_END),
        ):
            return float(self._get(CONF_TARIFF_SHOULDER, DEFAULT_TARIFF_SHOULDER))

        return float(self._get(CONF_TARIFF_OFFPEAK, DEFAULT_TARIFF_OFFPEAK))

    def _accumulate_energy(self, interval_sec: float) -> None:
        """Accumulate each zone's own cycle kWh/cost via Riemann sum of that
        zone's EM sensor watts at the currently-active tariff rate, then
        recompute the aggregate totals actually displayed (Global's 2
        summary cards) as the sum of every currently-enabled zone's own
        accumulator plus Global's own direct EM slots (2.3) — never double-
        counted, since each zone's watts are read from that zone's own 4
        slots only.

        Cost is accumulated incrementally at each interval's own rate
        (kwh_this_tick * rate_this_tick), not recomputed from scratch as
        total_kwh * current_rate — the latter would retroactively re-price
        every previously-accumulated kWh at whatever rate happens to be
        active *now*, which is only harmless under a flat "anytime" rate and
        silently wrong the moment time-of-use pricing is active.

        On the first tick since coordinator startup (or since a cycle reset),
        `_last_energy_tick` is None — the interval is skipped to avoid an
        artificially large accumulation from an undefined elapsed duration.
        """
        now = dt_util.utcnow()
        rate = self._current_tariff_rate()

        if self._last_energy_tick is not None:
            elapsed_h = (now - self._last_energy_tick).total_seconds() / 3600.0

            zone1_kwh = (self._zone_em_watts(
                (CONF_EM_ZONE1_S1, CONF_EM_ZONE1_S2, CONF_EM_ZONE1_S3, CONF_EM_ZONE1_S4)
            ) * elapsed_h) / 1000.0
            zone2_kwh = (self._zone_em_watts(
                (CONF_EM_ZONE2_S1, CONF_EM_ZONE2_S2, CONF_EM_ZONE2_S3, CONF_EM_ZONE2_S4)
            ) * elapsed_h) / 1000.0
            drying_kwh = (self._zone_em_watts(
                (CONF_EM_DRYING_S1, CONF_EM_DRYING_S2, CONF_EM_DRYING_S3, CONF_EM_DRYING_S4)
            ) * elapsed_h) / 1000.0
            global_kwh = (self._zone_em_watts(
                (CONF_EM_GLOBAL_S1, CONF_EM_GLOBAL_S2, CONF_EM_GLOBAL_S3, CONF_EM_GLOBAL_S4)
            ) * elapsed_h) / 1000.0

            self._zone1_cycle_kwh += zone1_kwh
            self._zone2_cycle_kwh += zone2_kwh
            self._drying_cycle_kwh += drying_kwh
            self._global_cycle_kwh += global_kwh

            self._zone1_cycle_cost += zone1_kwh * rate
            self._zone2_cycle_cost += zone2_kwh * rate
            self._drying_cycle_cost += drying_kwh * rate
            self._global_cycle_cost += global_kwh * rate

        self._last_energy_tick = now

        # Global/Infrastructure has no enable toggle — always included.
        zone1_on = bool(self._get(CONF_EM_ZONE1_ENABLED, DEFAULT_EM_ZONE_ENABLED))
        zone2_on = bool(self._get(CONF_EM_ZONE2_ENABLED, DEFAULT_EM_ZONE_ENABLED))
        drying_on = bool(self._get(CONF_EM_DRYING_ENABLED, DEFAULT_EM_ZONE_ENABLED))

        self._cycle_kwh = (
            (self._zone1_cycle_kwh if zone1_on else 0.0)
            + (self._zone2_cycle_kwh if zone2_on else 0.0)
            + (self._drying_cycle_kwh if drying_on else 0.0)
            + self._global_cycle_kwh
        )
        self._cycle_cost = (
            (self._zone1_cycle_cost if zone1_on else 0.0)
            + (self._zone2_cycle_cost if zone2_on else 0.0)
            + (self._drying_cycle_cost if drying_on else 0.0)
            + self._global_cycle_cost
        )
        if self.data:
            self.data[NS_ENERGY]["cycle_cost_usd"] = self._cycle_cost
            self.data[NS_ENERGY]["cycle_kwh"] = self._cycle_kwh

    async def reset_energy_cycle(self) -> dict[str, Any]:
        """Energy & ROI tab's dedicated Reset button (2.6) — lighter-weight
        than a full harvest close-out: archives the current aggregate totals
        as Previous Cycle (2.7) via the journal store, then zeroes every
        live accumulator (aggregate and per-zone) so the next tick starts
        counting from zero. The archived data is never deleted.
        """
        archived_kwh = self._cycle_kwh
        archived_cost = self._cycle_cost

        record: dict[str, Any] = {
            "cycle_kwh": round(archived_kwh, 3),
            "cycle_cost_usd": round(archived_cost, 2),
        }
        journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
        if journal is not None:
            record = await journal.async_set_previous_cycle_energy(
                self._entry.entry_id, archived_kwh, archived_cost
            )

        self._cycle_kwh = 0.0
        self._cycle_cost = 0.0
        self._zone1_cycle_kwh = 0.0
        self._zone2_cycle_kwh = 0.0
        self._drying_cycle_kwh = 0.0
        self._global_cycle_kwh = 0.0
        self._zone1_cycle_cost = 0.0
        self._zone2_cycle_cost = 0.0
        self._drying_cycle_cost = 0.0
        self._global_cycle_cost = 0.0
        self._last_energy_tick = None
        if self.data:
            self.data[NS_ENERGY]["cycle_kwh"] = 0.0
            self.data[NS_ENERGY]["cycle_cost_usd"] = 0.0

        return record

    # ── Appliance dropout watchdog ─────────────────────────────────────────────

    def _check_appliance_dropout(self, role: str, entity_id: Optional[str]) -> bool:
        """Track continuous unavailability of a role-mapped appliance entity.

        Returns True once the entity has been unavailable for 5+ minutes.
        The critical notification (persistent + mobile push) fires exactly
        once per dropout episode via `_appliance_dropout_alerted[role]` —
        without this guard the notification would re-fire on every ~30s
        coordinator tick for as long as the entity stays unavailable, since
        `persistent_notification.create`'s idempotent notification_id only
        dedupes the notification *entity*, not the mobile-push fan-out.
        Returns False immediately when `entity_id` is None (not configured —
        not a dropout).
        """
        if entity_id is None:
            return False

        state = self.hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            if self._appliance_unavail_since.get(role) is None:
                self._appliance_unavail_since[role] = dt_util.utcnow()
            elapsed = dt_util.utcnow() - self._appliance_unavail_since[role]
            if elapsed >= timedelta(minutes=5):
                if not self._appliance_dropout_alerted.get(role, False):
                    self.hass.async_create_task(
                        self._raise_appliance_dropout_notification(role, entity_id)
                    )
                    self._appliance_dropout_alerted[role] = True
                return True
        else:
            self._appliance_unavail_since[role] = None
            self._appliance_dropout_alerted[role] = False
        return False

    async def _raise_appliance_dropout_notification(self, role: str, entity_id: str) -> None:
        """Raise a critical notification for a dropped-out appliance entity."""
        await self._notify_critical(
            title=f"Helix Cultivate — Appliance Unreachable ({role})",
            message=(
                f"{role} ({entity_id}) has been unavailable for 5+ minutes. "
                "Control loop skipped for this appliance."
            ),
            level="critical",
        )

    # ── Time-lapse camera snapshot ────────────────────────────────────────────

    async def _maybe_trigger_snapshot(self) -> None:
        """Capture one time-lapse still per day at the configured clock time.

        Inactive entirely when no camera is mapped to CONF_GROW_CAMERA — no
        errors, no placeholder. Stills land under config/www/ (auto-allowed
        by HA's camera.snapshot service) and are registered with the journal
        store so close_out_harvest can compile the cycle's stills into a
        time-lapse. See journal_store.py and close_out_harvest().
        """
        camera_id: Optional[str] = self._get(CONF_GROW_CAMERA)
        if not camera_id:
            return

        today_local = dt_util.now().date()
        if self._last_snapshot_date == today_local:
            return

        capture_setting = self._get(CONF_TIMELAPSE_CAPTURE_TIME, DEFAULT_TIMELAPSE_CAPTURE_TIME)
        target_dt: Optional[datetime]
        if capture_setting == DEFAULT_TIMELAPSE_CAPTURE_TIME:
            target_dt = get_astral_event_date(self.hass, "noon")
        else:
            try:
                hour_str, minute_str = str(capture_setting).split(":", 1)
                target_dt = dt_util.now().replace(
                    hour=int(hour_str), minute=int(minute_str), second=0, microsecond=0
                )
            except (ValueError, TypeError):
                target_dt = get_astral_event_date(self.hass, "noon")

        if target_dt is None or dt_util.utcnow() < dt_util.as_utc(target_dt):
            return

        filename = self.hass.config.path(
            "www", "helix_cultivate_timelapse", self._entry.entry_id,
            f"{today_local.isoformat()}.jpg",
        )
        try:
            await self.hass.services.async_call(
                "camera",
                "snapshot",
                {"entity_id": camera_id, "filename": filename},
                blocking=True,
            )
            self._last_snapshot_date = today_local
            journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
            if journal is not None:
                await journal.async_add_timelapse_image(self._entry.entry_id, filename)
            _LOGGER.info("Helix Cultivate: daily time-lapse still captured at %s", filename)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Helix Cultivate: daily time-lapse snapshot failed: %s", exc)

    # ── Independent sensor/fan layer toggles ──────────────────────────────────

    def _is_fan_tier_enabled(self, tier: str) -> bool:
        """Whether the given canopy fan layer is active.

        Upper is always active (mandatory primary layer, no toggle). Mid/
        lower are independently toggleable and default enabled so existing
        installs see no change on upgrade. This is the single choke point
        the fan-control loop (breeze tasks, stratification boost, and any
        direct set_fan_speed call) must respect so a disabled tier never has
        a command sent to it — not just skipped with a null check.
        """
        if tier == FAN_TIER_UPPER:
            return True
        if tier == FAN_TIER_MID:
            return bool(self._get(CONF_MID_CANOPY_FAN_ENABLED, True))
        if tier == FAN_TIER_LOWER:
            return bool(self._get(CONF_LOWER_CANOPY_FAN_ENABLED, True))
        return False

    def _is_sensor_tier_enabled(self, tier: str) -> bool:
        """Whether the given canopy sensor layer is active (independent of
        that tier's fan toggle — a tier can have sensors on with fans off,
        or vice versa)."""
        if tier == FAN_TIER_UPPER:
            return True
        if tier == FAN_TIER_MID:
            return bool(self._get(CONF_MID_CANOPY_SENSOR_ENABLED, True))
        if tier == FAN_TIER_LOWER:
            return bool(self._get(CONF_LOWER_CANOPY_SENSOR_ENABLED, True))
        return False

    # ── Breeze engine ─────────────────────────────────────────────────────────

    def _get_tier_fans(self, tier: str) -> list[str]:
        """Return non-None entity IDs for a given fan tier."""
        key_map = {
            FAN_TIER_UPPER: CONF_UPPER_FANS,
            FAN_TIER_MID: CONF_MID_FANS,
            FAN_TIER_LOWER: CONF_LOWER_FANS,
        }
        raw: list[Optional[str]] = self._get(key_map[tier], []) or []
        return [e for e in raw if e]

    async def _breeze_loop(self, tier: str) -> None:
        """Async breeze loop — modulates fan speed with random variance."""
        _LOGGER.debug("Helix Cultivate: Breeze engine started for tier %s", tier)
        try:
            while True:
                base = self._fan_speeds.get(tier, float(DEFAULT_FAN_SPEED_PCT))
                variance = float(self._get(CONF_BREEZE_VARIANCE, 20))
                delta = random.uniform(-variance, variance)
                target = max(0.0, min(100.0, base + delta))
                await self._apply_fan_speed_to_tier(tier, target)
                interval = random.uniform(BREEZE_INTERVAL_MIN_SEC, BREEZE_INTERVAL_MAX_SEC)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            _LOGGER.debug("Helix Cultivate: Breeze engine cancelled for tier %s", tier)
            raise

    def _start_breeze_task(self, tier: str) -> None:
        """Start or restart the breeze task for a tier."""
        existing = self._breeze_tasks.get(tier)
        if existing is not None and not existing.done():
            existing.cancel()
        task = self.hass.async_create_task(self._breeze_loop(tier))
        self._breeze_tasks[tier] = task

    def _stop_breeze_task(self, tier: str) -> None:
        """Cancel an active breeze task."""
        existing = self._breeze_tasks.get(tier)
        if existing is not None and not existing.done():
            existing.cancel()
        self._breeze_tasks.pop(tier, None)

    # ── Fan speed application ─────────────────────────────────────────────────

    async def _apply_fan_speed_to_tier(self, tier: str, speed_pct: float) -> None:
        """Send a unified speed command to all fans in a tier."""
        if not self._is_fan_tier_enabled(tier):
            return
        fan_ids = self._get_tier_fans(tier)
        if not fan_ids:
            return

        control_mode = self._get("fan_control_mode", "continuous")
        clamped = max(0.0, min(100.0, speed_pct))

        if control_mode == FAN_CONTROL_PWM_10STEP:
            clamped = round(clamped / 10) * 10

        for entity_id in fan_ids:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            domain = entity_id.split(".")[0]
            try:
                if domain == "fan":
                    if control_mode == FAN_CONTROL_BANG_BANG:
                        service = "turn_on" if clamped >= 50 else "turn_off"
                        await self.hass.services.async_call("fan", service, {"entity_id": entity_id})
                    else:
                        if clamped <= 0:
                            await self.hass.services.async_call("fan", "turn_off", {"entity_id": entity_id})
                        else:
                            await self.hass.services.async_call(
                                "fan", "set_percentage",
                                {"entity_id": entity_id, "percentage": int(clamped)},
                            )
                elif domain == "switch":
                    service = "turn_on" if clamped >= 50 else "turn_off"
                    await self.hass.services.async_call("switch", service, {"entity_id": entity_id})
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Helix Cultivate: failed to set fan %s to %.0f%%: %s",
                    entity_id, clamped, exc,
                )

    # ── Update cycle ──────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch sensor data, run stage manager, invoke climate engine."""
        from .climate_engine import ClimateEngine

        now = dt_util.utcnow()
        sensor_dropout = self._check_sensor_dropout()

        # ── Read all sensors through median filter ─────────────────────────────
        primary_temp = self._read_sensor(self._get(CONF_PRIMARY_TEMP_SENSOR))
        primary_rh = self._read_sensor(self._get(CONF_PRIMARY_HUMIDITY_SENSOR))

        upper_canopy_temp_id: Optional[str] = self._get(CONF_UPPER_CANOPY_TEMP_SENSOR)
        upper_canopy_rh_id: Optional[str] = self._get(CONF_UPPER_CANOPY_HUMIDITY_SENSOR)
        upper_canopy_temp: Optional[float] = (
            self._read_sensor(upper_canopy_temp_id) if upper_canopy_temp_id else primary_temp
        )
        upper_canopy_rh: Optional[float] = (
            self._read_sensor(upper_canopy_rh_id) if upper_canopy_rh_id else primary_rh
        )

        mid_canopy_temp: Optional[float] = self._read_sensor(self._get(CONF_MID_CANOPY_TEMP_SENSOR))
        mid_canopy_rh: Optional[float] = self._read_sensor(self._get(CONF_MID_CANOPY_HUMIDITY_SENSOR))

        lower_canopy_temp: Optional[float] = self._read_sensor(self._get(CONF_LOWER_CANOPY_TEMP_SENSOR))
        lower_canopy_rh: Optional[float] = self._read_sensor(self._get(CONF_LOWER_CANOPY_HUMIDITY_SENSOR))

        lung_temp: Optional[float] = self._read_sensor(self._get(CONF_LUNG_TEMP_SENSOR))
        lung_rh: Optional[float] = self._read_sensor(self._get(CONF_LUNG_HUMIDITY_SENSOR))

        # ── Repairs / issue_registry health checks ──────────────────────────────
        self._check_repairs_issues(lung_temp, lung_rh)

        # ── Calculate derived values ───────────────────────────────────────────
        leaf_vpd: Optional[float] = None
        if upper_canopy_temp is not None and upper_canopy_rh is not None:
            leaf_vpd = self._calc_leaf_vpd(upper_canopy_temp, upper_canopy_rh)

        if leaf_vpd is not None:
            self._vpd_history.append((dt_util.utcnow(), leaf_vpd))

        if upper_canopy_temp is not None:
            self._temp_history.append((dt_util.utcnow(), upper_canopy_temp))

        upper_enthalpy: Optional[float] = None
        if upper_canopy_temp is not None and upper_canopy_rh is not None:
            upper_enthalpy = self._calc_enthalpy(upper_canopy_temp, upper_canopy_rh)

        lung_enthalpy: Optional[float] = None
        if lung_temp is not None and lung_rh is not None:
            lung_enthalpy = self._calc_enthalpy(lung_temp, lung_rh)

        # ── Stage manager tick ─────────────────────────────────────────────────
        self.stage_manager.update_config(self._config)
        self.stage_manager.tick()

        # ── Detect lights on/off (evaluated before smooth glides so day/night
        #    profile selection reflects the current photoperiod state) ────────
        lights_on_now = self._lights_on()
        is_day = lights_on_now

        if self.smooth_glides_enabled:
            vpd_min, vpd_max = self.stage_manager.current_vpd_range(is_day)
            sm_temp = self.stage_manager.current_temp_anchor(is_day)
            if not self.vpd_target_manual_override:
                self.vpd_target_min = vpd_min
                self.vpd_target_max = vpd_max
                self.vpd_target = (vpd_min + vpd_max) / 2.0
            if sm_temp is not None and not self.temp_setpoint_manual_override:
                self.temp_setpoint = sm_temp
            # RH setpoint: derive from midpoint VPD at anchor temp (Tetens formula)
            if not self.rh_setpoint_manual_override:
                import math

                t = sm_temp if sm_temp is not None else self.temp_setpoint
                offset = self.effective_leaf_temp_offset_c()
                svp_leaf = 0.6108 * math.exp(17.27 * (t + offset) / (t + offset + 237.3))
                svp_air = 0.6108 * math.exp(17.27 * t / (t + 237.3))
                mid_vpd = (vpd_min + vpd_max) / 2.0
                rh_frac = max(0.0, min(1.0, (svp_leaf - mid_vpd) / svp_air)) if svp_air else 0.0
                self.rh_setpoint = round(rh_frac * 100.0, 1)

        await self._check_chronic_vpd_drift(leaf_vpd)
        await self._check_canopy_uniformity(
            upper_canopy_temp, upper_canopy_rh,
            mid_canopy_temp, mid_canopy_rh,
            lower_canopy_temp, lower_canopy_rh,
        )

        await self._maybe_trigger_snapshot()

        # ── Light schedule (must run before DLI accumulation — the estimation
        #    fallback below integrates against the brightness this just applied) ──
        await self._control_light_schedule()
        await self._control_supplemental_light()

        # ── Accumulate energy ──────────────────────────────────────────────────
        self._accumulate_dli(COORDINATOR_UPDATE_INTERVAL.total_seconds())
        self._accumulate_energy(COORDINATOR_UPDATE_INTERVAL.total_seconds())

        # ── Sensor dropout guard ──────────────────────────────────────────────
        if sensor_dropout:
            _LOGGER.warning(
                "Helix Cultivate: primary temperature sensor %s is stale/unavailable. "
                "Applying safe floor exhaust (%d%%). VPD control suspended.",
                self._get(CONF_PRIMARY_TEMP_SENSOR),
                DEFAULT_EXHAUST_SAFE_FLOOR_PCT,
            )
            if self._get(CONF_PRIMARY_TEMP_SENSOR):
                # A sensor IS mapped but has gone stale/unavailable — this is a
                # genuine fault, worth a critical alert (fired once per episode).
                if not self._sensor_dropout_alerted:
                    await self._raise_dropout_notification()
                    self._sensor_dropout_alerted = True
            # else: nothing has ever been mapped (fresh, not-yet-configured
            # install) — _check_repairs_issues() already raises a quiet
            # Repairs issue for this; don't also spam a critical push.
        else:
            self._sensor_dropout_alerted = False

        # ── Invoke climate engine ─────────────────────────────────────────────
        climate_state: dict[str, Any] = {}
        try:
            engine = ClimateEngine(self)
            climate_state = await engine.run(
                upper_temp=upper_canopy_temp,
                upper_rh=upper_canopy_rh,
                mid_temp=mid_canopy_temp,
                mid_rh=mid_canopy_rh,
                lower_temp=lower_canopy_temp,
                lower_rh=lower_canopy_rh,
                lung_temp=lung_temp,
                lung_rh=lung_rh,
                leaf_vpd=leaf_vpd,
                upper_enthalpy=upper_enthalpy,
                lung_enthalpy=lung_enthalpy,
                sensor_dropout=sensor_dropout,
                lights_on=lights_on_now,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Helix Cultivate: ClimateEngine.run() failed: %s", exc)

        # ── Manage breeze tasks ────────────────────────────────────────────────
        for tier, enabled_attr in [
            (FAN_TIER_UPPER, "breeze_upper_enabled"),
            (FAN_TIER_MID, "breeze_mid_enabled"),
            (FAN_TIER_LOWER, "breeze_lower_enabled"),
        ]:
            enabled = getattr(self, enabled_attr, False) and self._is_fan_tier_enabled(tier)
            task = self._breeze_tasks.get(tier)
            if enabled and (task is None or task.done()):
                self._start_breeze_task(tier)
            elif not enabled and task is not None and not task.done():
                self._stop_breeze_task(tier)
            if enabled and task is not None and task.done() and not task.cancelled():
                _LOGGER.error(
                    "Helix Cultivate: Breeze task for %s crashed — restarting", tier
                )
                self._start_breeze_task(tier)

        # ── Lights-off day boundary: DLI target alert + reset ───────────────────
        # Must run BEFORE _lights_state_prev is overwritten below — the
        # transition check needs the OLD value (this tick's ClimateEngine.run()
        # above already consumed it for lights-off purge detection).
        if not lights_on_now and self._lights_state_prev is True:
            await self._check_dli_target_and_reset()
        self._lights_state_prev = lights_on_now

        # ── Assemble and return namespaced data ───────────────────────────────
        prev_energy = (self.data or {}).get(NS_ENERGY, {})
        prev_lighting = (self.data or {}).get(NS_LIGHTING, {})

        return {
            NS_CLIMATE: {
                "upper_temp_c": upper_canopy_temp,
                "upper_rh_pct": upper_canopy_rh,
                "mid_temp_c": mid_canopy_temp,
                "mid_rh_pct": mid_canopy_rh,
                "lower_temp_c": lower_canopy_temp,
                "lower_rh_pct": lower_canopy_rh,
                "lung_temp_c": lung_temp,
                "lung_rh_pct": lung_rh,
                "leaf_vpd_kpa": leaf_vpd,
                "upper_enthalpy": upper_enthalpy,
                "lung_enthalpy": lung_enthalpy,
                "exhaust_pct": climate_state.get("exhaust_pct", float(self._get(CONF_EXHAUST_MIN_PCT, 10))),
                "primary_sensor_ok": not sensor_dropout,
                "sensor_dropout": sensor_dropout,
                "lights_on": lights_on_now,
                "vpd_target_min": self.vpd_target_min,
                "vpd_target_max": self.vpd_target_max,
                # Zone 1 appliance states
                "zone1_heater_on": climate_state.get("zone1_heater_on", False),
                "zone1_ac_on": climate_state.get("zone1_ac_on", False),
                "zone1_humid_on": climate_state.get("zone1_humid_on", False),
                "zone1_dehumid_on": climate_state.get("zone1_dehumid_on", False),
                "zone1_reverse_cycle_mode": climate_state.get("zone1_reverse_cycle_mode", None),
                "zone1_backup_heater_on": climate_state.get("zone1_backup_heater_on", False),
                # Zone 2 appliance states
                "zone2_heater_on": climate_state.get("zone2_heater_on", False),
                "zone2_ac_on": climate_state.get("zone2_ac_on", False),
                "zone2_humid_on": climate_state.get("zone2_humid_on", False),
                "zone2_dehumid_on": climate_state.get("zone2_dehumid_on", False),
                "zone2_reverse_cycle_mode": climate_state.get("zone2_reverse_cycle_mode", None),
                # Safety flags
                "thermal_runaway": climate_state.get("thermal_runaway", False),
                "last_update": now,
                # Independent canopy sensor/fan layer toggles
                "mid_canopy_sensor_enabled": self._is_sensor_tier_enabled(FAN_TIER_MID),
                "lower_canopy_sensor_enabled": self._is_sensor_tier_enabled(FAN_TIER_LOWER),
                "mid_canopy_fan_enabled": self._is_fan_tier_enabled(FAN_TIER_MID),
                "lower_canopy_fan_enabled": self._is_fan_tier_enabled(FAN_TIER_LOWER),
                # Canopy uniformity diagnostic
                "canopy_temp_spread_c": self._canopy_temp_spread,
                "canopy_rh_spread_pct": self._canopy_rh_spread,
                "canopy_uniformity_insight": self._canopy_uniformity_insight,
                # Outdoor conditions (local weather station override applied
                # server-side if mapped — see climate_engine._outdoor_temp_c)
                "outdoor_temp_c": climate_state.get("outdoor_temp_c"),
                "outdoor_rh_pct": climate_state.get("outdoor_rh_pct"),
                # Light schedule engine
                "light_applied_pct": self._light_applied_pct,
            },
            NS_LIGHTING: {
                "intensity_pct": self.light_intensity_pct,
                "dli_today_mol": prev_lighting.get("dli_today_mol", 0.0),
                "photoperiod_extended_min": prev_lighting.get("photoperiod_extended_min", 0),
                "phase": "day" if lights_on_now else "night",
                "last_snapshot_date": (
                    self._last_snapshot_date.isoformat() if self._last_snapshot_date else None
                ),
            },
            NS_ENERGY: {
                # Use the authoritative private accumulator — do NOT read back
                # from prev_energy here, which would create a circular no-op
                # that keeps the sensor permanently at zero.
                "cycle_kwh": self._cycle_kwh,
                "cycle_cost_usd": prev_energy.get("cycle_cost_usd", 0.0),
                "dli_today_mol": prev_energy.get("dli_today_mol", prev_lighting.get("dli_today_mol", 0.0)),
                "session_start": self._session_start,
            },
            NS_FERTIGATION: {},  # Phase 2 stub — always present, never raises KeyError
        }

    # ── Dropout persistent notification ──────────────────────────────────────

    async def _raise_dropout_notification(self) -> None:
        """Raise a critical notification when sensor dropout is detected."""
        await self._notify_critical(
            title="Helix Cultivate — Sensor Alert",
            message=(
                "The primary canopy temperature sensor is unavailable or has not updated "
                f"for over {DEFAULT_SENSOR_DROPOUT_MIN} minutes. "
                "Exhaust is running at safe floor. VPD control is suspended."
            ),
            level="critical",
        )

    # ── Chronic VPD drift detection ───────────────────────────────────────────

    async def _check_chronic_vpd_drift(self, leaf_vpd: Optional[float]) -> None:
        """Track sustained (non-instant) VPD drift outside the target band.

        Separate dwell-timer from the instant thermal-runaway/sensor-dropout
        alerts — this fires once per continuous excursion episode that
        outlasts CHRONIC_VPD_DRIFT_DWELL_MIN, for slow drift that never
        actually crosses a hard safety threshold. Reset as soon as VPD
        returns in-range, so a fresh episode can be detected and alerted on
        again later.
        """
        if leaf_vpd is None:
            return

        in_range = self.vpd_target_min <= leaf_vpd <= self.vpd_target_max
        if in_range:
            self._vpd_drift_since = None
            self._chronic_drift_alert_fired = False
            return

        now = dt_util.utcnow()
        if self._vpd_drift_since is None:
            self._vpd_drift_since = now
            return

        if self._chronic_drift_alert_fired:
            return

        elapsed_min = (now - self._vpd_drift_since).total_seconds() / 60.0
        if elapsed_min < CHRONIC_VPD_DRIFT_DWELL_MIN:
            return

        self._chronic_drift_alert_fired = True
        self.hass.bus.async_fire(
            "helix_cultivate_chronic_drift_detected",
            {
                "entry_id": self._entry.entry_id,
                "leaf_vpd_kpa": leaf_vpd,
                "vpd_target_min": self.vpd_target_min,
                "vpd_target_max": self.vpd_target_max,
                "drift_duration_min": round(elapsed_min, 1),
            },
        )
        await self._notify_critical(
            title="Helix Cultivate — Chronic VPD Drift",
            message=(
                f"Leaf VPD has sat outside the {self.vpd_target_min:.2f}–"
                f"{self.vpd_target_max:.2f} kPa target band for over "
                f"{CHRONIC_VPD_DRIFT_DWELL_MIN / 60:.0f} hours (currently "
                f"{leaf_vpd:.2f} kPa). Check for an actuator that isn't "
                "keeping up, not just a momentary spike."
            ),
            level="critical",
        )

    # ── Canopy uniformity diagnostic ──────────────────────────────────────────

    async def _check_canopy_uniformity(
        self,
        upper_temp: Optional[float],
        upper_rh: Optional[float],
        mid_temp: Optional[float],
        mid_rh: Optional[float],
        lower_temp: Optional[float],
        lower_rh: Optional[float],
    ) -> None:
        """Diagnose a top-to-bottom canopy temp/RH gradient.

        Keys off which sensor *layers* are enabled — completely independent
        of fan tier toggle state. Always includes upper; includes mid/lower
        only when their sensor toggle is on AND a reading is present. Skips
        entirely with fewer than 2 active layers (nothing to compare against,
        so a single-layer "spread of zero" would be meaningless).

        Live spread values and a human-readable insight update every tick a
        gradient is present, so the dashboard can show it immediately; the
        helix_cultivate_canopy_uniformity_alert event itself still requires
        the gradient to be sustained for CANOPY_UNIFORMITY_DWELL_MIN (reusing
        the same dwell-timer pattern as saturation/chronic-drift detection),
        to avoid firing on a single noisy reading.
        """
        layers: list[tuple[float, float]] = []
        if upper_temp is not None and upper_rh is not None:
            layers.append((upper_temp, upper_rh))
        if (
            self._is_sensor_tier_enabled(FAN_TIER_MID)
            and mid_temp is not None
            and mid_rh is not None
        ):
            layers.append((mid_temp, mid_rh))
        if (
            self._is_sensor_tier_enabled(FAN_TIER_LOWER)
            and lower_temp is not None
            and lower_rh is not None
        ):
            layers.append((lower_temp, lower_rh))

        if len(layers) < 2:
            self._canopy_temp_spread = None
            self._canopy_rh_spread = None
            self._canopy_uniformity_insight = None
            self._uniformity_drift_since = None
            self._uniformity_alert_fired = False
            return

        temps = [t for t, _ in layers]
        rhs = [r for _, r in layers]
        temp_spread = max(temps) - min(temps)
        rh_spread = max(rhs) - min(rhs)
        self._canopy_temp_spread = round(temp_spread, 1)
        self._canopy_rh_spread = round(rh_spread, 1)

        temp_exceeded = temp_spread > CANOPY_UNIFORMITY_TEMP_DELTA_C
        rh_exceeded = rh_spread > CANOPY_UNIFORMITY_RH_DELTA_PCT
        if not (temp_exceeded or rh_exceeded):
            self._canopy_uniformity_insight = None
            self._uniformity_drift_since = None
            self._uniformity_alert_fired = False
            return

        insight_parts: list[str] = []
        if rh_exceeded:
            insight_parts.append(f"{rh_spread:.0f}% humidity gradient top-to-bottom")
        if temp_exceeded:
            insight_parts.append(f"{temp_spread:.1f}°C temperature gradient top-to-bottom")
        self._canopy_uniformity_insight = (
            " and ".join(insight_parts) + " — check for an airflow dead zone."
        )

        now = dt_util.utcnow()
        if self._uniformity_drift_since is None:
            self._uniformity_drift_since = now
            return

        if self._uniformity_alert_fired:
            return

        elapsed_min = (now - self._uniformity_drift_since).total_seconds() / 60.0
        if elapsed_min < CANOPY_UNIFORMITY_DWELL_MIN:
            return

        self._uniformity_alert_fired = True
        self.hass.bus.async_fire(
            "helix_cultivate_canopy_uniformity_alert",
            {
                "entry_id": self._entry.entry_id,
                "temp_spread_c": self._canopy_temp_spread,
                "rh_spread_pct": self._canopy_rh_spread,
                "insight": self._canopy_uniformity_insight,
                "layers_compared": len(layers),
                "drift_duration_min": round(elapsed_min, 1),
            },
        )
        await self._notify_critical(
            title="Helix Cultivate — Canopy Uniformity",
            message=self._canopy_uniformity_insight,
            level="warning",
        )

    # ── Public setpoint mutators (called by number/select entities) ───────────

    def set_fan_speed(self, tier: str, speed_pct: float) -> None:
        """Update the base fan speed for a tier and apply immediately."""
        self._fan_speeds[tier] = max(0.0, min(100.0, speed_pct))
        if not getattr(self, f"breeze_{tier}_enabled", False):
            self.hass.async_create_task(
                self._apply_fan_speed_to_tier(tier, self._fan_speeds[tier])
            )
        if hasattr(self, "async_update_listeners"):
            self.async_update_listeners()

    def get_fan_speed(self, tier: str) -> float:
        """Return the current base fan speed for a tier."""
        return self._fan_speeds.get(tier, float(DEFAULT_FAN_SPEED_PCT))

    @property
    def cycle_kwh(self) -> float:
        """Public read access to the cycle energy accumulator.

        All internal write sites use self._cycle_kwh directly. External
        consumers (sensor platform, WS harvest response, diagnostics) use this
        property so there is a single authoritative float — no shadow attribute.
        """
        return self._cycle_kwh

    # ── Notifications ─────────────────────────────────────────────────────────

    async def _notify_critical(
        self, title: str, message: str, level: str = "critical"
    ) -> None:
        """Fire a persistent_notification and (if configured + critical) fan out
        to a mobile notify.* target. Centralised so all alert call-sites share
        one idempotent notification_id derivation and one mobile-push policy.
        """
        import re

        slug = re.sub(r"[^a-z0-9_]+", "_", title.lower()).strip("_")[:40]
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": message,
                    "notification_id": f"helix_{slug}",
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Helix Cultivate: failed to raise persistent_notification")

        if level == "info":
            return

        notify_target = self._get(CONF_NOTIFY_TARGET, "")
        if notify_target:
            service = notify_target.replace("notify.", "", 1)
            try:
                await self.hass.services.async_call(
                    "notify",
                    service,
                    {"title": title, "message": message},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Helix Cultivate: failed to fan out notification to %s", notify_target
                )

    # ── Harvest close-out ───────────────────────────────────────────────────────

    def _vpd_in_range_pct(self) -> float:
        """Return the percentage of samples in `_vpd_history` that fell within
        the current vpd_target_min/max band. Returns 0.0 if the deque is empty.
        """
        if not self._vpd_history:
            return 0.0
        in_range = sum(
            1
            for _, vpd_kpa in self._vpd_history
            if self.vpd_target_min <= vpd_kpa <= self.vpd_target_max
        )
        return round((in_range / len(self._vpd_history)) * 100.0, 1)

    async def close_out_harvest(self, wet_weight_g: float, dry_weight_g: float) -> dict[str, Any]:
        """Archive the completed grow cycle, reset all cycle counters and the
        stage machine, and return the full harvest record (including the
        newly-assigned record_id) for the frontend Harvest Report.

        Raises ValueError on schema violation (propagated from journal_store).
        """
        harvest_value_oz = float(self._get(CONF_HARVEST_VALUE_PER_OZ, DEFAULT_HARVEST_VALUE))
        dry_oz = dry_weight_g / 28.3495 if dry_weight_g else 0.0
        revenue = dry_oz * harvest_value_oz
        cost = (self.data or {}).get(NS_ENERGY, {}).get("cycle_cost_usd", self._cycle_cost)
        dollar_per_g = (cost / dry_weight_g) if dry_weight_g > 0 else 0.0

        journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
        if journal is None:
            raise ValueError("Journal store is not initialised — cannot archive harvest")

        # ── Compile this cycle's time-lapse stills into a GIF, if any ──────────
        # Inactive entirely when no camera was ever mapped — the popped list
        # is simply empty, so this is a no-op with no error and no
        # placeholder in the harvest record.
        timelapse_gif_url: Optional[str] = None
        timelapse_stills = await journal.async_pop_timelapse_images(self._entry.entry_id)
        if timelapse_stills:
            rel_dir = f"helix_cultivate_timelapse/{self._entry.entry_id}"
            gif_filename = f"timelapse_{dt_util.utcnow().strftime('%Y%m%dT%H%M%S')}.gif"
            gif_abs_path = self.hass.config.path("www", rel_dir, gif_filename)
            compiled = await journal.async_compile_timelapse_gif(
                [rec["path"] for rec in timelapse_stills], gif_abs_path
            )
            if compiled:
                timelapse_gif_url = f"/local/{rel_dir}/{gif_filename}"

        harvest_data: dict[str, Any] = {
            "wet_weight_g": wet_weight_g,
            "dry_weight_g": dry_weight_g,
            "cycle_kwh": self._cycle_kwh,
            "cycle_cost_usd": cost,
            "stage_durations": self.stage_manager.actual_stage_durations(),
            "vpd_in_range_pct": self._vpd_in_range_pct(),
            "dollar_per_g": round(dollar_per_g, 4),
            "revenue_usd": round(revenue, 2),
            "archived_at": dt_util.utcnow().isoformat(),
            "timelapse_gif_url": timelapse_gif_url,
        }

        record_id = await journal.archive_cycle(harvest_data)

        # Let users build their own automations against harvest completion
        # without going through Helix Cultivate's own notification system.
        # See docs/events.md.
        self.hass.bus.async_fire(
            "helix_cultivate_harvest_complete",
            {
                "entry_id": self._entry.entry_id,
                "dry_weight_g": dry_weight_g,
                "cycle_cost_usd": cost,
                "dollars_per_gram": round(dollar_per_g, 4),
            },
        )

        # Archive this cycle's energy totals as Previous Cycle (2.7) — a full
        # harvest close-out counts as "the last reset" for that display, same
        # as the dedicated Reset button.
        await journal.async_set_previous_cycle_energy(self._entry.entry_id, self._cycle_kwh, cost)

        # Reset cycle counters. _cycle_cost must be reset explicitly here too
        # (not just _cycle_kwh) — _accumulate_energy() now accumulates cost
        # incrementally rather than recomputing it from _cycle_kwh each tick,
        # so it no longer self-corrects to 0 just because _cycle_kwh did.
        self._cycle_kwh = 0.0
        self._cycle_cost = 0.0
        self._zone1_cycle_kwh = 0.0
        self._zone2_cycle_kwh = 0.0
        self._drying_cycle_kwh = 0.0
        self._global_cycle_kwh = 0.0
        self._zone1_cycle_cost = 0.0
        self._zone2_cycle_cost = 0.0
        self._drying_cycle_cost = 0.0
        self._global_cycle_cost = 0.0
        self._last_energy_tick = None
        if self.data:
            self.data[NS_ENERGY]["dli_today_mol"] = 0.0
            self.data[NS_ENERGY]["cycle_kwh"] = 0.0
            self.data[NS_ENERGY]["cycle_cost_usd"] = 0.0

        # Reset stage machine
        self.stage_manager.reset_cycle()

        await self._notify_critical(
            title="Helix Cultivate — Harvest Archived",
            message=(
                f"Cycle archived as {record_id}. {dry_weight_g:.1f}g dry at "
                f"${dollar_per_g:.2f}/g."
            ),
            level="info",
        )

        return {**harvest_data, "record_id": record_id}

    # ── Debounced option persistence ────────────────────────────────────────────

    @callback
    def queue_option_write(self, key: str, value: Any) -> None:
        """Queue a config-entry option write, debounced to avoid reload storms.

        Number/select persistent setters call this instead of writing to the
        config entry directly. Rapid successive calls (e.g. dragging several
        sliders in one Settings session) coalesce into a single
        async_update_entry call — and therefore a single reload — fired after
        OPTIONS_WRITE_DEBOUNCE_SEC of inactivity.
        """
        self._pending_options[key] = value
        if self._options_write_unsub is not None:
            self._options_write_unsub()
        self._options_write_unsub = async_call_later(
            self.hass, OPTIONS_WRITE_DEBOUNCE_SEC, self._flush_pending_options
        )

    @callback
    def _flush_pending_options(self, _now: Any = None) -> None:
        """Write all queued option changes to the config entry in one update."""
        self._options_write_unsub = None
        if not self._pending_options:
            return
        pending, self._pending_options = self._pending_options, {}
        new_options = {**self._entry.options, **pending}
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def async_shutdown(self) -> None:
        """Cancel all background tasks gracefully."""
        if self._options_write_unsub is not None:
            self._options_write_unsub()
            self._options_write_unsub = None
        for tier in list(self._breeze_tasks.keys()):
            self._stop_breeze_task(tier)
        _LOGGER.debug("Helix Cultivate coordinator shut down.")
