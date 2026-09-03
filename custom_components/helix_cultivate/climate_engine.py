"""Helix Cultivate — Climate Engine: control loops, watchdogs, PID/bang-bang."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.util import dt as dt_util

from .const import (
    ALGO_PID,
    CONF_ANTI_SHORT_CYCLE_MIN,
    CONF_DLI_SENSOR,
    CONF_LIGHT_LEAK_PPFD,
    CONF_LIGHT_LEAK_TRIGGER_MIN,
    DEFAULT_LIGHT_LEAK_PPFD,
    DEFAULT_LIGHT_LEAK_MIN,
    CONF_CONTROL_ALGORITHM,
    CONF_DRYING_AC,
    CONF_DRYING_CIRCULATION_FAN,
    CONF_DRYING_DEHUMIDIFIER,
    CONF_DRYING_ENABLED,
    CONF_DRYING_EXHAUST_FAN,
    CONF_DRYING_HEATER,
    CONF_DRYING_HUMIDITY_OFFSET,
    CONF_DRYING_HUMIDITY_SENSOR,
    CONF_DRYING_IS_REVERSE_CYCLE,
    CONF_DRYING_TEMP_OFFSET,
    CONF_DRYING_TEMP_SENSOR,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_EXHAUST_FAN,
    CONF_EXHAUST_MIN_PCT,
    CONF_HEATER_CUTOFF_C,
    CONF_LEAF_TEMP_OFFSET_C,
    CONF_LOWER_HUMIDITY_OFFSET,
    CONF_LOWER_TEMP_OFFSET,
    CONF_LUNG_HUMIDITY_OFFSET,
    CONF_LUNG_TEMP_OFFSET,
    CONF_MID_HUMIDITY_OFFSET,
    CONF_MID_TEMP_OFFSET,
    CONF_OUTDOOR_WEATHER_ENTITY,
    CONF_PRIMARY_HUMIDITY_OFFSET,
    CONF_PRIMARY_TEMP_OFFSET,
    CONF_SAFETY_HIGH_RH_PCT,
    CONF_SAFETY_HIGH_TEMP_C,
    CONF_SAFETY_LOW_RH_PCT,
    CONF_SAFETY_LOW_TEMP_C,
    CONF_THERMAL_RUNAWAY_C,
    CONF_TOPOLOGY,
    CONF_UPPER_HUMIDITY_OFFSET,
    CONF_UPPER_TEMP_OFFSET,
    CONF_ZONE1_AC,
    CONF_ZONE1_BACKUP_HEATER,
    CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C,
    CONF_ZONE1_DEHUMIDIFIER,
    CONF_ZONE1_HEATER,
    CONF_ZONE1_HUMIDIFIER,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE1_REVERSE_CYCLE,
    CONF_ZONE2_AC,
    CONF_ZONE2_DEHUMIDIFIER,
    CONF_ZONE2_HEATER,
    CONF_ZONE2_HUMIDIFIER,
    CONF_ZONE2_IS_REVERSE_CYCLE,
    CONF_ZONE2_REVERSE_CYCLE,
    DEFAULT_ANTI_SHORT_CYCLE_MIN,
    DEFAULT_BACKUP_HEATER_THRESHOLD_C,
    DEFAULT_EXHAUST_MIN_PCT,
    DEFAULT_EXHAUST_SAFE_FLOOR_PCT,
    DEFAULT_HEATER_CUTOFF_C,
    DEFAULT_LEAF_TEMP_OFFSET_C,
    DEFAULT_SAFETY_HIGH_RH_PCT,
    DEFAULT_SAFETY_HIGH_TEMP_C,
    DEFAULT_SAFETY_LOW_RH_PCT,
    DEFAULT_SAFETY_LOW_TEMP_C,
    DEFAULT_THERMAL_RUNAWAY_C,
    DRYING_CYCLE_EXHAUST_PCT,
    DRYING_LOCKED_RH_PCT,
    DRYING_LOCKED_TEMP_C,
    DRYING_TARGET_RH_PCT,
    DRYING_TARGET_TEMP_C,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FEEDFORWARD_PRECONDITIONING_MIN,
    LIGHTS_OFF_PURGE_DURATION_MIN,
    STAGE_DRYING,
    STRATIFICATION_RH_DELTA_PCT,
    STRATIFICATION_TEMP_DELTA_C,
    TOPOLOGY_COORDINATED,
)

if TYPE_CHECKING:
    from .coordinator import HelixCoordinator

_LOGGER = logging.getLogger(__name__)

# ── PID state per appliance (retained between engine calls via coordinator) ───
# Stored as {entity_key: {"integral": float, "prev_error": float, "last_ts": datetime}}
_PID_STATE: dict[str, dict[str, Any]] = {}

# ── Hysteresis deadbands ───────────────────────────────────────────────────────
TEMP_DEADBAND_C: float = 0.5    # ±0.5°C around temp setpoint
VPD_DEADBAND_KPA: float = 0.05  # ±0.05 kPa around VPD target
EXHAUST_PID_KP: float = 2.0
EXHAUST_PID_KI: float = 0.05
EXHAUST_PID_KD: float = 0.3

# ── Actuator interaction rules (Phase 9) ───────────────────────────────────────
SATURATION_DWELL_MIN: float = 8.0    # Minutes of continuous appliance runtime = saturated
VPD_ASSIST_STEP_C: float = 0.3       # Per-tick bias step applied to effective temp setpoint
VPD_ASSIST_MAX_BIAS_C: float = 1.5   # Maximum single-tick bias magnitude
THERMAL_PURGE_MARGIN_C: float = 1.5      # °C band below thermal_runaway_c where purge ramps
THERMAL_PURGE_SLOPE_TRIGGER: float = 0.5  # °C/min rising trend that activates purge earlier

# ── Reverse-cycle HVAC modes ──────────────────────────────────────────────────
HVAC_MODE_HEAT: str = "heat"
HVAC_MODE_COOL: str = "cool"
HVAC_MODE_OFF: str = "off"


# ────────────────────────────────────────────────────────────────────────────
# PID controller helper
# ────────────────────────────────────────────────────────────────────────────

def _pid_step(
    key: str,
    error: float,
    kp: float = 1.0,
    ki: float = 0.01,
    kd: float = 0.1,
    output_min: float = 0.0,
    output_max: float = 100.0,
    integral_clamp: float = 50.0,
) -> float:
    """Single PID step returning clamped output.

    State (integral, previous error, timestamp) is persisted in module-level
    _PID_STATE across engine calls to provide I and D terms.
    """
    now = dt_util.utcnow()
    state = _PID_STATE.setdefault(key, {"integral": 0.0, "prev_error": error, "last_ts": now})

    dt_secs = (now - state["last_ts"]).total_seconds()
    if dt_secs <= 0:
        dt_secs = 30.0  # default update interval

    integral = state["integral"] + error * dt_secs
    integral = max(-integral_clamp, min(integral_clamp, integral))

    derivative = (error - state["prev_error"]) / dt_secs

    output = kp * error + ki * integral + kd * derivative
    output = max(output_min, min(output_max, output))

    state["integral"] = integral
    state["prev_error"] = error
    state["last_ts"] = now

    return output


# ────────────────────────────────────────────────────────────────────────────
# Zone interlock — mutual exclusion enforcer
# ────────────────────────────────────────────────────────────────────────────

class ZoneInterlock:
    """Enforces per-zone mutual exclusion for heating/cooling and humidification.

    Rules (within a single zone):
    - heater_on XOR ac_on must always hold (discrete appliances)
    - humidifier_on XOR dehumidifier_on must always hold
    - reverse-cycle unit operates exclusively in one hvac_mode at a time

    Inter-zone concurrency is explicitly permitted.
    """

    def __init__(self, zone_label: str) -> None:
        self._zone = zone_label
        self._heater_on: bool = False
        self._ac_on: bool = False
        self._humid_on: bool = False
        self._dehumid_on: bool = False
        # Reverse-cycle current mode — None means off / unconfigured
        self._reverse_cycle_mode: Optional[str] = None

    def request_heat(self, on: bool) -> bool:
        if on and self._ac_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Heat ON request blocked — AC is already running (mutex).",
                self._zone,
            )
            return False
        self._heater_on = on
        return True

    def request_cool(self, on: bool) -> bool:
        if on and self._heater_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Cool ON request blocked — Heater is already running (mutex).",
                self._zone,
            )
            return False
        self._ac_on = on
        return True

    def request_humidify(self, on: bool) -> bool:
        if on and self._dehumid_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Humidify ON request blocked — Dehumidifier is already running (mutex).",
                self._zone,
            )
            return False
        self._humid_on = on
        return True

    def request_dehumidify(self, on: bool) -> bool:
        if on and self._humid_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Dehumidify ON request blocked — Humidifier is already running (mutex).",
                self._zone,
            )
            return False
        self._dehumid_on = on
        return True

    def request_reverse_cycle_mode(self, mode: Optional[str]) -> Optional[str]:
        """Set reverse-cycle hvac_mode. Returns the accepted mode or None if blocked.

        Blocks HEAT if discrete AC is already on; blocks COOL if discrete heater is on.
        """
        if mode == HVAC_MODE_HEAT and self._ac_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Reverse-cycle HEAT request blocked — discrete AC running (mutex).",
                self._zone,
            )
            return None
        if mode == HVAC_MODE_COOL and self._heater_on:
            _LOGGER.warning(
                "Helix Cultivate [%s]: Reverse-cycle COOL request blocked — discrete heater running (mutex).",
                self._zone,
            )
            return None
        self._reverse_cycle_mode = mode
        return mode

    @property
    def heater_on(self) -> bool:
        return self._heater_on

    @property
    def ac_on(self) -> bool:
        return self._ac_on

    @property
    def humid_on(self) -> bool:
        return self._humid_on

    @property
    def dehumid_on(self) -> bool:
        return self._dehumid_on

    @property
    def reverse_cycle_mode(self) -> Optional[str]:
        return self._reverse_cycle_mode


# ────────────────────────────────────────────────────────────────────────────
# Climate Engine
# ────────────────────────────────────────────────────────────────────────────

class ClimateEngine:
    """Stateless per-tick climate control engine.

    Instantiated fresh each coordinator update cycle. Persistent state
    (PID integrals, compressor timers, etc.) is stored on the coordinator.
    """

    def __init__(self, coordinator: "HelixCoordinator") -> None:
        self._coord = coordinator
        self._config: dict[str, Any] = coordinator._config
        self._z1 = ZoneInterlock("Zone1-LungRoom")
        self._z2 = ZoneInterlock("Zone2-Tent")
        # Light leak watchdog state — persists only for the duration of a night cycle
        self._light_leak_start: Optional[datetime] = None
        self._light_leak_alerted: bool = False

    # ── Config accessors ──────────────────────────────────────────────────────

    def _get(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def _exhaust_min_pct(self) -> float:
        return float(self._get(CONF_EXHAUST_MIN_PCT, DEFAULT_EXHAUST_MIN_PCT))

    def _heater_cutoff(self) -> float:
        return float(self._get(CONF_HEATER_CUTOFF_C, DEFAULT_HEATER_CUTOFF_C))

    def _thermal_runaway_threshold(self) -> float:
        return float(self._get(CONF_THERMAL_RUNAWAY_C, DEFAULT_THERMAL_RUNAWAY_C))

    def _anti_short_cycle_secs(self) -> float:
        return float(self._get(CONF_ANTI_SHORT_CYCLE_MIN, DEFAULT_ANTI_SHORT_CYCLE_MIN)) * 60.0

    def _use_pid(self) -> bool:
        return self._get(CONF_CONTROL_ALGORITHM, "bang_bang") == ALGO_PID

    def _topology(self) -> str:
        return self._get(CONF_TOPOLOGY, TOPOLOGY_COORDINATED)

    def _conditioning_room_enabled(self) -> bool:
        """Return True if the Conditioning Room module is active.

        Checks the explicit enable flag first (set by config/options flow),
        then falls back to topology for backward-compatibility with entries
        that pre-date the flag.
        """
        flag = self._get(CONF_ENABLE_CONDITIONING_ROOM)
        if flag is not None:
            return bool(flag)
        # Legacy fallback: coordinated topology implies conditioning room
        return self._topology() == TOPOLOGY_COORDINATED

    def _drying_environment_enabled(self) -> bool:
        """Return True if the Drying Environment (60/60) module is active."""
        flag = self._get(CONF_ENABLE_DRYING_ENVIRONMENT)
        if flag is not None:
            return bool(flag)
        # Legacy fallback: drying_enabled key
        return bool(self._get(CONF_DRYING_ENABLED, False))

    def _backup_heater_threshold(self) -> float:
        return float(self._get(CONF_ZONE1_BACKUP_HEATER_THRESHOLD_C, DEFAULT_BACKUP_HEATER_THRESHOLD_C))

    def _apply_sensor_offset(
        self,
        raw: Optional[float],
        temp_key: str,
        humidity_key: str,
        is_humidity: bool = False,
    ) -> Optional[float]:
        """Apply a ±offset calibration correction to a raw sensor reading.

        Returns None when raw is None (preserves null-safety throughout engine).
        Offsets default to 0.0 when not configured.
        """
        if raw is None:
            return None
        offset_key = humidity_key if is_humidity else temp_key
        offset = float(self._get(offset_key, 0.0))
        return raw + offset

    def _safety_check(
        self,
        temp: Optional[float],
        rh: Optional[float],
        zone_label: str,
    ) -> bool:
        """Return True if temp or RH is outside safety interlock ceilings."""
        if temp is not None:
            high_temp = float(self._get(CONF_SAFETY_HIGH_TEMP_C, DEFAULT_SAFETY_HIGH_TEMP_C))
            low_temp = float(self._get(CONF_SAFETY_LOW_TEMP_C, DEFAULT_SAFETY_LOW_TEMP_C))
            if temp >= high_temp or temp <= low_temp:
                _LOGGER.warning(
                    "Helix Cultivate [%s]: Safety interlock — temp %.1f°C outside [%.1f–%.1f°C]",
                    zone_label, temp, low_temp, high_temp,
                )
                return True
        if rh is not None:
            high_rh = float(self._get(CONF_SAFETY_HIGH_RH_PCT, DEFAULT_SAFETY_HIGH_RH_PCT))
            low_rh = float(self._get(CONF_SAFETY_LOW_RH_PCT, DEFAULT_SAFETY_LOW_RH_PCT))
            if rh >= high_rh or rh <= low_rh:
                _LOGGER.warning(
                    "Helix Cultivate [%s]: Safety interlock — RH %.1f%% outside [%.1f–%.1f%%]",
                    zone_label, rh, low_rh, high_rh,
                )
                return True
        return False

    # ── Compressor anti-short-cycle guard ─────────────────────────────────────

    def _compressor_allowed(self, appliance_key: str) -> bool:
        """Return True if the anti-short-cycle dwell has elapsed for this appliance."""
        last_off: Optional[datetime] = self._coord._last_compressor_off.get(appliance_key)
        if last_off is None:
            return True
        dwell = self._anti_short_cycle_secs()
        elapsed = (dt_util.utcnow() - last_off).total_seconds()
        if elapsed < dwell:
            _LOGGER.debug(
                "Helix Cultivate: anti-short-cycle blocking %s — %d/%d seconds elapsed",
                appliance_key,
                int(elapsed),
                int(dwell),
            )
            return False
        return True

    def _record_compressor_off(self, appliance_key: str) -> None:
        self._coord._last_compressor_off[appliance_key] = dt_util.utcnow()

    # ── Appliance service calls ───────────────────────────────────────────────

    async def _set_switch(
        self, entity_id: Optional[str], on: bool, role: str = "unknown"
    ) -> None:
        """Turn a switch or climate entity on/off. Safely no-ops if entity_id is None.

        `role` identifies the appliance function (e.g. "zone1_heater") for the
        appliance dropout watchdog (Phase 10B) — tracked continuously
        unavailable entities raise a persistent notification after 5 minutes.
        """
        if not entity_id:
            return
        if self._coord._check_appliance_dropout(role, entity_id):
            return
        state = self._coord.hass.states.get(entity_id)
        if state is None:
            return
        domain = entity_id.split(".")[0]
        service = "turn_on" if on else "turn_off"
        try:
            await self._coord.hass.services.async_call(
                domain, service, {"entity_id": entity_id}
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to call %s.%s on %s: %s",
                domain, service, entity_id, exc,
            )

    async def _set_reverse_cycle(
        self, entity_id: Optional[str], mode: Optional[str]
    ) -> None:
        """Set a climate entity to the specified hvac_mode (heat / cool / off).

        Gracefully no-ops when entity_id is None or entity is unavailable.
        Uses climate.set_hvac_mode for reverse-cycle heat pumps and split systems.
        """
        if not entity_id or not mode:
            if entity_id:
                # mode is None — turn off the unit
                state = self._coord.hass.states.get(entity_id)
                if state is None or state.state == "unavailable":
                    return
                try:
                    await self._coord.hass.services.async_call(
                        "climate", "set_hvac_mode",
                        {"entity_id": entity_id, "hvac_mode": HVAC_MODE_OFF},
                    )
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.warning(
                        "Helix Cultivate: failed to set reverse-cycle %s to off: %s",
                        entity_id, exc,
                    )
            return

        state = self._coord.hass.states.get(entity_id)
        if state is None or state.state == "unavailable":
            return

        # Only call the service if the mode actually needs to change
        current_mode = state.state  # climate entity state IS the hvac_mode string
        if current_mode == mode:
            return

        try:
            await self._coord.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": entity_id, "hvac_mode": mode},
            )
            _LOGGER.debug(
                "Helix Cultivate: reverse-cycle %s → %s (was %s)",
                entity_id, mode, current_mode,
            )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to set reverse-cycle %s to %s: %s",
                entity_id, mode, exc,
            )

    async def _set_fan_pct(self, entity_id: Optional[str], pct: float) -> None:
        if not entity_id:
            return
        state = self._coord.hass.states.get(entity_id)
        if state is None:
            return
        domain = entity_id.split(".")[0]
        clamped = max(0.0, min(100.0, pct))
        try:
            if domain == "fan":
                if clamped <= 0:
                    await self._coord.hass.services.async_call("fan", "turn_off", {"entity_id": entity_id})
                else:
                    await self._coord.hass.services.async_call(
                        "fan", "set_percentage",
                        {"entity_id": entity_id, "percentage": int(clamped)},
                    )
            elif domain == "switch":
                await self._coord.hass.services.async_call(
                    "switch", "turn_on" if clamped >= 50 else "turn_off",
                    {"entity_id": entity_id},
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to set fan %s to %.0f%%: %s",
                entity_id, clamped, exc,
            )

    async def _set_light_intensity(self, entity_id: Optional[str], pct: float) -> None:
        if not entity_id:
            return
        state = self._coord.hass.states.get(entity_id)
        if state is None:
            return
        domain = entity_id.split(".")[0]
        try:
            if domain == "light":
                brightness = int(pct / 100.0 * 255)
                if pct <= 0:
                    await self._coord.hass.services.async_call("light", "turn_off", {"entity_id": entity_id})
                else:
                    await self._coord.hass.services.async_call(
                        "light", "turn_on",
                        {"entity_id": entity_id, "brightness": brightness},
                    )
            elif domain == "switch":
                await self._coord.hass.services.async_call(
                    "switch", "turn_on" if pct >= 50 else "turn_off",
                    {"entity_id": entity_id},
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Helix Cultivate: failed to set light %s to %.0f%%: %s",
                entity_id, pct, exc,
            )

    # ── Outdoor temperature helper ────────────────────────────────────────────

    def _outdoor_temp_c(self) -> Optional[float]:
        """Return the current outdoor temperature from the weather entity, or None."""
        weather_id: Optional[str] = self._get(CONF_OUTDOOR_WEATHER_ENTITY)
        if not weather_id:
            return None
        state = self._coord.hass.states.get(weather_id)
        if state is None:
            return None
        try:
            temp = state.attributes.get("temperature")
            return float(temp) if temp is not None else None
        except (TypeError, ValueError):
            return None

    # ── Thermal runaway guard ─────────────────────────────────────────────────

    async def _handle_thermal_runaway(self, canopy_temp: float) -> bool:
        """Check and act on canopy thermal runaway. Returns True if triggered."""
        threshold = self._thermal_runaway_threshold()
        if canopy_temp < threshold:
            return False

        _LOGGER.warning(
            "Helix Cultivate: THERMAL RUNAWAY DETECTED — canopy %.1f°C >= %.1f°C threshold. "
            "Dimming light to 0%%, forcing exhaust to 100%%.",
            canopy_temp,
            threshold,
        )

        grow_light = self._get("grow_light")
        await self._set_light_intensity(grow_light, 0.0)
        self._coord.light_intensity_pct = 0.0

        # Kill all Zone 1 heaters (discrete + backup)
        await self._set_switch(self._get(CONF_ZONE1_HEATER), False, role="zone1_heater")
        await self._set_switch(self._get(CONF_ZONE1_BACKUP_HEATER), False, role="zone1_backup_heater")
        await self._set_switch(self._get(CONF_ZONE2_HEATER), False, role="zone2_heater")
        # Turn off both reverse-cycle units
        await self._set_reverse_cycle(self._get(CONF_ZONE1_REVERSE_CYCLE), None)
        await self._set_reverse_cycle(self._get(CONF_ZONE2_REVERSE_CYCLE), None)

        await self._coord._notify_critical(
            title="Helix Cultivate — Thermal Runaway Alert",
            message=(
                f"Canopy temperature ({canopy_temp:.1f}°C) exceeded thermal runaway "
                f"guard ({threshold:.1f}°C). Grow light cut to 0%, exhaust forced to 100%. "
                "All heaters killed. Check environment immediately."
            ),
            level="critical",
        )

        # ── Base Under Siege notification (idempotent, separate ID) ───────────
        await self._coord._notify_critical(
            title="⚠️ Helix Cultivate — Base Under Siege",
            message=(
                f"Warning: Base Under Siege. Thermal thresholds breached — "
                f"canopy {canopy_temp:.1f}°C exceeds {threshold:.1f}°C ceiling. "
                "All cooling engaged. Immediate inspection required."
            ),
            level="critical",
        )

        return True

    # ── Light leak watchdog ───────────────────────────────────────────────────

    async def _check_light_leak(self) -> None:
        """Night-time PAR sentinel.

        If a PAR/DLI sensor detects light above threshold for longer than the
        configured trigger duration during the night phase, fires a persistent
        HA notification. Only alerts once per night cycle.
        """
        from datetime import datetime, timezone as _tz  # local import to avoid circular

        dli_entity: Optional[str] = self._get(CONF_DLI_SENSOR)
        if not dli_entity:
            return  # no PAR sensor mapped — silent no-op

        if self._light_leak_alerted:
            return  # already fired this night cycle

        threshold_ppfd: float = float(self._get(CONF_LIGHT_LEAK_PPFD, DEFAULT_LIGHT_LEAK_PPFD))
        trigger_min: float = float(self._get(CONF_LIGHT_LEAK_TRIGGER_MIN, DEFAULT_LIGHT_LEAK_MIN))

        try:
            raw = self._coord.hass.states.get(dli_entity)
            if raw is None or raw.state in ("unavailable", "unknown"):
                self._light_leak_start = None
                return

            par_value: float = float(raw.state)
        except (ValueError, AttributeError):
            self._light_leak_start = None
            return

        now: datetime = datetime.now(_tz.utc)

        if par_value <= threshold_ppfd:
            # Light gone — reset detection window
            self._light_leak_start = None
            return

        # PAR above threshold during night
        if self._light_leak_start is None:
            self._light_leak_start = now
            _LOGGER.debug(
                "Helix Cultivate: light leak detection started — PAR %.1f μmol > %.1f threshold",
                par_value,
                threshold_ppfd,
            )
            return

        elapsed_min: float = (now - self._light_leak_start).total_seconds() / 60.0
        if elapsed_min >= trigger_min:
            _LOGGER.critical(
                "Helix Cultivate: CRITICAL — Light Leak Detected! PAR %.1f μmol sustained for %.1f min during night.",
                par_value,
                elapsed_min,
            )
            await self._coord._notify_critical(
                title="🔴 Helix Cultivate — Critical: Light Leak",
                message=(
                    f"CRITICAL: Light Leak Detected in Canopy. "
                    f"PAR sensor ({dli_entity}) reading {par_value:.1f} μmol "
                    f"for {elapsed_min:.0f} minutes during the night cycle. "
                    "Inspect your grow space immediately."
                ),
                level="critical",
            )
            self._light_leak_alerted = True

    # ── Zone 1 heater over-temp cutoff ────────────────────────────────────────

    async def _check_zone1_heater_cutoff(self, canopy_temp: Optional[float]) -> bool:
        """Kill Zone 1 heaters if canopy temp exceeds cutoff. Returns True if cut."""
        if canopy_temp is None:
            return False
        cutoff = self._heater_cutoff()
        if canopy_temp >= cutoff:
            heater_id = self._get(CONF_ZONE1_HEATER)
            backup_id = self._get(CONF_ZONE1_BACKUP_HEATER)
            if heater_id:
                _LOGGER.warning(
                    "Helix Cultivate: Zone 1 heater over-temp cutoff triggered — "
                    "%.1f°C >= %.1f°C. Killing heater %s.",
                    canopy_temp, cutoff, heater_id,
                )
                await self._set_switch(heater_id, False, role="zone1_heater")
            if backup_id:
                _LOGGER.warning(
                    "Helix Cultivate: Zone 1 backup heater over-temp cutoff triggered — "
                    "%.1f°C >= %.1f°C. Killing backup heater %s.",
                    canopy_temp, cutoff, backup_id,
                )
                await self._set_switch(backup_id, False, role="zone1_backup_heater")
            return True
        return False

    # ── Feedforward MPC via outdoor weather entity ────────────────────────────

    def _feedforward_adjustment(self) -> float:
        """Return a feedforward exhaust adjustment based on outdoor forecast.

        Returns 0.0 if no weather entity is configured (graceful bypass).
        Returns +/- percentage points to add to the base exhaust signal.
        """
        weather_id: Optional[str] = self._get(CONF_OUTDOOR_WEATHER_ENTITY)
        if not weather_id:
            return 0.0

        state = self._coord.hass.states.get(weather_id)
        if state is None:
            return 0.0

        try:
            forecast = state.attributes.get("forecast", [])
            if not forecast or len(forecast) < 2:
                return 0.0
            future_temp = float(forecast[0].get("temperature", 0))
            current_temp = float(state.attributes.get("temperature", future_temp))
            delta = future_temp - current_temp
            # Scale: ±5°C forecast shift → ±10% exhaust pre-correction
            correction = max(-15.0, min(15.0, delta * 2.0))
            _LOGGER.debug(
                "Helix Cultivate: feedforward MPC: outdoor delta=%.1f°C → exhaust correction=%.1f%%",
                delta,
                correction,
            )
            return correction
        except (TypeError, ValueError, KeyError):
            return 0.0

    # ── Exhaust fan control ───────────────────────────────────────────────────

    async def _control_exhaust(
        self,
        leaf_vpd: Optional[float],
        canopy_temp: Optional[float],
        upper_enthalpy: Optional[float],
        lung_enthalpy: Optional[float],
        sensor_dropout: bool,
        lights_on: bool,
        thermal_runaway: bool,
    ) -> float:
        """Compute and apply exhaust fan percentage. Returns the applied %."""
        exhaust_id: Optional[str] = self._get(CONF_EXHAUST_FAN)
        min_pct = self._exhaust_min_pct()

        # ── Hard overrides ────────────────────────────────────────────────────
        if thermal_runaway:
            await self._set_fan_pct(exhaust_id, 100.0)
            return 100.0

        if sensor_dropout:
            await self._set_fan_pct(exhaust_id, float(DEFAULT_EXHAUST_SAFE_FLOOR_PCT))
            return float(DEFAULT_EXHAUST_SAFE_FLOOR_PCT)

        # ── Lights-off dehumidification purge ─────────────────────────────────
        purge_until = self._coord._lights_off_purge_until
        if purge_until is not None and dt_util.utcnow() < purge_until:
            purge_pct = min(100.0, min_pct + 40.0)
            await self._set_fan_pct(exhaust_id, purge_pct)
            return purge_pct

        # Detect lights → off transition to start purge
        if not lights_on and self._coord._lights_state_prev is True:
            self._coord._lights_off_purge_until = dt_util.utcnow() + timedelta(
                minutes=LIGHTS_OFF_PURGE_DURATION_MIN
            )
            _LOGGER.info("Helix Cultivate: Lights-off dehumidification purge started.")

        # ── Base exhaust calculation ───────────────────────────────────────────
        topology = self._topology()
        base_pct = min_pct

        if topology == TOPOLOGY_COORDINATED and upper_enthalpy is not None and lung_enthalpy is not None:
            delta_h = upper_enthalpy - lung_enthalpy
            if self._use_pid():
                base_pct = _pid_step(
                    "exhaust_enthalpy",
                    error=delta_h,
                    kp=EXHAUST_PID_KP,
                    ki=EXHAUST_PID_KI,
                    kd=EXHAUST_PID_KD,
                    output_min=min_pct,
                    output_max=100.0,
                )
            else:
                if delta_h > 2.0:
                    base_pct = 75.0
                elif delta_h > 1.0:
                    base_pct = 50.0
                elif delta_h > 0.0:
                    base_pct = 30.0
                else:
                    base_pct = min_pct
        elif leaf_vpd is not None:
            vpd_min = getattr(
                self._coord, "vpd_target_min", self._coord.vpd_target - VPD_DEADBAND_KPA
            )
            vpd_max = getattr(
                self._coord, "vpd_target_max", self._coord.vpd_target + VPD_DEADBAND_KPA
            )
            vpd_error = leaf_vpd - ((vpd_min + vpd_max) / 2.0)
            pre_dehumidify, _pre_humid, _slope, _proj = self._vpd_predictive_flags(leaf_vpd)
            if self._use_pid():
                base_pct = _pid_step(
                    "exhaust_vpd",
                    error=vpd_error,
                    kp=EXHAUST_PID_KP,
                    ki=EXHAUST_PID_KI,
                    kd=EXHAUST_PID_KD,
                    output_min=min_pct,
                    output_max=100.0,
                )
            else:
                if leaf_vpd > vpd_max + 0.10:
                    base_pct = 65.0
                elif leaf_vpd > vpd_max or pre_dehumidify:
                    base_pct = 40.0
                else:
                    base_pct = min_pct

        # ── Feedforward MPC correction ─────────────────────────────────────────
        ff_correction = self._feedforward_adjustment()
        final_pct = max(min_pct, min(100.0, base_pct + ff_correction))

        # ── Thermal purge floor — sits below the hard thermal runaway 100% cutoff
        if canopy_temp is not None:
            purge_floor = self._thermal_purge_pct(canopy_temp)
            if purge_floor > 0.0:
                final_pct = max(final_pct, purge_floor)
                _LOGGER.debug(
                    "Helix Cultivate: thermal purge floor %.1f%% applied (canopy=%.1f°C)",
                    purge_floor,
                    canopy_temp,
                )

        await self._set_fan_pct(exhaust_id, final_pct)
        return final_pct

    # ── Bang-bang temperature control ────────────────────────────────────────

    def _bang_bang_temp(
        self,
        current_temp: Optional[float],
        setpoint_override: Optional[float] = None,
    ) -> tuple[bool, bool]:
        """Return (want_heat, want_cool) from bang-bang hysteresis.

        `setpoint_override` (Phase 9C VPD-assist bias) takes precedence over
        `self._coord.temp_setpoint` when provided — used to nudge the effective
        temperature target when a humidifier/dehumidifier is saturated.
        """
        if current_temp is None:
            return False, False
        setpoint = setpoint_override if setpoint_override is not None else self._coord.temp_setpoint
        if current_temp < setpoint - TEMP_DEADBAND_C:
            return True, False
        if current_temp > setpoint + TEMP_DEADBAND_C:
            return False, True
        return False, False

    # ── Saturation tracking (Phase 9B) ───────────────────────────────────────

    def _is_saturated(self, zone_label: str, appliance: str) -> bool:
        """Return True if the named appliance has been continuously ON for at
        least SATURATION_DWELL_MIN minutes AND the VPD trend is not improving
        in the direction that appliance is meant to drive it.
        """
        if appliance == "dehumidifier":
            since = self._coord._dehumid_on_since.get(zone_label)
            slope, _ = self._vpd_trend()
            trend_improving = slope is not None and slope > 0.005
        elif appliance == "humidifier":
            since = self._coord._humid_on_since.get(zone_label)
            slope, _ = self._vpd_trend()
            trend_improving = slope is not None and slope < -0.005
        else:
            return False

        if since is None:
            return False
        elapsed_min = (dt_util.utcnow() - since).total_seconds() / 60.0
        return elapsed_min >= SATURATION_DWELL_MIN and not trend_improving

    # ── VPD-assist temperature bias (Phase 9C) ───────────────────────────────

    def _vpd_assist_bias(self, zone_label: str, leaf_vpd: Optional[float]) -> float:
        """Return a stateless flat temp setpoint nudge (kPa → °C assist).

        If dehumidifier is saturated and VPD is still too low (too wet):
            nudge temp UP by VPD_ASSIST_STEP_C (warmer air holds more moisture
            → lowers RH → raises VPD)
        If humidifier is saturated and VPD is still too high (too dry):
            nudge temp DOWN by VPD_ASSIST_STEP_C

        Recomputed fresh every tick — no accumulation, no state held here.
        """
        if leaf_vpd is None:
            return 0.0
        vpd_min = getattr(
            self._coord, "vpd_target_min", self._coord.vpd_target - VPD_DEADBAND_KPA
        )
        vpd_max = getattr(
            self._coord, "vpd_target_max", self._coord.vpd_target + VPD_DEADBAND_KPA
        )

        if leaf_vpd < vpd_min and self._is_saturated(zone_label, "humidifier"):
            return -VPD_ASSIST_STEP_C
        if leaf_vpd > vpd_max and self._is_saturated(zone_label, "dehumidifier"):
            return +VPD_ASSIST_STEP_C
        return 0.0

    # ── Temperature trend + thermal purge (Phase 9D) ─────────────────────────

    def _temp_trend(self) -> tuple[Optional[float], Optional[float]]:
        """OLS linear regression over temp history → (slope °C/min, projected 3min out)."""
        hist = list(self._coord._temp_history)
        if len(hist) < 3:
            return None, None
        t0 = hist[0][0]
        xs = [(t - t0).total_seconds() / 60.0 for t, _ in hist]
        ys = [v for _, v in hist]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0:
            return None, None
        slope = num / den
        projected = ys[-1] + slope * 3.0
        return slope, projected

    def _thermal_purge_pct(self, canopy_temp: float) -> float:
        """Return a proportional exhaust floor (50-100%) when temp approaches
        thermal_runaway_c. Sits below the existing hard 100% runaway cutoff.

        Activation:
          - canopy_temp > (thermal_runaway_c - THERMAL_PURGE_MARGIN_C), OR
          - projected temp (3min) > (thermal_runaway_c - THERMAL_PURGE_MARGIN_C)
            AND slope > THERMAL_PURGE_SLOPE_TRIGGER

        Output: 0.0 if inactive; linear ramp 50.0->100.0 across the margin band.
        """
        runaway_c = float(
            self._coord._config.get(CONF_THERMAL_RUNAWAY_C, DEFAULT_THERMAL_RUNAWAY_C)
        )
        purge_start = runaway_c - THERMAL_PURGE_MARGIN_C
        slope, projected = self._temp_trend()

        temp_for_ramp = canopy_temp
        if (
            slope is not None
            and slope > THERMAL_PURGE_SLOPE_TRIGGER
            and projected is not None
            and projected > purge_start
        ):
            temp_for_ramp = max(canopy_temp, projected)

        if temp_for_ramp <= purge_start:
            return 0.0

        t = (temp_for_ramp - purge_start) / THERMAL_PURGE_MARGIN_C
        return 50.0 + 50.0 * min(1.0, t)

    # ── Bang-bang VPD/humidity control ───────────────────────────────────────

    def _vpd_trend(self) -> tuple[Optional[float], Optional[float]]:
        """Simple OLS linear regression over VPD history → (slope kPa/min, projected 3min out).

        Returns (None, None) when fewer than 3 samples are available (deque
        holds up to 6 samples across a 3-minute window at 30s poll interval).
        """
        hist = list(self._coord._vpd_history)
        if len(hist) < 3:
            return None, None
        t0 = hist[0][0]
        xs = [(t - t0).total_seconds() / 60.0 for t, _ in hist]
        ys = [v for _, v in hist]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0:
            return None, None
        slope = num / den  # kPa per minute
        projected = ys[-1] + slope * 3.0
        return slope, projected

    def _vpd_predictive_flags(
        self, leaf_vpd: Optional[float]
    ) -> tuple[bool, bool, Optional[float], Optional[float]]:
        """Compute (pre_dehumidify, pre_humidify, slope, projected) for VPD control.

        Combines the current reading against the day/night range with a
        trend-based early-engagement signal so the climate engine begins
        correcting before the boundary is actually crossed.
        """
        slope, projected = self._vpd_trend()
        vpd_min = getattr(
            self._coord, "vpd_target_min", self._coord.vpd_target - VPD_DEADBAND_KPA
        )
        vpd_max = getattr(
            self._coord, "vpd_target_max", self._coord.vpd_target + VPD_DEADBAND_KPA
        )

        pre_dehumidify = leaf_vpd is not None and (
            leaf_vpd >= vpd_max
            or (projected is not None and projected >= vpd_max and slope is not None and slope > 0.015)
        )
        pre_humidify = leaf_vpd is not None and (
            leaf_vpd <= vpd_min
            or (projected is not None and projected <= vpd_min and slope is not None and slope < -0.015)
        )
        return pre_dehumidify, pre_humidify, slope, projected

    def _bang_bang_vpd(
        self, leaf_vpd: Optional[float]
    ) -> tuple[bool, bool]:
        """Return (want_humidify, want_dehumidify) from trend-aware VPD bang-bang.

        Uses the coordinator's day/night VPD range (vpd_target_min/max) when
        available, falling back to a symmetric deadband around vpd_target for
        backward compatibility with coordinators that predate Phase 5.
        A predictive dVPD/dt trend (Phase 6) allows early engagement before
        the boundary is crossed when the reading is trending toward it fast.
        """
        if leaf_vpd is None:
            return False, False
        pre_dehumidify, pre_humidify, _, _ = self._vpd_predictive_flags(leaf_vpd)
        # VPD too HIGH (above/trending above range) → air too dry → humidify
        if pre_dehumidify:
            return True, False
        # VPD too LOW (below/trending below range) → air too wet → dehumidify
        if pre_humidify:
            return False, True
        return False, False

    # ── Reverse-cycle appliance control ──────────────────────────────────────

    async def _control_reverse_cycle(
        self,
        zone: ZoneInterlock,
        zone_label: str,
        entity_id: Optional[str],
        want_heat: bool,
        want_cool: bool,
    ) -> Optional[str]:
        """Drive a reverse-cycle climate unit based on heat/cool demand.

        Returns the hvac_mode string that was applied, or None if not configured.

        Logic:
        - If heat is wanted → request HEAT mode (blocked by interlock if discrete AC is on)
        - If cool is wanted → request COOL mode (blocked if discrete heater is on)
        - Neither → OFF (or remains at current mode without unnecessary re-commands)

        Anti-short-cycle is applied to the compressor start — the reverse-cycle unit
        itself manages internal compressor cycling; we only apply HA-side timing to
        prevent rapid hvac_mode flips (heat → cool → heat) that could stress the unit.
        """
        if not entity_id:
            return None

        if want_heat and not want_cool:
            if not self._compressor_allowed(f"{zone_label}_rc_heat"):
                # Cannot flip yet — return current mode to avoid desync
                state = self._coord.hass.states.get(entity_id)
                return state.state if state else None
            accepted = zone.request_reverse_cycle_mode(HVAC_MODE_HEAT)
            await self._set_reverse_cycle(entity_id, accepted or HVAC_MODE_OFF)
            if accepted == HVAC_MODE_HEAT:
                _LOGGER.debug(
                    "Helix Cultivate [%s]: Reverse-cycle → HEAT (demand)", zone_label
                )
            return accepted or HVAC_MODE_OFF

        if want_cool and not want_heat:
            if not self._compressor_allowed(f"{zone_label}_rc_cool"):
                state = self._coord.hass.states.get(entity_id)
                return state.state if state else None
            accepted = zone.request_reverse_cycle_mode(HVAC_MODE_COOL)
            await self._set_reverse_cycle(entity_id, accepted or HVAC_MODE_OFF)
            if accepted == HVAC_MODE_COOL:
                _LOGGER.debug(
                    "Helix Cultivate [%s]: Reverse-cycle → COOL (demand)", zone_label
                )
            # Record compressor-off timestamp when we flip from a previous heat cycle
            prev_mode = zone.reverse_cycle_mode
            if prev_mode == HVAC_MODE_HEAT:
                self._record_compressor_off(f"{zone_label}_rc_heat")
            return accepted or HVAC_MODE_OFF

        # No thermal demand — turn off if currently running
        prev_mode = zone.reverse_cycle_mode
        if prev_mode in (HVAC_MODE_HEAT, HVAC_MODE_COOL):
            self._record_compressor_off(f"{zone_label}_rc_{prev_mode}")
        accepted = zone.request_reverse_cycle_mode(None)
        await self._set_reverse_cycle(entity_id, None)
        return HVAC_MODE_OFF

    # ── Zone 1 backup heater staging ─────────────────────────────────────────

    async def _stage_backup_heater(
        self,
        current_temp: Optional[float],
        lung_temp: Optional[float],
        primary_heat_on: bool,
        primary_rc_mode: Optional[str],
    ) -> bool:
        """Stage the Zone 1 backup heater based on outdoor temp and primary heat demand.

        Backup heater stages on when ALL of the following are true:
        1. A backup heater entity is configured
        2. The outdoor temperature is below the user-defined threshold
        3. The primary heat source (discrete heater OR reverse-cycle in HEAT mode) is
           already running (demand confirmed) AND the zone temp is still below setpoint
           minus a tighter deadband — i.e. the primary source is "falling behind"

        Returns True if backup heater was turned on.
        """
        backup_id: Optional[str] = self._get(CONF_ZONE1_BACKUP_HEATER)
        if not backup_id:
            return False

        # ── Condition 1: outdoor temp below threshold ──────────────────────────
        outdoor_temp = self._outdoor_temp_c()
        threshold = self._backup_heater_threshold()

        outdoor_below_threshold = outdoor_temp is not None and outdoor_temp < threshold

        if not outdoor_below_threshold:
            # Outdoor temperature is acceptable — backup heater not needed
            await self._set_switch(backup_id, False, role="zone1_backup_heater")
            return False

        # ── Condition 2: primary heat source is active and falling behind ───────
        # "Falling behind" = primary demand is on AND zone temp is still well below setpoint
        setpoint = self._coord.temp_setpoint
        reference_temp = lung_temp if lung_temp is not None else current_temp

        primary_heat_active = primary_heat_on or (primary_rc_mode == HVAC_MODE_HEAT)

        if reference_temp is None or not primary_heat_active:
            await self._set_switch(backup_id, False, role="zone1_backup_heater")
            return False

        # Tighter deadband for backup staging — only kick in if primary is clearly insufficient
        falling_behind = reference_temp < (setpoint - TEMP_DEADBAND_C * 2.0)

        if falling_behind:
            _LOGGER.info(
                "Helix Cultivate [Zone1]: Backup heater staging ON — "
                "outdoor=%.1f°C (threshold=%.1f°C), zone=%.1f°C (setpoint=%.1f°C).",
                outdoor_temp,
                threshold,
                reference_temp,
                setpoint,
            )
            await self._set_switch(backup_id, True, role="zone1_backup_heater")
            return True
        else:
            await self._set_switch(backup_id, False, role="zone1_backup_heater")
            return False

    # ── Zone appliance control ────────────────────────────────────────────────

    async def _control_zone(
        self,
        zone: ZoneInterlock,
        zone_label: str,
        current_temp: Optional[float],
        leaf_vpd: Optional[float],
        heater_id: Optional[str],
        ac_id: Optional[str],
        humid_id: Optional[str],
        dehumid_id: Optional[str],
        is_reverse_cycle: bool = False,
        reverse_cycle_id: Optional[str] = None,
        enable_heat_cutoff: bool = False,
    ) -> Optional[str]:
        """Evaluate and apply appliance states for a single zone.

        HVAC model:
        - is_reverse_cycle=False (default):
            ac_id   → discrete cooler (switch / relay driven via turn_on/off)
            heater_id → discrete heater (switch / relay)
        - is_reverse_cycle=True:
            ac_id   → unified heat pump (driven via climate.set_hvac_mode)
                       This entity IS the reverse-cycle entity.
            heater_id → secondary / backup heating stage (staged when primary
                        heat is active but zone is still falling behind setpoint)

        A separate explicit reverse_cycle_id (legacy config) is also honoured
        alongside the new is_reverse_cycle pattern; both are checked.

        Mutual exclusion is enforced by the ZoneInterlock instance.
        Anti-short-cycle dwell is applied to compressor appliances.

        Returns the hvac_mode string applied to the reverse-cycle unit (or None).
        """
        bias = self._vpd_assist_bias(zone_label, leaf_vpd)
        effective_setpoint = self._coord.temp_setpoint + max(
            -VPD_ASSIST_MAX_BIAS_C, min(VPD_ASSIST_MAX_BIAS_C, bias)
        )
        want_heat, want_cool = self._bang_bang_temp(
            current_temp, setpoint_override=effective_setpoint
        )
        want_humid, want_dehumid = self._bang_bang_vpd(leaf_vpd)

        # ── Thermal cutoffs ────────────────────────────────────────────────────
        if enable_heat_cutoff and current_temp is not None:
            cutoff = self._heater_cutoff()
            if current_temp >= cutoff:
                want_heat = False

        # ── Resolve which entity drives reverse-cycle ──────────────────────────
        # When is_reverse_cycle=True the AC entity IS the heat pump.
        # An explicit reverse_cycle_id (legacy) takes precedence if set.
        effective_rc_id: Optional[str] = reverse_cycle_id
        effective_discrete_ac_id: Optional[str] = None
        effective_heater_id: Optional[str] = heater_id
        effective_backup_heater_id: Optional[str] = None

        if is_reverse_cycle and ac_id and not reverse_cycle_id:
            # AC entity becomes the reverse-cycle unit
            effective_rc_id = ac_id
            # Heater entity becomes the backup
            effective_backup_heater_id = heater_id
            effective_heater_id = None  # no discrete heater in this path
            effective_discrete_ac_id = None
        else:
            effective_discrete_ac_id = ac_id

        # ── Anti-short-cycle for compressor appliances ─────────────────────────
        if want_cool and not self._compressor_allowed(f"{zone_label}_ac"):
            want_cool = False
        if want_dehumid and not self._compressor_allowed(f"{zone_label}_dehumid"):
            want_dehumid = False

        # ── Discrete appliance interlock ───────────────────────────────────────
        zone.request_heat(want_heat if effective_heater_id else False)
        if not want_heat and zone.heater_on:
            zone.request_heat(False)

        cool_allowed = zone.request_cool(want_cool if effective_discrete_ac_id else False)
        if not want_cool and zone.ac_on:
            zone.request_cool(False)
            self._record_compressor_off(f"{zone_label}_ac")

        zone.request_humidify(want_humid)
        if not want_humid and zone.humid_on:
            zone.request_humidify(False)

        dehumid_allowed = zone.request_dehumidify(want_dehumid)
        if not want_dehumid and zone.dehumid_on:
            zone.request_dehumidify(False)
            self._record_compressor_off(f"{zone_label}_dehumid")

        # ── Reverse-cycle control (heat pump via hvac_mode) ────────────────────
        rc_mode = await self._control_reverse_cycle(
            zone=zone,
            zone_label=zone_label,
            entity_id=effective_rc_id,
            want_heat=want_heat,
            want_cool=want_cool,
        )

        # ── Issue discrete appliance service calls ─────────────────────────────
        await self._set_switch(effective_heater_id, zone.heater_on, role=f"{zone_label}_heater")
        await self._set_switch(effective_discrete_ac_id, zone.ac_on, role=f"{zone_label}_ac")
        await self._set_switch(humid_id, zone.humid_on, role=f"{zone_label}_humid")
        await self._set_switch(dehumid_id, zone.dehumid_on, role=f"{zone_label}_dehumid")

        # ── Saturation tracking (Phase 9A) ──────────────────────────────────────
        if zone.humid_on:
            if self._coord._humid_on_since.get(zone_label) is None:
                self._coord._humid_on_since[zone_label] = dt_util.utcnow()
        else:
            self._coord._humid_on_since[zone_label] = None

        if zone.dehumid_on:
            if self._coord._dehumid_on_since.get(zone_label) is None:
                self._coord._dehumid_on_since[zone_label] = dt_util.utcnow()
        else:
            self._coord._dehumid_on_since[zone_label] = None

        # ── Backup heater staging when is_reverse_cycle=True ──────────────────
        if is_reverse_cycle and effective_backup_heater_id:
            outdoor_temp = self._outdoor_temp_c()
            threshold = self._backup_heater_threshold()
            outdoor_cold = outdoor_temp is not None and outdoor_temp < threshold
            primary_heat_active = rc_mode == HVAC_MODE_HEAT

            if outdoor_cold and primary_heat_active and current_temp is not None:
                setpoint = self._coord.temp_setpoint
                falling_behind = current_temp < (setpoint - TEMP_DEADBAND_C * 2.0)
                if falling_behind:
                    _LOGGER.info(
                        "Helix Cultivate [%s]: Backup heater staging ON — "
                        "outdoor=%.1f°C (threshold=%.1f°C), zone=%.1f°C vs setpoint=%.1f°C.",
                        zone_label,
                        outdoor_temp,
                        threshold,
                        current_temp,
                        setpoint,
                    )
                    await self._set_switch(effective_backup_heater_id, True, role=f"{zone_label}_backup_heater")
                else:
                    await self._set_switch(effective_backup_heater_id, False, role=f"{zone_label}_backup_heater")
            else:
                await self._set_switch(effective_backup_heater_id, False, role=f"{zone_label}_backup_heater")

        return rc_mode

    # ── Drying zone control ───────────────────────────────────────────────────

    async def _control_drying_zone(
        self,
        drying_temp: Optional[float],
        drying_rh: Optional[float],
    ) -> None:
        """Execute the fixed 15.5°C / 60% RH drying zone control loop.

        The drying zone runs a locked 60/60 cure profile — temperature and
        humidity targets are fixed constants, not user-configurable setpoints.
        Gentle cyclic exhaust is applied to exchange air slowly without
        disturbing terpene development.

        HVAC follows the same is_reverse_cycle model as cultivation zones.
        """
        ac_id: Optional[str] = self._get(CONF_DRYING_AC)
        heater_id: Optional[str] = self._get(CONF_DRYING_HEATER)
        dehumid_id: Optional[str] = self._get(CONF_DRYING_DEHUMIDIFIER)
        exhaust_id: Optional[str] = self._get(CONF_DRYING_EXHAUST_FAN)
        circ_id: Optional[str] = self._get(CONF_DRYING_CIRCULATION_FAN)
        is_rc: bool = bool(self._get(CONF_DRYING_IS_REVERSE_CYCLE, False))

        # ── Stage-target integration with locked/unlocked branch (Phase 8) ─────
        # When the active grow stage is "drying" AND the operator has explicitly
        # unlocked custom profiles, derive the target temperature and RH from
        # the stage manager's day/night VPD range. Otherwise (locked, or not in
        # the drying stage) fall back to the fixed cure-profile constants.
        is_day = self._coord._lights_on()
        active_stage = self._coord.stage_manager.current_stage
        is_unlocked = self._coord.stage_manager.is_drying_unlocked()

        vpd_min, vpd_max = self._coord.stage_manager.current_vpd_range(is_day)

        if active_stage == STAGE_DRYING and is_unlocked:
            target_temp = self._coord.stage_manager.current_temp_anchor(is_day)
            offset = float(self._get(CONF_LEAF_TEMP_OFFSET_C, DEFAULT_LEAF_TEMP_OFFSET_C))
            svp_leaf = 0.6108 * math.exp(
                17.27 * (target_temp + offset) / (target_temp + offset + 237.3)
            )
            svp_air = 0.6108 * math.exp(17.27 * target_temp / (target_temp + 237.3))
            mid_vpd = (vpd_min + vpd_max) / 2.0
            rh_frac = max(0.0, min(1.0, (svp_leaf - mid_vpd) / svp_air)) if svp_air else 0.0
            target_rh = rh_frac * 100.0
        elif active_stage == STAGE_DRYING:
            # Locked: fixed cure profile values
            target_temp = DRYING_LOCKED_TEMP_C
            target_rh = DRYING_LOCKED_RH_PCT
        else:
            # Fallback to fixed constants when not in the drying stage
            target_temp = DRYING_TARGET_TEMP_C
            target_rh = DRYING_TARGET_RH_PCT

        # ── Bang-bang evaluation against resolved targets ──────────────────────
        want_heat: bool = False
        want_cool: bool = False
        want_dehumid: bool = False

        if drying_temp is not None:
            if drying_temp < target_temp - TEMP_DEADBAND_C:
                want_heat = True
            elif drying_temp > target_temp + TEMP_DEADBAND_C:
                want_cool = True

        # Trend-aware drying RH control (replaces flat drying_rh > target_rh + 3.0).
        # Uses the whole-space VPD trend (Phase 6) as an early-engagement signal —
        # a fast wetting trend across the facility often precedes a rise in the
        # drying room's own RH before the local sensor crosses the deadband.
        slope, projected = self._vpd_trend()
        pre_dehumid_dry = drying_rh is not None and (
            drying_rh > target_rh + 2.0
            or (
                projected is not None
                and projected < vpd_min
                and slope is not None
                and slope < -0.015
            )
        )
        if drying_rh is not None and (drying_rh > target_rh + 3.0 or pre_dehumid_dry):
            want_dehumid = True

        # ── Apply HVAC control ─────────────────────────────────────────────────
        if is_rc and ac_id:
            # AC entity is a heat pump — drive via hvac_mode
            if want_heat:
                await self._set_reverse_cycle(ac_id, HVAC_MODE_HEAT)
            elif want_cool:
                await self._set_reverse_cycle(ac_id, HVAC_MODE_COOL)
            else:
                await self._set_reverse_cycle(ac_id, None)
        else:
            # Discrete appliances
            await self._set_switch(heater_id, want_heat, role="drying_heater")
            await self._set_switch(ac_id, want_cool, role="drying_ac")

        # ── Dehumidifier ───────────────────────────────────────────────────────
        await self._set_switch(dehumid_id, want_dehumid, role="drying_dehumid")

        # ── Saturation tracking (Phase 9A) ──────────────────────────────────────
        if want_dehumid:
            if self._coord._dehumid_on_since.get("drying") is None:
                self._coord._dehumid_on_since["drying"] = dt_util.utcnow()
        else:
            self._coord._dehumid_on_since["drying"] = None

        # ── Gentle cyclic exhaust (fixed %) ────────────────────────────────────
        if exhaust_id:
            await self._set_fan_pct(exhaust_id, DRYING_CYCLE_EXHAUST_PCT)

        # ── Indirect circulation fan (always on when mapped) ───────────────────
        if circ_id:
            await self._set_fan_pct(circ_id, 40.0)

        _LOGGER.debug(
            "Helix Cultivate [DryingZone]: temp=%.1f°C (target=%.1f), "
            "rh=%.1f%% (target=%.1f) → heat=%s cool=%s dehumid=%s",
            drying_temp if drying_temp is not None else float("nan"),
            target_temp,
            drying_rh if drying_rh is not None else float("nan"),
            target_rh,
            want_heat,
            want_cool,
            want_dehumid,
        )

    # ── Stratification boost ──────────────────────────────────────────────────

    async def _check_stratification(
        self,
        upper_temp: Optional[float],
        lower_temp: Optional[float],
        upper_rh: Optional[float],
        lower_rh: Optional[float],
    ) -> None:
        """Boost lower and mid fans autonomously if canopy is stratified."""
        if upper_temp is None or lower_temp is None:
            return

        temp_delta = upper_temp - lower_temp  # positive = lower is colder
        rh_delta: Optional[float] = None
        if upper_rh is not None and lower_rh is not None:
            rh_delta = lower_rh - upper_rh  # positive = lower is wetter

        stratified = temp_delta >= STRATIFICATION_TEMP_DELTA_C or (
            rh_delta is not None and rh_delta >= STRATIFICATION_RH_DELTA_PCT
        )

        if stratified:
            _LOGGER.debug(
                "Helix Cultivate: Stratification detected (ΔT=%.1f°C, ΔRH=%s%%). "
                "Boosting lower/mid canopy fans.",
                temp_delta,
                f"{rh_delta:.1f}" if rh_delta is not None else "N/A",
            )
            for tier in [FAN_TIER_MID, FAN_TIER_LOWER]:
                current_speed = self._coord.get_fan_speed(tier)
                boosted = min(100.0, current_speed + 20.0)
                await self._coord._apply_fan_speed_to_tier(tier, boosted)

    # ── Main run method ───────────────────────────────────────────────────────

    async def run(
        self,
        upper_temp: Optional[float],
        upper_rh: Optional[float],
        mid_temp: Optional[float],
        mid_rh: Optional[float],
        lower_temp: Optional[float],
        lower_rh: Optional[float],
        lung_temp: Optional[float],
        lung_rh: Optional[float],
        leaf_vpd: Optional[float],
        upper_enthalpy: Optional[float],
        lung_enthalpy: Optional[float],
        sensor_dropout: bool,
        lights_on: bool,
    ) -> dict[str, Any]:
        """Execute one control cycle and return the resulting appliance state dict."""

        # ── Thermal runaway guard ──────────────────────────────────────────────
        canopy_temp = upper_temp  # primary canopy reference
        thermal_runaway = False
        if canopy_temp is not None:
            thermal_runaway = await self._handle_thermal_runaway(canopy_temp)

        # ── Zone 1 heater over-temp cutoff ────────────────────────────────────
        await self._check_zone1_heater_cutoff(canopy_temp)

        # ── Exhaust fan ───────────────────────────────────────────────────────
        exhaust_pct = await self._control_exhaust(
            leaf_vpd=leaf_vpd,
            canopy_temp=canopy_temp,
            upper_enthalpy=upper_enthalpy,
            lung_enthalpy=lung_enthalpy,
            sensor_dropout=sensor_dropout,
            lights_on=lights_on,
            thermal_runaway=thermal_runaway,
        )

        # ── Zone control (skip if dropout or thermal runaway for safety) ───────
        zone1_heater_on = False
        zone1_ac_on = False
        zone1_humid_on = False
        zone1_dehumid_on = False
        zone1_reverse_cycle_mode: Optional[str] = None
        zone1_backup_heater_on = False

        zone2_heater_on = False
        zone2_ac_on = False
        zone2_humid_on = False
        zone2_dehumid_on = False
        zone2_reverse_cycle_mode: Optional[str] = None

        if not sensor_dropout and not thermal_runaway:
            # ── Zone 1 — Conditioning Room (flag-gated) ───────────────────────
            if self._conditioning_room_enabled():
                z1_is_rc = bool(self._get(CONF_ZONE1_IS_REVERSE_CYCLE, False))
                zone1_reverse_cycle_mode = await self._control_zone(
                    zone=self._z1,
                    zone_label="zone1",
                    current_temp=lung_temp,
                    leaf_vpd=leaf_vpd,
                    heater_id=self._get(CONF_ZONE1_HEATER),
                    ac_id=self._get(CONF_ZONE1_AC),
                    humid_id=self._get(CONF_ZONE1_HUMIDIFIER),
                    dehumid_id=self._get(CONF_ZONE1_DEHUMIDIFIER),
                    is_reverse_cycle=z1_is_rc,
                    reverse_cycle_id=self._get(CONF_ZONE1_REVERSE_CYCLE),
                    enable_heat_cutoff=True,
                )
                zone1_heater_on = self._z1.heater_on
                zone1_ac_on = self._z1.ac_on
                zone1_humid_on = self._z1.humid_on
                zone1_dehumid_on = self._z1.dehumid_on

                # Legacy backup heater staging path (when no is_reverse_cycle)
                # When is_reverse_cycle=True the backup is handled inside _control_zone
                if not z1_is_rc:
                    zone1_backup_heater_on = await self._stage_backup_heater(
                        current_temp=canopy_temp,
                        lung_temp=lung_temp,
                        primary_heat_on=zone1_heater_on,
                        primary_rc_mode=zone1_reverse_cycle_mode,
                    )
                else:
                    # Backup heater staging is handled inside _control_zone
                    # when is_reverse_cycle=True; report its entity state
                    backup_id = self._get(CONF_ZONE1_HEATER)
                    if backup_id:
                        bk_state = self._coord.hass.states.get(backup_id)
                        zone1_backup_heater_on = (
                            bk_state is not None and bk_state.state == "on"
                        )
                    else:
                        zone1_backup_heater_on = False

            # ── Zone 2 — Primary Grow Space (always active in both topologies) ─
            z2_is_rc = bool(self._get(CONF_ZONE2_IS_REVERSE_CYCLE, False))
            zone2_reverse_cycle_mode = await self._control_zone(
                zone=self._z2,
                zone_label="zone2",
                current_temp=upper_temp,
                leaf_vpd=leaf_vpd,
                heater_id=self._get(CONF_ZONE2_HEATER),
                ac_id=self._get(CONF_ZONE2_AC),
                humid_id=self._get(CONF_ZONE2_HUMIDIFIER),
                dehumid_id=self._get(CONF_ZONE2_DEHUMIDIFIER),
                is_reverse_cycle=z2_is_rc,
                reverse_cycle_id=self._get(CONF_ZONE2_REVERSE_CYCLE),
                enable_heat_cutoff=False,
            )
            zone2_heater_on = self._z2.heater_on
            zone2_ac_on = self._z2.ac_on
            zone2_humid_on = self._z2.humid_on
            zone2_dehumid_on = self._z2.dehumid_on

            # ── Drying zone control (flag-gated) ───────────────────────────────
            if self._drying_environment_enabled():
                raw_drying_temp = self._coord._read_sensor(self._get(CONF_DRYING_TEMP_SENSOR))
                raw_drying_rh = self._coord._read_sensor(self._get(CONF_DRYING_HUMIDITY_SENSOR))
                # Apply calibration offsets
                drying_temp = self._apply_sensor_offset(
                    raw_drying_temp, CONF_DRYING_TEMP_OFFSET, CONF_DRYING_HUMIDITY_OFFSET, is_humidity=False
                )
                drying_rh = self._apply_sensor_offset(
                    raw_drying_rh, CONF_DRYING_TEMP_OFFSET, CONF_DRYING_HUMIDITY_OFFSET, is_humidity=True
                )
                await self._control_drying_zone(drying_temp=drying_temp, drying_rh=drying_rh)

            # ── Light leak watchdog (night phase only) ─────────────────────────
            if not lights_on:
                await self._check_light_leak()
            else:
                # Day cycle — reset watchdog state for next night
                self._light_leak_start = None
                self._light_leak_alerted = False

            # ── Stratification check ───────────────────────────────────────────
            await self._check_stratification(
                upper_temp=upper_temp,
                lower_temp=lower_temp,
                upper_rh=upper_rh,
                lower_rh=lower_rh,
            )

        return {
            "exhaust_pct": exhaust_pct,
            "thermal_runaway": thermal_runaway,
            # Zone 1
            "zone1_heater_on": zone1_heater_on,
            "zone1_ac_on": zone1_ac_on,
            "zone1_humid_on": zone1_humid_on,
            "zone1_dehumid_on": zone1_dehumid_on,
            "zone1_reverse_cycle_mode": zone1_reverse_cycle_mode,
            "zone1_backup_heater_on": zone1_backup_heater_on,
            # Zone 2
            "zone2_heater_on": zone2_heater_on,
            "zone2_ac_on": zone2_ac_on,
            "zone2_humid_on": zone2_humid_on,
            "zone2_dehumid_on": zone2_dehumid_on,
            "zone2_reverse_cycle_mode": zone2_reverse_cycle_mode,
        }
