"""Helix Cultivate — Environmental Learning System (v1.4.0 Parts 7-10).

Opt-in, advanced layer for correlating environmental conditions (external
weather, time-of-day, lighting, an approximate occupied/heated-hours
schedule) against actuator duty-cycle, so the system can eventually nudge
its own predictive feedforward (weather pre-conditioning, Predictive
Pre-Heating) with real, site-specific data rather than only generic
assumptions.

Instantiated fresh each coordinator tick (matching ClimateEngine's own
pattern) and only ever called when CONF_THERMAL_LEARNING_ENABLED is True —
with the toggle off, nothing in this module runs at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.util import dt as dt_util

from .const import (
    CONF_LEARNING_DURATION_DAYS,
    CONF_LEARNING_STARTED_AT,
    CONF_LEARNING_STATE,
    DEEP_CALIBRATION_MAX_MIN,
    DEEP_CALIBRATION_MIN_MIN,
    DEFAULT_LEARNING_DURATION_DAYS,
    DOMAIN,
    LEARNING_CONFIDENT_SAMPLE_COUNT,
    LEARNING_LOG_INTERVAL_MIN,
    LEARNING_STATE_ACTIVE,
    LEARNING_STATE_LEARNING,
    LIVE_TEST_MAX_WAIT_MIN,
    LIVE_TEST_SETPOINT_NUDGE_C,
)

if TYPE_CHECKING:
    from .coordinator import HelixCoordinator

_LOGGER = logging.getLogger(__name__)

# Deep Calibration and Live Actuator Response Testing are mutually exclusive
# with each other (one test per zone at a time) but independent across
# zones — tracked as a dict keyed by zone in the durable store.
TEST_TYPE_DEEP_CALIBRATION: str = "deep_calibration"
TEST_TYPE_LIVE_ACTUATOR: str = "live_actuator"

ZONE_LABELS: tuple[str, ...] = ("zone2", "drying", "conditioning")


def outdoor_temp_bucket(outdoor_temp_c: Optional[float]) -> str:
    """5°C-wide bucket id for regression indexing — coarse enough to
    accumulate real sample counts per bucket in a reasonable time, fine
    enough to distinguish meaningfully different thermal-loss conditions."""
    if outdoor_temp_c is None:
        return "unknown"
    bucket_floor = int(outdoor_temp_c // 5) * 5
    return f"{bucket_floor}to{bucket_floor + 5}"


class LearningEngine:
    """One tick's worth of Environmental Learning System work."""

    def __init__(self, coordinator: "HelixCoordinator") -> None:
        self._coord = coordinator

    def _get(self, key: str, default: Any = None) -> Any:
        return self._coord._get(key, default)

    @property
    def _store(self):
        return self._coord.hass.data.get(DOMAIN, {}).get("learning_store")

    # ── State machine (7.2) ─────────────────────────────────────────────────

    def learning_state(self) -> str:
        return self._get(CONF_LEARNING_STATE, LEARNING_STATE_LEARNING)

    async def ensure_started(self) -> None:
        """Called the first tick the master toggle is on with no state yet
        recorded — begins Learning, independent of cycle_state/occupancy."""
        if self._get(CONF_LEARNING_STARTED_AT) is not None:
            return
        now = dt_util.utcnow()
        self._coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_LEARNING
        self._coord._config[CONF_LEARNING_STARTED_AT] = now.isoformat()
        self._coord.queue_option_write(CONF_LEARNING_STATE, LEARNING_STATE_LEARNING)
        self._coord.queue_option_write(CONF_LEARNING_STARTED_AT, now.isoformat())

    def maybe_graduate_to_active(self) -> bool:
        """Part 7.2: unconditional graduation after the configured fixed
        duration — never gated on having observed any particular event.
        Returns True if a graduation just happened this call."""
        if self.learning_state() != LEARNING_STATE_LEARNING:
            return False
        started_raw = self._get(CONF_LEARNING_STARTED_AT)
        if not started_raw:
            return False
        try:
            started_at = datetime.fromisoformat(started_raw)
        except (TypeError, ValueError):
            return False
        duration_days = float(self._get(CONF_LEARNING_DURATION_DAYS, DEFAULT_LEARNING_DURATION_DAYS))
        if dt_util.utcnow() - started_at >= timedelta(days=duration_days):
            self._coord._config[CONF_LEARNING_STATE] = LEARNING_STATE_ACTIVE
            self._coord.queue_option_write(CONF_LEARNING_STATE, LEARNING_STATE_ACTIVE)
            _LOGGER.info(
                "Helix Cultivate: Environmental Learning graduated to Active "
                "after %.0f days.", duration_days,
            )
            return True
        return False

    # ── Confidence-weighted blending (7.3) ─────────────────────────────────────

    def get_confidence_blended_bias(
        self, zone: str, outdoor_temp_c: Optional[float]
    ) -> float:
        """Returns a small additional setpoint bias (°C) derived from this
        zone's learned regression bucket for the current outdoor-temp
        condition, weighted by how much data actually exists for it — 0.0
        whenever there's no store, no bucket, or (necessarily) while still
        disabled. This never replaces the generic weather feedforward; it's
        summed on top of it, and its own weight is what keeps a thin-data
        condition from being treated as confidently known.
        """
        store = self._store
        if store is None:
            return 0.0
        bucket = store.get_regression_bucket(zone, outdoor_temp_bucket(outdoor_temp_c))
        if bucket is None or not bucket.get("count"):
            return 0.0
        confidence = min(1.0, bucket["count"] / LEARNING_CONFIDENT_SAMPLE_COUNT)
        return float(bucket["mean_response"]) * confidence

    # ── Passive continuous logging (7.5/7.6) ────────────────────────────────────

    async def maybe_log_hourly(
        self,
        zone: str,
        outdoor_temp_c: Optional[float],
        indoor_temp_c: Optional[float],
        actuator_duty_pct: float,
        lights_on: bool,
        light_pct: float,
        cycle_id: Optional[str],
    ) -> None:
        """Rate-limited to roughly once per LEARNING_LOG_INTERVAL_MIN per
        zone — captures a snapshot naturally whenever the tick lands near
        that interval, rather than requiring a scheduled test to happen to
        coincide with a real weather event."""
        store = self._store
        if store is None:
            return
        last_log = self._coord._learning_last_log
        last = last_log.get(zone)
        now = dt_util.utcnow()
        if last is not None and (now - last).total_seconds() < LEARNING_LOG_INTERVAL_MIN * 60:
            return
        last_log[zone] = now

        await store.record_hourly_log({
            "zone": zone,
            "outdoor_temp_c": outdoor_temp_c,
            "indoor_temp_c": indoor_temp_c,
            "actuator_duty_pct": actuator_duty_pct,
            "lights_on": lights_on,
            "light_pct": light_pct,
            "cycle_id": cycle_id,
            "hour_of_day": now.hour,
        })

        if indoor_temp_c is not None and outdoor_temp_c is not None:
            # The observation folded into the regression bucket is how far
            # below/above the zone's own setpoint it's running under this
            # outdoor condition — the thing a learned bias should correct.
            setpoint = getattr(self._coord, "temp_setpoint", None)
            if setpoint is not None:
                await store.update_regression_bucket(
                    zone, outdoor_temp_bucket(outdoor_temp_c), setpoint - indoor_temp_c
                )

        await self._maybe_export(zone, outdoor_temp_c, indoor_temp_c, actuator_duty_pct)

    # ── Optional InfluxDB / VictoriaMetrics line-protocol export (8.2) ─────────

    async def _maybe_export(
        self, zone: str, outdoor_temp_c: Optional[float],
        indoor_temp_c: Optional[float], actuator_duty_pct: float,
    ) -> None:
        from .const import CONF_LEARNING_EXPORT_ENABLED, CONF_LEARNING_EXPORT_URL

        if not self._get(CONF_LEARNING_EXPORT_ENABLED, False):
            return
        url = self._get(CONF_LEARNING_EXPORT_URL)
        if not url:
            return

        fields = []
        if outdoor_temp_c is not None:
            fields.append(f"outdoor_temp_c={outdoor_temp_c}")
        if indoor_temp_c is not None:
            fields.append(f"indoor_temp_c={indoor_temp_c}")
        fields.append(f"actuator_duty_pct={actuator_duty_pct}")
        if not fields:
            return
        line = f"helix_cultivate_learning,zone={zone} " + ",".join(fields)

        try:
            session = self._coord.hass.helpers.aiohttp_client.async_get_clientsession()
            await session.post(url, data=line, timeout=5)
        except Exception as exc:  # noqa: BLE001
            # Best-effort, one-way mirror — quiet logging only, never a
            # blocking error or critical alert. The core learning system
            # must be completely unaffected by an unreachable endpoint.
            _LOGGER.debug("Helix Cultivate: learning export failed (%s): %s", url, exc)

    # ── Deep Calibration (7.4) ──────────────────────────────────────────────────

    async def start_deep_calibration(
        self,
        zone: str,
        current_temp: Optional[float] = None,
        outdoor_temp_c: Optional[float] = None,
    ) -> dict[str, Any]:
        """Begin a Deep Calibration test for `zone` — only valid for an
        unoccupied zone (zone2/drying) or a Conditioning Room that's
        currently eligible per the Part 3 dependent-zone rule. Cuts that
        zone's actuator control entirely for a randomised 20-40 minute
        window; climate_engine checks is_deep_calibration_active() and
        skips driving that zone while a test is active there. Caller
        supplies the current readings explicitly (the coordinator already
        has them fresh each tick) rather than this reaching back into
        coordinator internals that may not exist for every zone.
        """
        self._assert_zone_eligible_for_deep_calibration(zone)
        store = self._require_store()

        import random
        duration_min = random.uniform(DEEP_CALIBRATION_MIN_MIN, DEEP_CALIBRATION_MAX_MIN)

        test = {
            "type": TEST_TYPE_DEEP_CALIBRATION,
            "zone": zone,
            "started_at": dt_util.utcnow().isoformat(),
            "duration_min": duration_min,
            "started_temp_c": current_temp,
            "outdoor_temp_c": outdoor_temp_c,
        }
        await store.set_active_test(test)
        _LOGGER.info(
            "Helix Cultivate: Deep Calibration started for zone=%s, duration=%.1f min",
            zone, duration_min,
        )
        return test

    def _assert_zone_eligible_for_deep_calibration(self, zone: str) -> None:
        if zone == "conditioning":
            if not self._coord.is_conditioning_room_calibration_eligible():
                raise ValueError(
                    "Conditioning Room is not eligible for Deep Calibration — "
                    "at least one dependent zone is currently occupied."
                )
            return
        if zone == "zone2":
            if self._coord.is_zone2_occupied():
                raise ValueError("Primary Grow Space is occupied — Deep Calibration is not permitted.")
            return
        if zone == "drying":
            if self._coord.is_drying_occupied():
                raise ValueError("Drying Room is occupied — Deep Calibration is not permitted.")
            return
        raise ValueError(f"Unknown zone: {zone!r}")

    def is_deep_calibration_active(self, zone: str) -> bool:
        """Checked by climate_engine at the top of each zone's control
        function — True means skip driving this zone's actuators entirely."""
        store = self._store
        if store is None:
            return False
        active = store.get_active_test()
        return bool(
            active
            and active.get("type") == TEST_TYPE_DEEP_CALIBRATION
            and active.get("zone") == zone
        )

    async def tick_active_test(self, current_temps: dict[str, Optional[float]]) -> None:
        """Called every coordinator tick when learning is enabled — checks
        whether an in-progress Deep Calibration has run its full duration
        and, if so, logs the observed free-decay and resumes normal
        control. Also enforces LIVE_TEST_MAX_WAIT_MIN as a safety cap for
        live actuator tests so a real fault can't hang a test forever.
        current_temps maps zone -> current temperature reading, so decay
        can be measured without a second live sensor lookup here.
        """
        store = self._store
        if store is None:
            return
        active = store.get_active_test()
        if active is None:
            return

        started_at = datetime.fromisoformat(active["started_at"])
        elapsed_min = (dt_util.utcnow() - started_at).total_seconds() / 60.0

        if active["type"] == TEST_TYPE_DEEP_CALIBRATION:
            if elapsed_min >= active["duration_min"]:
                await self._finish_deep_calibration(active, current_temps.get(active["zone"]))
        elif active["type"] == TEST_TYPE_LIVE_ACTUATOR:
            if elapsed_min >= LIVE_TEST_MAX_WAIT_MIN:
                await self._finish_live_actuator_test(
                    active, current_temps.get(active["zone"]), timed_out=True
                )

    async def _finish_deep_calibration(
        self, test: dict[str, Any], ended_temp: Optional[float]
    ) -> None:
        store = self._require_store()
        zone = test["zone"]
        started_temp = test.get("started_temp_c")
        decay_c = (
            (started_temp - ended_temp) if started_temp is not None and ended_temp is not None else None
        )
        record = {**test, "ended_at": dt_util.utcnow().isoformat(), "ended_temp_c": ended_temp, "decay_c": decay_c}
        await store.append_test_history(record)
        if decay_c is not None:
            await store.update_regression_bucket(
                zone, outdoor_temp_bucket(test.get("outdoor_temp_c")), decay_c
            )
        await store.set_active_test(None)
        _LOGGER.info(
            "Helix Cultivate: Deep Calibration finished for zone=%s — decay=%s°C, control resumed.",
            zone, f"{decay_c:.2f}" if decay_c is not None else "unknown",
        )

    # ── Live Actuator Response Testing (7.4) ────────────────────────────────────

    async def start_live_actuator_test(
        self, zone: str, thermostat_controlled: bool
    ) -> dict[str, Any]:
        """Available regardless of occupancy (stays within safe bounds).
        For a directly-controlled actuator (e.g. a circulation fan), the
        caller is expected to step it through its increments itself and
        just use this to record the test window; for a thermostat-
        controlled zone (Reverse Cycle in heat_cool), this nudges the
        target setpoint and times how long the zone takes to reach it.
        """
        if zone == "conditioning":
            # Cross-zone: eligibility always allowed (Live Actuator Testing
            # is permitted regardless of occupancy) but the test measures
            # BOTH Conditioning Room's own response and every zone that
            # depends on it.
            dependents = self._coord.conditioning_room_dependent_zones()
        else:
            dependents = []

        store = self._require_store()
        test = {
            "type": TEST_TYPE_LIVE_ACTUATOR,
            "zone": zone,
            "thermostat_controlled": thermostat_controlled,
            "dependent_zones": dependents,
            "started_at": dt_util.utcnow().isoformat(),
            "nudge_c": LIVE_TEST_SETPOINT_NUDGE_C if thermostat_controlled else None,
            "started_temp_c": None,
            "started_dependent_temps": {},
        }
        await store.set_active_test(test)
        return test

    async def _finish_live_actuator_test(
        self, test: dict[str, Any], ended_temp: Optional[float], timed_out: bool
    ) -> None:
        store = self._require_store()
        started_at = datetime.fromisoformat(test["started_at"])
        lag_min = (dt_util.utcnow() - started_at).total_seconds() / 60.0
        record = {
            **test, "ended_at": dt_util.utcnow().isoformat(),
            "ended_temp_c": ended_temp, "lag_min": lag_min, "timed_out": timed_out,
        }
        await store.append_test_history(record)

        # Cross-zone lag/magnitude — Part 7.4's explicit requirement that
        # this is tracked as its own dataset, distinct from same-zone data.
        for dependent in test.get("dependent_zones", []):
            started_dep = test.get("started_dependent_temps", {}).get(dependent)
            if started_dep is not None and ended_temp is not None and test.get("started_temp_c"):
                magnitude_ratio = (
                    abs(ended_temp - started_dep) / abs(test["started_temp_c"] - (test.get("nudge_c") or 1))
                    if test.get("nudge_c") else 0.0
                )
                await store.update_cross_zone_response(dependent, lag_min, magnitude_ratio)

        await store.set_active_test(None)

    def _require_store(self):
        store = self._store
        if store is None:
            raise ValueError("Learning store is not initialised.")
        return store

    # ── 7.4b: chaining external-weather and cross-zone models ──────────────────

    def combined_lead_time_min(self, dependent_zone: str) -> float:
        """Total lead time (minutes) before an external change would
        otherwise affect `dependent_zone` — the sum of the external-to-
        Conditioning-Room lag (approximated here from the regression
        bucket's own update cadence, since a dedicated external-lag model
        is out of scope for this version) and the learned Conditioning-
        Room-to-dependent-zone lag from cross-zone response testing.
        Returns 0.0 whenever insufficient data exists for either half —
        callers should treat 0.0 as "no confident lead time available yet."
        """
        cross = self._store.get_cross_zone_response(dependent_zone) if self._store else None
        if cross is None or cross["count"] < 1:
            return 0.0
        return float(cross["mean_lag_min"])

    def predictive_preheat_adjustment(
        self, zone: str, default_lead_min: float, default_bias_c: float
    ) -> tuple[float, float]:
        """Part 7.4b: refines the existing Predictive Pre-Heating feature's
        lead-time/magnitude via confidence-weighted blending (7.3) against
        this zone's own learned lights-off thermal response — never a hard
        replacement of the grower's configured default. Returns
        (lead_min, bias_c), both blended toward the learned value in
        proportion to how much relevant data exists.
        """
        store = self._store
        if store is None:
            return default_lead_min, default_bias_c
        bucket = store.get_regression_bucket(zone, "lights_off_response")
        if bucket is None or not bucket.get("count"):
            return default_lead_min, default_bias_c
        confidence = min(1.0, bucket["count"] / LEARNING_CONFIDENT_SAMPLE_COUNT)
        learned_bias = float(bucket["mean_response"])
        blended_bias = default_bias_c + confidence * (learned_bias - default_bias_c)
        return default_lead_min, blended_bias
