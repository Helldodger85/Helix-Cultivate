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
    CONF_EM_DRYING_SENSORS,
    CONF_EM_GLOBAL_SENSORS,
    CONF_EM_ZONE1_SENSORS,
    CONF_EM_ZONE2_SENSORS,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_EXHAUST_FAN,
    CONF_EXHAUST_MIN_PCT,
    CONF_GROW_CAMERA,
    CONF_GROW_LIGHT,
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

        # ── Energy session start ──────────────────────────────────────────────
        self._session_start: datetime = dt_util.utcnow()
        self._cycle_kwh: float = 0.0
        self._cycle_cost: float = 0.0
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

    # ── Leaf VPD calculation ──────────────────────────────────────────────────

    def _calc_leaf_vpd(self, temp_c: float, rh_pct: float) -> float:
        """Calculate Leaf VPD [kPa] using configured leaf temperature offset."""
        import math
        offset = float(self._get(CONF_LEAF_TEMP_OFFSET_C, DEFAULT_LEAF_TEMP_OFFSET_C))
        t_leaf = temp_c + offset
        svp_leaf = 0.6108 * math.exp(17.27 * t_leaf / (t_leaf + 237.3))
        svp_air = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
        rh_frac = max(0.0, min(1.0, rh_pct / 100.0))
        vpd = svp_leaf - (rh_frac * svp_air)
        return max(0.0, vpd)

    # ── Lights state detection ────────────────────────────────────────────────

    def _lights_on(self) -> bool:
        """Return True if grow light entity is currently on."""
        light_id: Optional[str] = self._get(CONF_GROW_LIGHT)
        if not light_id:
            return False
        state = self.hass.states.get(light_id)
        return state is not None and state.state in ("on",)

    # ── DLI accumulation ─────────────────────────────────────────────────────

    def _accumulate_dli(self, interval_sec: float) -> None:
        """Accumulate DLI from PAR sensor or skip gracefully if absent."""
        dli_sensor_id: Optional[str] = self._get(CONF_DLI_SENSOR)
        if not dli_sensor_id or not self._lights_on():
            return
        ppfd = self._read_sensor(dli_sensor_id)
        if ppfd is None:
            return
        increment = ppfd * interval_sec / 1_000_000.0
        if self.data:
            self.data[NS_ENERGY]["dli_today_mol"] = (
                self.data[NS_ENERGY].get("dli_today_mol", 0.0) + increment
            )

    # ── Energy accumulation ───────────────────────────────────────────────────

    def _read_em_watts(self) -> float:
        """Sum instantaneous watt readings from all configured energy-monitor
        sensors across the zone1, zone2, drying, and global collapsed sensor
        lists. Returns 0.0 when no sensors are configured or all readings are
        unavailable.
        """
        total = 0.0
        for list_key in (
            CONF_EM_ZONE1_SENSORS,
            CONF_EM_ZONE2_SENSORS,
            CONF_EM_DRYING_SENSORS,
            CONF_EM_GLOBAL_SENSORS,
        ):
            entity_ids = self._get(list_key) or []
            for entity_id in entity_ids:
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
        """Accumulate cycle kWh via Riemann sum of EM sensor watts, then
        update cycle cost from the currently-active tariff rate.

        On the first tick since coordinator startup (or since a cycle reset),
        `_last_energy_tick` is None — the interval is skipped to avoid an
        artificially large accumulation from an undefined elapsed duration.
        """
        now = dt_util.utcnow()
        if self._last_energy_tick is not None:
            elapsed_h = (now - self._last_energy_tick).total_seconds() / 3600.0
            watts = self._read_em_watts()
            self._cycle_kwh += (watts * elapsed_h) / 1000.0
        self._last_energy_tick = now

        rate = self._current_tariff_rate()
        self._cycle_cost = self._cycle_kwh * rate
        if self.data:
            self.data[NS_ENERGY]["cycle_cost_usd"] = self._cycle_cost
            self.data[NS_ENERGY]["cycle_kwh"] = self._cycle_kwh

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
                offset = float(self._get(CONF_LEAF_TEMP_OFFSET_C, DEFAULT_LEAF_TEMP_OFFSET_C))
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

        # Reset cycle counters
        self._cycle_kwh = 0.0
        self._last_energy_tick = None
        if self.data:
            self.data[NS_ENERGY]["dli_today_mol"] = 0.0

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
