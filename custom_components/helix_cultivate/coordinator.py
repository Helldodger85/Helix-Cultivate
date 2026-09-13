"""Helix Cultivate — Central DataUpdateCoordinator."""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
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
    CONF_THERMAL_LEARNING_ENABLED,
    DEFAULT_THERMAL_LEARNING_ENABLED,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_EXHAUST_FAN,
    CONF_ZONE2_AC,
    CONF_ZONE2_HEATER,
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
    DEFAULT_FAN_VARIANCE_PCT,
    DEFAULT_HARVEST_VALUE,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    CONF_SENSOR_DROPOUT_MIN,
    DEFAULT_SENSOR_DROPOUT_MIN_CFG,
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
    # 3.2 Canopy wind sweep
    CONF_WIND_SWEEP_ENABLED,
    DEFAULT_WIND_SWEEP_ENABLED,
    WIND_SWEEP_INTERVAL_MIN,
    WIND_SWEEP_BOOST_PCT,
    WIND_SWEEP_REST_PCT,
    # 3.5 Stage-progression heads-up warnings
    CONF_STAGE_WARNING_LEAD_DAYS,
    DEFAULT_STAGE_WARNING_LEAD_DAYS,
    STAGE_TRANSITION_TIPS,
    # Cycle lifecycle (Part 1)
    CONF_CYCLE_STATE,
    CONF_DRYING_CYCLE_ID,
    CONF_DRYING_DEPENDS_ON_CONDITIONING,
    CONF_DRYING_OCCUPIED,
    CONF_ZONE2_CYCLE_ID,
    CONF_ZONE2_DEPENDS_ON_CONDITIONING,
    CONF_ZONE2_OCCUPIED,
    DEFAULT_DEPENDS_ON_CONDITIONING,
    DEFAULT_DRYING_OCCUPIED,
    DEFAULT_ZONE2_OCCUPIED,
    CONF_STAGE_START_DATE,
    CYCLE_STATE_ACTIVE,
    CYCLE_STATE_NOT_STARTED,
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
        # Part 1.6: read the persisted base speed back from config (matching
        # the breeze_variance_{tier} convention) — previously this always
        # started at the coded default and set_fan_speed() never persisted
        # its writes, so ANY unrelated settings change that triggered a
        # config-entry reload (rebuilding this coordinator from scratch)
        # silently reverted a manually-set fan speed back to 50%.
        self._fan_speeds: dict[str, float] = {
            FAN_TIER_UPPER: float(self._config.get(f"fan_speed_{FAN_TIER_UPPER}", DEFAULT_FAN_SPEED_PCT)),
            FAN_TIER_MID: float(self._config.get(f"fan_speed_{FAN_TIER_MID}", DEFAULT_FAN_SPEED_PCT)),
            FAN_TIER_LOWER: float(self._config.get(f"fan_speed_{FAN_TIER_LOWER}", DEFAULT_FAN_SPEED_PCT)),
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
        # Part 5.5 (v1.4.0): dwell timer for the backup heater's "primary
        # source is falling behind" condition — same pattern as
        # _dehumid_on_since/_humid_on_since above.
        self._backup_heater_falling_behind_since: Optional[datetime] = None
        # Part 7.5 (v1.4.0): last passive-log timestamp per zone, keyed by
        # zone label — rate-limits Environmental Learning's hourly logging.
        self._learning_last_log: dict[str, datetime] = {}
        # Part 1.2 (v1.4.1): last dedicated-sensor reading sent via
        # midea_ac.follow_me per entity_id — only re-sent on a meaningful
        # change (FOLLOW_ME_MIN_DELTA_C).
        self._follow_me_last_sent: dict[str, float] = {}

        # ── Appliance dropout watchdog (Phase 10B) ────────────────────────────
        # Keys are role strings: "zone1_heater", "zone1_dehumid", etc.
        self._appliance_unavail_since: dict[str, Optional[datetime]] = {}
        # Pre-existing gap: this was read/written throughout
        # _check_appliance_dropout()/_raise_appliance_dropout_notification()
        # but never actually initialised here, so the very first dropout
        # check on a real coordinator (not a test's mock_coord, which sets
        # this explicitly) would raise AttributeError. Fixed while adding
        # _record_command_failure() (Part 1), which reads/writes the same dict.
        self._appliance_dropout_alerted: dict[str, bool] = {}

        # ── Dew point / condensation prediction (Part 3.3) ────────────────────
        self._dew_point_risk_since: Optional[datetime] = None
        self._dew_point_alerted: bool = False

        # ── Canopy wind sweep (Part 3.2) ───────────────────────────────────────
        self._wind_sweep_phase_since: Optional[datetime] = None
        self._wind_sweep_current_tier: Optional[str] = None

        # ── Stage-progression heads-up warnings (Part 3.5) ─────────────────────
        self._stage_warning_alerted: dict[str, bool] = {}

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
        # Part 4.1: each tier reads its own persisted breeze_{tier}_enabled key
        # (matching the breeze_variance_{tier} convention already used for
        # variance) — previously all three read the single shared
        # CONF_BREEZE_ENABLED key, so enabling Breeze on one tier silently
        # enabled it on all three at once.
        self.breeze_upper_enabled: bool = self._read_persisted_breeze_enabled(FAN_TIER_UPPER)
        self.breeze_mid_enabled: bool = self._read_persisted_breeze_enabled(FAN_TIER_MID)
        self.breeze_lower_enabled: bool = self._read_persisted_breeze_enabled(FAN_TIER_LOWER)
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

    def _read_persisted_breeze_enabled(self, tier: str) -> bool:
        """Read this tier's own persisted breeze_{tier}_enabled key (Part 4.1)."""
        return bool(self._config.get(f"breeze_{tier}_enabled", False))

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
        """Return True if the primary temperature sensor has been stale > dropout threshold.

        Part 1 safety fix: this previously always used the hardcoded
        DEFAULT_SENSOR_DROPOUT_MIN constant regardless of what a grower had
        configured (via the Options Flow, or now the live Dropout Timeout
        number entity) — CONF_SENSOR_DROPOUT_MIN was persisted correctly but
        silently never actually read here, so the dropout timeout was not
        genuinely configurable at all.
        """
        primary_temp_id: Optional[str] = self._get(CONF_PRIMARY_TEMP_SENSOR)
        if not primary_temp_id:
            return True
        dropout_min = float(self._get(CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG))
        state = self.hass.states.get(primary_temp_id)
        if state is None or state.state in ("unavailable", "unknown", ""):
            if self._primary_last_seen is None:
                return True
            stale_secs = (dt_util.utcnow() - self._primary_last_seen).total_seconds()
            return stale_secs > dropout_min * 60
        self._primary_last_seen = dt_util.utcnow()
        return False

    # ── Repairs / issue_registry health checks (Phase 12B) ────────────────────

    def _check_repairs_issues(
        self,
        lung_temp: Optional[float],
        lung_rh: Optional[float],
        sensor_dropout: bool = False,
    ) -> None:
        """Evaluate the Repairs conditions and create/clear issues.

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

        # ── 6. Primary sensor actively dropped out (Part 2.1) ─────────────────
        # Distinct from #5 above: this is a sensor that WAS mapped and
        # working, now gone stale/unavailable — surfaced as its own Repairs
        # issue (with the specific entity_id) so the dashboard's Sensor
        # Dropout badge has a real Repairs entry to link to, sourced from
        # the same _check_sensor_dropout() state already driving the
        # critical notification. Not new dropout-detection logic — the
        # detection already existed, only the Repairs surfacing was missing.
        issue_id = "primary_sensor_dropout"
        primary_temp_id = self._get(CONF_PRIMARY_TEMP_SENSOR)
        if sensor_dropout and primary_temp_id:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.ERROR,
                translation_key=issue_id,
                translation_placeholders={"entity_id": primary_temp_id},
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

    def _calc_dew_point_c(self, temp_c: float, rh_pct: float) -> float:
        """Dew point [°C] via the standard Magnus-formula approximation —
        reuses the same a/b saturation-vapor-pressure constants as
        _calc_leaf_vpd above for internal consistency. Used by the dew
        point / condensation prediction hard override (Part 3.3).
        """
        import math
        rh_frac = max(0.01, min(1.0, rh_pct / 100.0))  # avoid log(0)
        a, b = 17.27, 237.3
        alpha = math.log(rh_frac) + (a * temp_c) / (b + temp_c)
        return (b * alpha) / (a - alpha)

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

    def _minutes_until_lights_off(self) -> Optional[float]:
        """Minutes from now until the next scheduled lights-off transition,
        derived from the same schedule parameters _light_schedule_multiplier
        uses — Helix Cultivate drives the light schedule directly, so the
        off-time is always known in advance. Used by predictive
        pre-heating (Part 3.4).

        Returns None when there is no scheduled "off" transition to predict:
        hours<=0 (light never on) or hours>=24 (always on).
        """
        hours, on_time, _key = self._light_schedule_params()
        if hours <= 0 or hours >= 24:
            return None
        now_t = dt_util.now().time()
        on_minutes = on_time.hour * 60 + on_time.minute
        now_minutes = now_t.hour * 60 + now_t.minute
        off_minutes = (on_minutes + hours * 60.0) % (24 * 60)
        return (off_minutes - now_minutes) % (24 * 60)

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

    # ── Stage-progression heads-up warnings (Part 3.5) ──────────────────────

    async def _check_stage_progression_warning(self) -> None:
        """Purely informational/advisory reminder for manual grower action —
        Helix Cultivate does not perform any of these transitions
        automatically. At CONF_STAGE_WARNING_LEAD_DAYS (default 3) before
        the active stage's expected duration elapses, fires an
        informational notification (and dashboard banner, via the same
        exposed sensor attrs pattern as other advisories) suggesting
        relevant manual actions for the upcoming transition.

        Fires exactly once per approaching transition (guarded by
        `_stage_warning_alerted[stage]`, reset the moment the countdown is
        no longer inside the lead window) — a 30-second tick loop would
        otherwise re-fire this every tick for the entire lead window.
        """
        stage = self.stage_manager.current_stage
        if stage not in STAGE_SEQUENCE or stage == STAGE_SEQUENCE[-1]:
            # Drying (the last stage) has no "next" stage to warn about
            # within this cycle.
            return

        duration = self.stage_manager._duration(stage)
        elapsed = self.stage_manager._elapsed_days()
        days_remaining = duration - elapsed
        lead_days = int(self._get(CONF_STAGE_WARNING_LEAD_DAYS, DEFAULT_STAGE_WARNING_LEAD_DAYS))

        if days_remaining > lead_days:
            self._stage_warning_alerted[stage] = False
            return
        if self._stage_warning_alerted.get(stage, False):
            return

        idx = STAGE_SEQUENCE.index(stage)
        next_stage = STAGE_SEQUENCE[idx + 1]
        next_label = STAGE_LABELS.get(next_stage, next_stage)
        tip = STAGE_TRANSITION_TIPS.get(next_stage, "")

        self.hass.bus.async_fire(
            "helix_cultivate_stage_progression_warning",
            {
                "entry_id": self._entry.entry_id,
                "current_stage": stage,
                "next_stage": next_stage,
                "days_remaining": days_remaining,
            },
        )
        await self._notify_critical(
            title=f"Helix Cultivate — Approaching {next_label}",
            message=(
                f"~{days_remaining} day(s) until the expected transition to "
                f"{next_label}. {tip} This is a reminder for manual action — "
                "Helix Cultivate does not perform this automatically."
            ),
            level="info",
        )
        self._stage_warning_alerted[stage] = True

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

    def _actuator_dropout_status(self) -> tuple[bool, list[str]]:
        """Part 1.2: whether any Primary Grow Space actuator — heater, AC/
        Reverse Cycle, or exhaust fan — is currently past the 5-minute
        dropout threshold, and which mapped entity IDs are affected.

        Used to escalate the dashboard's sensor-dropout badge from amber to
        red: losing control of hardware (can't heat/cool/exhaust) is more
        urgent than losing a passive reading. Recomputed fresh from
        `_appliance_unavail_since` rather than cached, since that dict is
        only ever written from within climate_engine's own control calls.
        """
        role_to_conf = {
            "zone2_heater": CONF_ZONE2_HEATER,
            "zone2_ac": CONF_ZONE2_AC,
            "exhaust": CONF_EXHAUST_FAN,
        }
        entities: list[str] = []
        for role, conf_key in role_to_conf.items():
            since = self._appliance_unavail_since.get(role)
            if since is not None and (dt_util.utcnow() - since) >= timedelta(minutes=5):
                entity_id = self._get(conf_key)
                if entity_id:
                    entities.append(entity_id)
        return bool(entities), entities

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

    def _record_command_failure(self, role: str, entity_id: str) -> None:
        """Feed an actuator command that failed even after the retry
        wrapper's attempts (ClimateEngine._call_service_with_retry, Part 1)
        into the exact same dwell-and-notify tracking used above for
        entities the HA state machine itself reports unavailable — a
        service call that fails outright after retries is equally valid
        evidence the appliance is unreachable. Deliberately reuses
        `_appliance_unavail_since`/`_appliance_dropout_alerted` rather than
        a second, parallel tracking dict: a persistent failure must
        accumulate the same 5-minute dwell before alerting once, not spawn
        its own separate alerting system. If the entity's actual HA state
        recovers on a later tick, `_check_appliance_dropout`'s own reset
        branch clears this dwell too, since both share the same dicts.
        """
        if self._appliance_unavail_since.get(role) is None:
            self._appliance_unavail_since[role] = dt_util.utcnow()
        elapsed = dt_util.utcnow() - self._appliance_unavail_since[role]
        if elapsed >= timedelta(minutes=5) and not self._appliance_dropout_alerted.get(role, False):
            self.hass.async_create_task(
                self._raise_appliance_dropout_notification(role, entity_id)
            )
            self._appliance_dropout_alerted[role] = True

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
                # Part 4.2: per-tier variance — this previously read the single
                # shared CONF_BREEZE_VARIANCE key for every tier, ignoring the
                # already-existing, independently-editable Upper/Mid/Lower
                # Breeze Variance number entities (breeze_variance_{tier}).
                variance = float(self._get(f"breeze_variance_{tier}", DEFAULT_FAN_VARIANCE_PCT))
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

    def _current_zone_temp_for_learning(self, zone: str) -> Optional[float]:
        """Current temperature reading for a learning-system zone label,
        read from the last-assembled tick data — used to snapshot a Deep
        Calibration test's starting point without a second live sensor read."""
        climate = (self.data or {}).get(NS_CLIMATE, {})
        return {
            "zone2": climate.get("upper_temp_c"),
            "conditioning": climate.get("lung_temp_c"),
            "drying": climate.get("drying_temp_c"),
        }.get(zone)

    def is_deep_calibration_active(self, zone: str) -> bool:
        """Cheap, always-safe check used by climate_engine on every tick —
        False immediately whenever Environmental Learning is disabled, so
        this costs nothing for the overwhelming majority of installs."""
        if not self._get(CONF_THERMAL_LEARNING_ENABLED, DEFAULT_THERMAL_LEARNING_ENABLED):
            return False
        from .learning_engine import LearningEngine

        return LearningEngine(self).is_deep_calibration_active(zone)

    def active_live_actuator_test_for_zone(self, zone: str) -> Optional[dict[str, Any]]:
        """Cheap, always-safe check mirroring is_deep_calibration_active
        above — returns the active test dict when a Live Actuator Response
        Test is currently running for `zone`, else None. Consumed by
        climate_engine to autonomously apply (and later revert) the
        setpoint nudge for a thermostat-controlled zone's test, so the
        whole nudge/measure cycle needs no manual intervention once
        started (Part 2, v1.4.1)."""
        if not self._get(CONF_THERMAL_LEARNING_ENABLED, DEFAULT_THERMAL_LEARNING_ENABLED):
            return None
        store = self.hass.data.get(DOMAIN, {}).get("learning_store")
        if store is None:
            return None
        active = store.get_active_test()
        if not active:
            return None
        from .learning_engine import TEST_TYPE_LIVE_ACTUATOR

        if active.get("type") == TEST_TYPE_LIVE_ACTUATOR and active.get("zone") == zone:
            return active
        return None

    async def _run_environmental_learning_tick(
        self,
        upper_canopy_temp: Optional[float],
        lung_temp: Optional[float],
        outdoor_temp: Optional[float],
    ) -> None:
        """Part 7: entirely inert (no import even happens meaningfully
        beyond this early return) whenever the master toggle is off —
        zero background logging, zero scheduled tests, zero influence."""
        if not self._get(CONF_THERMAL_LEARNING_ENABLED, DEFAULT_THERMAL_LEARNING_ENABLED):
            return

        from .learning_engine import LearningEngine

        engine = LearningEngine(self)
        await engine.ensure_started()
        engine.maybe_graduate_to_active()

        drying_temp: Optional[float] = None
        if self._get(CONF_ENABLE_DRYING_ENVIRONMENT, False):
            drying_temp = self._read_sensor(self._get(CONF_DRYING_TEMP_SENSOR))

        lights_on = bool((self.data or {}).get(NS_CLIMATE, {}).get("lights_on", False))
        light_pct = float(self.light_intensity_pct or 0.0)

        await engine.maybe_log_hourly(
            "zone2", outdoor_temp, upper_canopy_temp,
            self._fan_speeds.get(FAN_TIER_UPPER, 0.0), lights_on, light_pct,
            self._get(CONF_ZONE2_CYCLE_ID),
        )
        if self._get(CONF_ENABLE_CONDITIONING_ROOM, False):
            await engine.maybe_log_hourly(
                "conditioning", outdoor_temp, lung_temp, 0.0, lights_on, light_pct, None,
            )
        if drying_temp is not None:
            await engine.maybe_log_hourly(
                "drying", outdoor_temp, drying_temp, 0.0, lights_on, light_pct,
                self._get(CONF_DRYING_CYCLE_ID),
            )

        zone_temps = {
            "zone2": upper_canopy_temp,
            "conditioning": lung_temp,
            "drying": drying_temp,
        }
        await engine.tick_active_test(zone_temps)
        # Part 2 (v1.4.1): decide autonomously whether it's time to run a
        # Live Actuator Response Test — a no-op most ticks (interval not
        # elapsed yet, or a test is already active). Manual triggering (the
        # Settings tab's start action) remains available alongside this.
        await engine.maybe_schedule_live_actuator_test(zone_temps)

    def _manage_breeze_tasks(self) -> None:
        """Start/stop each tier's breeze loop to match its enabled state
        (Part 4.1/4.2) — runs every tick, before _manage_wind_sweep, so wind
        sweep (when active) can immediately stop whatever this just
        (re)started for a tier it's about to take over instead of the two
        fighting over the same fan. Once wind sweep releases a tier, this
        naturally restarts its breeze task on the very next tick since it
        re-evaluates "enabled but no live task" every time."""
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

    async def _manage_wind_sweep(self) -> None:
        """Canopy wind sweep (Part 3.2) — growing stages only. Rotates a
        boosted speed among the currently-enabled circulation tiers on a
        dwell timer, rather than every enabled tier running the same static
        speed simultaneously — mimics natural gusting wind to eliminate
        static microclimates and add mechanical stem-strengthening stress.

        Must never activate during Drying, where the gentle-cyclic/constant
        airflow strategy (CONF_DRYING_AIRFLOW_MODE) takes exclusive
        priority — checked explicitly below, not just left to the toggle.
        Off by default (CONF_WIND_SWEEP_ENABLED), so nothing changes for
        existing installs unless a grower opts in.
        """
        enabled = bool(self._get(CONF_WIND_SWEEP_ENABLED, DEFAULT_WIND_SWEEP_ENABLED))
        if not enabled or self.stage_manager.current_stage == STAGE_DRYING:
            self._wind_sweep_phase_since = None
            self._wind_sweep_current_tier = None
            return

        enabled_tiers = [
            t for t in (FAN_TIER_UPPER, FAN_TIER_MID, FAN_TIER_LOWER)
            if self._is_fan_tier_enabled(t)
        ]
        if not enabled_tiers:
            return

        now = dt_util.utcnow()
        if (
            self._wind_sweep_current_tier not in enabled_tiers
            or self._wind_sweep_phase_since is None
        ):
            self._wind_sweep_current_tier = enabled_tiers[0]
            self._wind_sweep_phase_since = now
        else:
            elapsed_min = (now - self._wind_sweep_phase_since).total_seconds() / 60.0
            if elapsed_min >= WIND_SWEEP_INTERVAL_MIN:
                idx = enabled_tiers.index(self._wind_sweep_current_tier)
                self._wind_sweep_current_tier = enabled_tiers[(idx + 1) % len(enabled_tiers)]
                self._wind_sweep_phase_since = now

        for tier in enabled_tiers:
            # Take over from the breeze engine for every tier wind sweep
            # drives, so its own independent async loop can't fight this
            # tick-based choreography over the same fans.
            self._stop_breeze_task(tier)
            target = (
                WIND_SWEEP_BOOST_PCT if tier == self._wind_sweep_current_tier
                else WIND_SWEEP_REST_PCT
            )
            await self._apply_fan_speed_to_tier(tier, target)

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
        self._check_repairs_issues(lung_temp, lung_rh, sensor_dropout)

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
        await self._check_stage_progression_warning()

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
        self._manage_breeze_tasks()

        # ── Canopy wind sweep (Part 3.2) — runs after breeze-task management
        # so that, when active, it can stop any breeze task the block above
        # just (re)started for a tier it's about to take over, rather than
        # the two fighting over the same fan.
        await self._manage_wind_sweep()

        # ── Environmental Learning System (Part 7) — fully inert when the
        # master toggle is off; nothing below this line runs at all in
        # that case.
        await self._run_environmental_learning_tick(
            upper_canopy_temp, lung_temp, climate_state.get("outdoor_temp_c")
        )

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
        dropout_min = float(self._get(CONF_SENSOR_DROPOUT_MIN, DEFAULT_SENSOR_DROPOUT_MIN_CFG))
        await self._notify_critical(
            title="Helix Cultivate — Sensor Alert",
            message=(
                "The primary canopy temperature sensor is unavailable or has not updated "
                f"for over {dropout_min:.0f} minutes. "
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
        """Update the base fan speed for a tier, persist it, and apply
        immediately unless Breeze is currently driving this tier's speed."""
        self._fan_speeds[tier] = max(0.0, min(100.0, speed_pct))
        # Part 1.6: persist so this survives a config-entry reload triggered
        # by an unrelated settings change elsewhere in the panel — this was
        # previously an in-memory-only coordinator attribute, exactly the
        # bug pattern already fixed for the Breeze switches last session.
        config_key = f"fan_speed_{tier}"
        self._config[config_key] = self._fan_speeds[tier]
        self.queue_option_write(config_key, self._fan_speeds[tier])
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

    async def _finalize_harvest_record(
        self,
        wet_weight_g: float,
        dry_weight_g: float,
        *,
        cycle_id: Optional[str] = None,
        cycle_kwh: Optional[float] = None,
        cycle_cost: Optional[float] = None,
        stage_durations: Optional[dict[str, int]] = None,
    ) -> dict[str, Any]:
        """Shared record-building/archiving logic for both close_out_harvest()
        (no dedicated Drying Room — the only cycle ever in flight) and
        harvest_complete_drying_batch() (Part 4.4: closing out one specific
        batch that may be concurrent with a newer, unrelated cycle already
        running in Primary Grow Space). Deliberately does NOT touch
        occupancy flags or stage-machine state — callers own that, since
        the two paths differ there. cycle_kwh/cycle_cost/stage_durations
        default to the live global counters/current stage (the
        no-dedicated-room case, where there is only ever one cycle) but
        accept explicit overrides so a concurrent drying batch is costed
        and duration-tracked from its own isolated snapshot instead.
        """
        harvest_value_oz = float(self._get(CONF_HARVEST_VALUE_PER_OZ, DEFAULT_HARVEST_VALUE))
        dry_oz = dry_weight_g / 28.3495 if dry_weight_g else 0.0
        revenue = dry_oz * harvest_value_oz
        if cycle_kwh is None:
            cycle_kwh = self._cycle_kwh
        if cycle_cost is None:
            cycle_cost = (self.data or {}).get(NS_ENERGY, {}).get("cycle_cost_usd", self._cycle_cost)
        dollar_per_g = (cycle_cost / dry_weight_g) if dry_weight_g > 0 else 0.0

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
            "cycle_id": cycle_id,
            "wet_weight_g": wet_weight_g,
            "dry_weight_g": dry_weight_g,
            "cycle_kwh": cycle_kwh,
            "cycle_cost_usd": cycle_cost,
            "stage_durations": (
                stage_durations if stage_durations is not None
                else self.stage_manager.actual_stage_durations()
            ),
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
                "cycle_id": cycle_id,
                "dry_weight_g": dry_weight_g,
                "cycle_cost_usd": cycle_cost,
                "dollars_per_gram": round(dollar_per_g, 4),
            },
        )

        # Archive this cycle's energy totals as Previous Cycle (2.7) — a full
        # harvest close-out counts as "the last reset" for that display, same
        # as the dedicated Reset button.
        await journal.async_set_previous_cycle_energy(self._entry.entry_id, cycle_kwh, cycle_cost)

        await self._notify_critical(
            title="Helix Cultivate — Harvest Archived",
            message=(
                f"Cycle archived as {record_id}. {dry_weight_g:.1f}g dry at "
                f"${dollar_per_g:.2f}/g."
            ),
            level="info",
        )

        return {**harvest_data, "record_id": record_id}

    async def close_out_harvest(self, wet_weight_g: float, dry_weight_g: float) -> dict[str, Any]:
        """Archive the completed grow cycle, reset all cycle counters and the
        stage machine, and return the full harvest record (including the
        newly-assigned record_id) for the frontend Harvest Report.

        The no-dedicated-Drying-Room path (Part 4.5) — material never
        physically leaves Primary Grow Space during Drying, so there is
        only ever one cycle in flight and this resets every global counter.
        See harvest_complete_drying_batch() for the dedicated-room path,
        which must NOT reset these since an unrelated, concurrent cycle may
        already be running in Primary Grow Space by the time this fires.

        Raises ValueError on schema violation (propagated from journal_store).
        """
        cycle_id = self._get(CONF_ZONE2_CYCLE_ID)
        harvest_data = await self._finalize_harvest_record(
            wet_weight_g, dry_weight_g, cycle_id=cycle_id
        )
        cost = harvest_data["cycle_cost_usd"]

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

        # Return to a genuine not-started state (Part 1.4) — the next
        # grower action is always an explicit Start New Cycle, never a
        # silent Germination Day-0 reactivation the instant this closes.
        self.stage_manager.return_to_not_started()
        self._config[CONF_ZONE2_OCCUPIED] = False
        new_options = {
            **self._entry.options,
            CONF_CYCLE_STATE: CYCLE_STATE_NOT_STARTED,
            "current_stage": self.stage_manager.current_stage,
            # Part 4.5: this is the no-dedicated-Drying-Room path — material
            # never physically leaves Primary Grow Space during Drying, so
            # this close-out is the only point at which the space actually
            # becomes empty again.
            CONF_ZONE2_OCCUPIED: False,
        }
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        return harvest_data

    # ── Cycle lifecycle (Part 1) ─────────────────────────────────────────────

    async def start_cycle(
        self, growth_mode: str, start_date: str, starting_stage: str
    ) -> None:
        """"Start New Cycle" action (Part 1.2) — the only way a cycle moves
        from "not_started" to "active". Accepts a backdated start_date
        (configuring the integration a few days after actually planting)
        and a non-default starting_stage (e.g. clones purchased already in
        Early Veg), so day-counting and stage resolution are correct from
        the very first tick.

        Reuses the existing CONF_GROWTH_MODE toggle rather than a
        duplicate — growth_mode is persisted here alongside stage/date/
        cycle_state in a single immediate config-entry write, the same
        pattern the Grow Stage select entity's setter uses for an explicit,
        infrequent user action (as opposed to the debounced
        queue_option_write() sliders use).

        Raises ValueError on an invalid stage or growth mode.
        """
        if starting_stage not in STAGE_SEQUENCE:
            raise ValueError(f"Invalid starting stage: {starting_stage!r}")
        if growth_mode not in (GROWTH_MODE_AUTOFLOWER, GROWTH_MODE_PHOTOPERIOD):
            raise ValueError(f"Invalid growth mode: {growth_mode!r}")
        try:
            parsed_date = date.fromisoformat(start_date) if start_date else date.today()
        except (ValueError, TypeError):
            parsed_date = date.today()

        self._config[CONF_GROWTH_MODE] = growth_mode
        self.stage_manager.start_new_cycle(starting_stage, parsed_date)

        # Part 4.1: a fresh cycle_id per cycle, and Primary Grow Space is now
        # physically occupied — independent of cycle_state, which tracks
        # whether a batch is being tracked at all, not whether the space
        # itself currently holds plant material.
        new_cycle_id = uuid.uuid4().hex[:12]
        self._config[CONF_ZONE2_CYCLE_ID] = new_cycle_id
        self._config[CONF_ZONE2_OCCUPIED] = True

        new_options = {
            **self._entry.options,
            CONF_GROWTH_MODE: growth_mode,
            "current_stage": starting_stage,
            CONF_STAGE_START_DATE: parsed_date.isoformat(),
            CONF_CYCLE_STATE: CYCLE_STATE_ACTIVE,
            CONF_ZONE2_CYCLE_ID: new_cycle_id,
            CONF_ZONE2_OCCUPIED: True,
        }
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        self.hass.bus.async_fire(
            "helix_cultivate_cycle_started",
            {
                "entry_id": self._entry.entry_id,
                "growth_mode": growth_mode,
                "starting_stage": starting_stage,
                "start_date": parsed_date.isoformat(),
            },
        )

    async def abort_cycle(self) -> None:
        """"Abort Cycle" action (Part 1.5) — a second, clearly-distinct
        destructive action from harvest close-out: no harvest record, no
        weight entry, no journal archive. For a cycle that never reaches
        harvest (pests, mistakes, a failed run). Returns directly to
        "not_started" so the next action is an explicit Start New Cycle.
        """
        self.stage_manager.return_to_not_started()
        self._config[CONF_ZONE2_OCCUPIED] = False
        new_options = {
            **self._entry.options,
            CONF_CYCLE_STATE: CYCLE_STATE_NOT_STARTED,
            "current_stage": self.stage_manager.current_stage,
            CONF_ZONE2_OCCUPIED: False,
        }
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        self.hass.bus.async_fire(
            "helix_cultivate_cycle_aborted",
            {"entry_id": self._entry.entry_id},
        )

    # ── Zone occupancy (Part 4) ─────────────────────────────────────────────────

    def is_zone2_occupied(self) -> bool:
        """Primary Grow Space occupancy — physically holds plant material
        right now, independent of cycle_state (which only tracks whether a
        batch is being tracked at all)."""
        return bool(self._get(CONF_ZONE2_OCCUPIED, DEFAULT_ZONE2_OCCUPIED))

    def is_drying_occupied(self) -> bool:
        """Dedicated Drying Room occupancy — only ever meaningful when
        enable_drying_environment is True; always False otherwise (there is
        no separate room to be occupied)."""
        if not self._get(CONF_ENABLE_DRYING_ENVIRONMENT, False):
            return False
        return bool(self._get(CONF_DRYING_OCCUPIED, DEFAULT_DRYING_OCCUPIED))

    # ── Conditioning Room calibration eligibility (Part 3) ──────────────────────
    #
    # Corrects an earlier design that gated Conditioning Room's own Deep
    # Calibration eligibility on ITS OWN occupancy — but Conditioning Room
    # never has plants, so that gate was always trivially true and missed
    # the actual risk: a dependent zone (Primary Grow Space, or a
    # dependent Drying Room) being destabilized by Conditioning Room
    # deliberately cutting its own actuator control during calibration.
    # Consumed by the Environmental Learning System (Part 7) — nothing
    # calls this yet on its own, since Deep Calibration doesn't exist
    # until Part 7 builds it, but the gating rule is correct and testable
    # in isolation now.

    def conditioning_room_dependent_zones(self) -> list[str]:
        """Return which zones (by FAN_TIER-style identifier: "zone2",
        "drying") are flagged as depending on Conditioning Room for their
        own baseline climate — per Part 3.1, always an explicit, confirmed
        per-zone toggle, never silently inferred at read-time. Drying is
        only ever included when a dedicated Drying Room actually exists."""
        dependents: list[str] = []
        if self._get(CONF_ZONE2_DEPENDS_ON_CONDITIONING, DEFAULT_DEPENDS_ON_CONDITIONING):
            dependents.append("zone2")
        if self._get(CONF_ENABLE_DRYING_ENVIRONMENT, False) and self._get(
            CONF_DRYING_DEPENDS_ON_CONDITIONING, DEFAULT_DEPENDS_ON_CONDITIONING
        ):
            dependents.append("drying")
        return dependents

    def is_conditioning_room_calibration_eligible(self) -> bool:
        """Part 3.2: Conditioning Room may only run Deep Calibration when
        EVERY zone flagged as depending on it (per conditioning_room_
        dependent_zones()) is currently unoccupied. If Drying Room depends
        on Conditioning Room and is currently occupied by curing material,
        Conditioning Room is restricted to Live Actuator Response Testing
        only, regardless of Primary Grow Space's own occupancy state.
        Always re-evaluated fresh from current occupancy — never cached.
        """
        occupancy_by_zone = {
            "zone2": self.is_zone2_occupied(),
            "drying": self.is_drying_occupied(),
        }
        return not any(
            occupancy_by_zone[zone] for zone in self.conditioning_room_dependent_zones()
        )

    async def space_now_empty(self) -> None:
        """"Harvest — Space Now Empty" (Part 4.2). Only valid when a
        dedicated Drying Room is configured — without one, material never
        physically leaves Primary Grow Space during Drying, so there is
        nothing to transfer (the frontend never shows this action in that
        topology; this check is the backend's own defense-in-depth copy of
        that same rule).

        Transfers occupancy — Primary Grow Space becomes unoccupied and
        Drying Room becomes occupied by this same batch — WITHOUT touching
        the batch's cycle_id, its stage tracking (current_stage/
        stage_start_date keep advancing exactly as before — this is not a
        reset), or any accumulated data. The only lasting record of the
        transfer is CONF_DRYING_CYCLE_ID, so harvest_complete_drying_batch()
        later knows which cycle_id it's closing out.
        """
        if not self._get(CONF_ENABLE_DRYING_ENVIRONMENT, False):
            raise ValueError(
                "space_now_empty() requires a dedicated Drying Room "
                "(enable_drying_environment) — without one, drying happens "
                "in Primary Grow Space itself and there is nothing to "
                "transfer."
            )
        cycle_id = self._get(CONF_ZONE2_CYCLE_ID)

        # Snapshot this batch's stage-duration history now, while
        # stage_manager still represents it — by the time
        # harvest_complete_drying_batch() runs, Primary Grow Space may
        # already be tracking a different, newer cycle_id, so reading
        # stage_manager live at that point would attribute the wrong
        # batch's durations to this one.
        # v1.4.1 Part 3 fix: also snapshot the Drying stage's own true
        # start date (not just its elapsed-days-so-far total). Primary Grow
        # Space's single live stage_manager is about to be freed for a new
        # cycle, so this batch's day-count in Drying needs its own
        # unchanging reference point to keep computing live from — the
        # transfer itself never touches this date, it only carries forward
        # whatever stage_manager already had for the current (Drying) stage.
        journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
        if journal is not None:
            drying_start = self.stage_manager.stage_start_date
            await journal.open_drying_batch(cycle_id, {
                "stage_durations_snapshot": self.stage_manager.actual_stage_durations(),
                "drying_stage_start_date": drying_start.isoformat() if drying_start else None,
                "moved_to_drying_at": dt_util.utcnow().isoformat(),
            })

        self._config[CONF_ZONE2_OCCUPIED] = False
        self._config[CONF_DRYING_OCCUPIED] = True
        self._config[CONF_DRYING_CYCLE_ID] = cycle_id
        new_options = {
            **self._entry.options,
            CONF_ZONE2_OCCUPIED: False,
            CONF_DRYING_OCCUPIED: True,
            CONF_DRYING_CYCLE_ID: cycle_id,
        }
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)

        self.hass.bus.async_fire(
            "helix_cultivate_space_now_empty",
            {"entry_id": self._entry.entry_id, "cycle_id": cycle_id},
        )

    def _drying_batch_live_days(self, snapshot: Optional[dict[str, Any]]) -> Optional[int]:
        """Recompute the Drying stage's own elapsed-days live from the
        unchanging `drying_stage_start_date` captured at transfer time —
        the same `date.today() - stage_start_date` pattern every other
        stage's day-count already uses. Returns None when the snapshot
        predates this field (an in-progress v1.4.0 batch) or carries no
        start date, rather than fabricating a number.
        """
        if not snapshot:
            return None
        raw = snapshot.get("drying_stage_start_date")
        if not raw:
            return None
        try:
            start = date.fromisoformat(raw)
        except (TypeError, ValueError):
            return None
        return max(0, (date.today() - start).days)

    def drying_batch_elapsed_days(self) -> Optional[int]:
        """Live day-count for the batch currently occupying the dedicated
        Drying Room — for the dashboard. None when nothing is occupying it
        or no snapshot exists yet."""
        if not self.is_drying_occupied():
            return None
        journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
        if journal is None:
            return None
        cycle_id = self._get(CONF_DRYING_CYCLE_ID)
        snapshot = journal.get_open_drying_batch(cycle_id)
        return self._drying_batch_live_days(snapshot)

    async def harvest_complete_drying_batch(
        self, wet_weight_g: float, dry_weight_g: float
    ) -> dict[str, Any]:
        """"Harvest Complete" (Part 9) for the batch currently occupying the
        dedicated Drying Room — closes out CONF_DRYING_CYCLE_ID specifically
        and frees Drying Room's occupancy (Part 4.3: this is the only thing
        that clears it — never stage-tracking completion alone). Entirely
        independent of whatever Primary Grow Space is doing at the moment
        this is called — a fresh cycle_id may already be germinating there
        concurrently.
        """
        if not self.is_drying_occupied():
            raise ValueError(
                "No batch is currently occupying the Drying Room — nothing to close out."
            )
        cycle_id = self._get(CONF_DRYING_CYCLE_ID)

        journal = self.hass.data.get(DOMAIN, {}).get("journal_store")
        snapshot = journal.get_open_drying_batch(cycle_id) if journal is not None else None
        stage_durations = (
            dict(snapshot.get("stage_durations_snapshot")) if snapshot is not None
            and snapshot.get("stage_durations_snapshot") is not None else None
        )
        # v1.4.1 Part 3 fix: the snapshot's own "drying" entry was frozen at
        # whatever elapsed_days read at transfer time (typically ~0) — the
        # archived harvest record must reflect the real, final number of
        # days actually spent drying, recomputed live right now rather than
        # reusing that stale transfer-time value.
        if stage_durations is not None:
            live_drying_days = self._drying_batch_live_days(snapshot)
            if live_drying_days is not None:
                stage_durations[STAGE_DRYING] = live_drying_days

        # Uses the Drying-specific energy accumulators, not the global
        # zone2 ones — an unrelated, concurrent cycle may already be
        # running in Primary Grow Space and must not be affected by this.
        harvest_data = await self._finalize_harvest_record(
            wet_weight_g, dry_weight_g,
            cycle_id=cycle_id,
            cycle_kwh=self._drying_cycle_kwh,
            cycle_cost=self._drying_cycle_cost,
            stage_durations=stage_durations,
        )
        self._drying_cycle_kwh = 0.0
        self._drying_cycle_cost = 0.0

        self._config[CONF_DRYING_OCCUPIED] = False
        new_options = {
            **self._entry.options,
            CONF_DRYING_OCCUPIED: False,
        }
        self.hass.config_entries.async_update_entry(self._entry, options=new_options)
        if journal is not None:
            await journal.close_open_drying_batch(cycle_id)
        return harvest_data

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
