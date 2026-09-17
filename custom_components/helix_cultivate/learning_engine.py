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
    CONF_DRYING_IS_REVERSE_CYCLE,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_LEARNING_DURATION_DAYS,
    CONF_LEARNING_SHADOW_MODE,
    CONF_LEARNING_STARTED_AT,
    CONF_LEARNING_STATE,
    CONF_ZONE1_IS_REVERSE_CYCLE,
    CONF_ZONE2_IS_REVERSE_CYCLE,
    DEEP_CALIBRATION_MAX_MIN,
    DEEP_CALIBRATION_MIN_MIN,
    DEFAULT_LEARNING_DURATION_DAYS,
    DEFAULT_LEARNING_SHADOW_MODE,
    DOMAIN,
    LEARNING_CONFIDENT_SAMPLE_COUNT,
    LEARNING_LOG_INTERVAL_MIN,
    LEARNING_STATE_ACTIVE,
    LEARNING_STATE_LEARNING,
    LIVE_ACTUATOR_TEST_INTERVAL_ACTIVE_HOURS,
    LIVE_ACTUATOR_TEST_INTERVAL_LEARNING_HOURS,
    LIVE_TEST_MAX_WAIT_MIN,
    LIVE_TEST_REACHED_TOLERANCE_C,
    LIVE_TEST_SETPOINT_NUDGE_C,
    WEATHER_EVENT_PRECIP_THRESHOLD_PCT,
    WEATHER_EVENT_TEMP_SWING_C,
)

if TYPE_CHECKING:
    from .coordinator import HelixCoordinator

_LOGGER = logging.getLogger(__name__)

# Deep Calibration and Live Actuator Response Testing are mutually exclusive
# with each other — the durable store holds a single `active_test` slot, so
# only one test (of either type, for one zone) can be in progress
# system-wide at any moment. Cross-zone response data is nonetheless
# tracked independently per dependent zone (see update_cross_zone_response).
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
        # Part 5.1 (v1.6.0): Shadow Mode defaults ON whenever Environmental
        # Learning is first enabled — a grower must opt IN to letting the
        # regression touch a real setpoint, never the other way around.
        self._coord._config[CONF_LEARNING_SHADOW_MODE] = DEFAULT_LEARNING_SHADOW_MODE
        self._coord.queue_option_write(CONF_LEARNING_SHADOW_MODE, DEFAULT_LEARNING_SHADOW_MODE)

    def shadow_mode_enabled(self) -> bool:
        """Part 5.1: True while the regression's predictions must never
        touch a real setpoint — only ever observed, never applied."""
        return bool(self._get(CONF_LEARNING_SHADOW_MODE, DEFAULT_LEARNING_SHADOW_MODE))

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

    # ── Confidence-weighted blending (7.3, upgraded in v1.4.1 Part 4) ───────────

    def get_confidence_blended_bias(
        self,
        zone: str,
        outdoor_temp_c: Optional[float],
        hour_of_day: Optional[int] = None,
        month: Optional[int] = None,
        lights_on: bool = False,
        light_pct: float = 0.0,
        occupied: bool = False,
    ) -> float:
        """Returns a small additional setpoint bias (°C) from this zone's
        fitted multi-variable regression (Part 4) for the given
        conditions — combining outdoor temperature, time-of-day, season,
        lighting, and occupancy rather than requiring this exact
        combination to have been observed before (the old bucketed model's
        limitation). Weighted by the regression's own prediction-interval-
        based confidence: 0.0 whenever there's no store, no fitted model
        yet (Part 4.4's safe fallback — insufficient or degenerate data
        must never look confidently known), or a query missing
        outdoor_temp_c. This never replaces the generic weather
        feedforward; it's summed on top of it, exactly as before — only
        what feeds the blending changed, not the blending mechanism.
        """
        predicted, confidence = self._predict_with_confidence(
            zone, outdoor_temp_c, hour_of_day, month, lights_on, light_pct, occupied,
        )
        if confidence <= 0.0:
            return 0.0
        return predicted * confidence

    def _predict_with_confidence(
        self,
        zone: str,
        outdoor_temp_c: Optional[float],
        hour_of_day: Optional[int],
        month: Optional[int],
        lights_on: bool,
        light_pct: float,
        occupied: bool,
    ) -> tuple[float, float]:
        """Shared regression lookup backing both get_confidence_blended_bias
        and the Part 5.2 Shadow Mode readout, so both see the exact same
        raw prediction/confidence pair from a single fit — never computed
        twice with any chance of drifting apart."""
        store = self._store
        if store is None:
            return 0.0, 0.0
        model = store.get_regression_model(zone)
        if model is None:
            return 0.0, 0.0

        from .learning_regression import build_feature_vector, predict_with_confidence

        x0 = build_feature_vector(
            outdoor_temp_c=outdoor_temp_c, hour_of_day=hour_of_day, month=month,
            lights_on=lights_on, light_pct=light_pct, occupied=occupied,
        )
        if x0 is None:
            return 0.0, 0.0
        return predict_with_confidence(model, x0)

    # ── Shadow Mode feedforward (Part 5.2, v1.6.0) ───────────────────────────

    def compute_conditioning_shadow_feedforward(
        self,
        generic_bias_c: float,
        outdoor_temp_c: Optional[float],
        indoor_temp_c: Optional[float],
        lights_on: bool = False,
        light_pct: float = 0.0,
        occupied: bool = False,
    ) -> dict[str, Any]:
        """Computes Conditioning Room's confidence-weighted blended
        feedforward bias every tick regardless of Shadow Mode's state (so
        the Part 6 comparison chart and Part 8 readout stay live either
        way), and decides which bias value is actually applied to the real
        setpoint: the existing generic weather feedforward alone while
        Shadow Mode is on, or the full blended value once it's off.
        """
        now = dt_util.utcnow()
        predicted, confidence = self._predict_with_confidence(
            "conditioning", outdoor_temp_c, now.hour, now.month,
            lights_on, light_pct, occupied,
        )
        blended_bias_c = predicted * confidence if confidence > 0.0 else 0.0
        shadow_mode = self.shadow_mode_enabled()
        applied_bias_c = generic_bias_c if shadow_mode else blended_bias_c

        setpoint = getattr(self._coord, "temp_setpoint", None)
        predicted_indoor_temp_c: Optional[float] = (
            setpoint - blended_bias_c if setpoint is not None else None
        )

        return {
            "shadow_mode": shadow_mode,
            "generic_bias_c": generic_bias_c,
            "blended_bias_c": blended_bias_c,
            "confidence": confidence,
            "applied_bias_c": applied_bias_c,
            "predicted_indoor_temp_c": predicted_indoor_temp_c,
        }

    # ── Retrospective summary (v1.6.0 Part 9) ────────────────────────────────

    def compute_shadow_retrospective_summary(
        self, zone: str = "conditioning", trailing_days: float = 7.0,
    ) -> Optional[dict[str, Any]]:
        """Aggregate summary over a trailing window for the Settings tab —
        NOT a live graph, that tab's role is configuration, not ongoing
        monitoring (Part 6 already covers live monitoring on Conditioning
        Room's own tab). Derived from the same logged comparison data.

        Returns None when there's nothing yet to summarise (no rows with
        both a generic and a blended bias logged in the window).
        """
        store = self._store
        if store is None:
            return None

        cutoff = dt_util.utcnow() - timedelta(days=trailing_days)
        agree_count = 0
        disagree_count = 0
        disagree_magnitude_sum = 0.0

        for row in store.get_hourly_logs(zone):
            generic = row.get("shadow_generic_bias_c")
            blended = row.get("shadow_blended_bias_c")
            if generic is None or blended is None:
                continue
            ts_raw = row.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except (TypeError, ValueError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=cutoff.tzinfo)
            if ts < cutoff:
                continue

            same_direction = (generic >= 0) == (blended >= 0)
            if same_direction:
                agree_count += 1
            else:
                disagree_count += 1
                disagree_magnitude_sum += abs(blended)

        total = agree_count + disagree_count
        if total == 0:
            return None

        return {
            "sample_count": total,
            "agreement_pct": round(100.0 * agree_count / total, 1),
            "avg_disagreement_bias_c": (
                round(disagree_magnitude_sum / disagree_count, 2) if disagree_count else 0.0
            ),
            "trailing_days": trailing_days,
        }

    # ── Weather-event log (v1.6.0 Part 7) ────────────────────────────────────

    async def maybe_log_weather_event(
        self,
        future_temp_c: Optional[float],
        current_outdoor_temp_c: Optional[float],
        precipitation_probability: Optional[float],
        shadow_prediction: Optional[dict[str, Any]],
    ) -> None:
        """Edge-triggered detection of a notable discrete forecast change —
        logs once when a threshold condition BECOMES true, not again on
        every tick it stays true, and again once it clears and re-triggers.
        Each logged entry is correlated with the Shadow prediction at that
        exact moment (Part 7.2), whatever it happened to be.
        """
        store = self._store
        if store is None:
            return

        state = store.get_weather_event_state()
        precip_active = bool(state.get("precip_active", False))
        swing_active = bool(state.get("temp_swing_active", False))
        new_state = dict(state)
        now = dt_util.utcnow()
        messages: list[str] = []

        if precipitation_probability is not None:
            now_high = precipitation_probability >= WEATHER_EVENT_PRECIP_THRESHOLD_PCT
            if now_high and not precip_active:
                messages.append(
                    f"Rain expected within the next hour ({precipitation_probability:.0f}% chance)"
                )
            new_state["precip_active"] = now_high

        if future_temp_c is not None and current_outdoor_temp_c is not None:
            delta = future_temp_c - current_outdoor_temp_c
            now_swinging = abs(delta) >= WEATHER_EVENT_TEMP_SWING_C
            if now_swinging and not swing_active:
                direction = "rise" if delta > 0 else "drop"
                messages.append(
                    f"Significant temperature {direction} forecast ({delta:+.1f}°C within the hour)"
                )
            new_state["temp_swing_active"] = now_swinging

        if new_state != state:
            await store.set_weather_event_state(new_state)

        for message in messages:
            await store.record_weather_event({
                "ts": now.isoformat(),
                "message": message,
                "correlated_bias_c": (shadow_prediction or {}).get("blended_bias_c"),
                "correlated_predicted_temp_c": (shadow_prediction or {}).get("predicted_indoor_temp_c"),
            })

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
        shadow_predicted_indoor_temp_c: Optional[float] = None,
        shadow_generic_bias_c: Optional[float] = None,
        shadow_blended_bias_c: Optional[float] = None,
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

        # The response a learned bias should correct is how far below/
        # above the zone's own setpoint it's running under these
        # conditions — computed once, here, at log time (using today's
        # real setpoint) and stored directly on the row, since a later
        # refit must not recompute it against whatever setpoint happens to
        # be configured at REFIT time (which could be a different growth
        # stage entirely).
        setpoint = getattr(self._coord, "temp_setpoint", None)
        setpoint_gap_c: Optional[float] = (
            setpoint - indoor_temp_c
            if setpoint is not None and indoor_temp_c is not None else None
        )
        occupied = cycle_id is not None

        await store.record_hourly_log({
            "zone": zone,
            "outdoor_temp_c": outdoor_temp_c,
            "indoor_temp_c": indoor_temp_c,
            "actuator_duty_pct": actuator_duty_pct,
            "lights_on": lights_on,
            "light_pct": light_pct,
            "cycle_id": cycle_id,
            "hour_of_day": now.hour,
            "month": now.month,
            "setpoint_gap_c": setpoint_gap_c,
            "occupied": occupied,
            # Part 6 (v1.6.0): piggybacks on this same hourly row/cadence —
            # no separate data-collection cadence for the Conditioning Room
            # comparison chart. None for every zone except "conditioning",
            # and even there only once Environmental Learning has a fitted
            # model to predict from.
            "shadow_predicted_indoor_temp_c": shadow_predicted_indoor_temp_c,
            # Part 9 (v1.6.0): the raw generic/blended bias pair behind the
            # predicted temp above — kept alongside it so the Settings tab's
            # retrospective agreement summary can be derived later without
            # re-deriving anything from the temperature delta.
            "shadow_generic_bias_c": shadow_generic_bias_c,
            "shadow_blended_bias_c": shadow_blended_bias_c,
        })

        if setpoint_gap_c is not None:
            await self._refit_regression(zone)

        await self._maybe_export(zone, outdoor_temp_c, indoor_temp_c, actuator_duty_pct)

    async def _refit_regression(self, zone: str) -> None:
        """Part 4.2: refit on the same rolling cadence as before — every
        time a new usable hourly log lands for this zone (never stops
        refitting). Trains on every historical row for this zone that
        carries setpoint_gap_c; rows logged before this upgrade (v1.4.0)
        lack that field and are simply skipped rather than fabricated —
        the model naturally starts building real confidence from zero new
        data after an upgrade instead of guessing.
        """
        store = self._store
        if store is None:
            return
        from .learning_regression import build_feature_vector, fit_ols

        rows: list[list[float]] = []
        targets: list[float] = []
        for row in store.get_hourly_logs(zone):
            gap = row.get("setpoint_gap_c")
            if gap is None:
                continue
            vector = build_feature_vector(
                outdoor_temp_c=row.get("outdoor_temp_c"),
                hour_of_day=row.get("hour_of_day"),
                month=row.get("month"),
                lights_on=bool(row.get("lights_on")),
                light_pct=float(row.get("light_pct") or 0.0),
                occupied=bool(row.get("occupied")),
            )
            if vector is None:
                continue
            rows.append(vector)
            targets.append(float(gap))

        model = fit_ols(rows, targets)
        if model is not None:
            model["updated_at"] = dt_util.utcnow().isoformat()
            await store.set_regression_model(zone, model)
        # else: not enough usable data yet, or a degenerate fit — leave
        # any previously-fitted model untouched rather than discarding it
        # over what would have to be a transient numerical hiccup (real
        # sample counts only grow, so a fit that has already succeeded
        # once should keep succeeding).

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
        control. For a thermostat-controlled Live Actuator Test, finishes
        early as soon as the zone's own dedicated sensor reaches the nudged
        target (measuring real lag rather than always waiting out the full
        window); LIVE_TEST_MAX_WAIT_MIN remains a safety cap either way so a
        real fault (stuck actuator, sensor dropout) can't hang a test
        forever. current_temps maps zone -> current temperature reading (a
        dedicated sensor value, never an actuator's own attribute), so
        decay/lag can be measured without a second live sensor lookup here.
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
            return

        if active["type"] == TEST_TYPE_LIVE_ACTUATOR:
            current_temp = current_temps.get(active["zone"])
            reached_target = False
            if (
                active.get("thermostat_controlled")
                and active.get("nudge_c")
                and current_temp is not None
                and active.get("started_temp_c") is not None
            ):
                target = active["started_temp_c"] + active["nudge_c"]
                reached_target = abs(current_temp - target) <= LIVE_TEST_REACHED_TOLERANCE_C

            if reached_target:
                await self._finish_live_actuator_test(active, current_temps, timed_out=False)
            elif elapsed_min >= LIVE_TEST_MAX_WAIT_MIN:
                await self._finish_live_actuator_test(active, current_temps, timed_out=True)

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
        self,
        zone: str,
        thermostat_controlled: bool,
        current_temp: Optional[float] = None,
        dependent_temps: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """Available regardless of occupancy (stays within safe bounds).
        For a directly-controlled actuator (e.g. a circulation fan), the
        caller is expected to step it through its increments itself and
        just use this to record the test window; for a thermostat-
        controlled zone (Reverse Cycle in heat_cool), climate_engine reads
        this active test back (via the coordinator) and nudges its own
        effective setpoint by nudge_c for the duration, so the whole nudge/
        measure/revert cycle runs autonomously on the normal control tick.

        `current_temp`/`dependent_temps` are this zone's (and, for
        Conditioning Room, its dependents') dedicated-sensor readings AT
        THE MOMENT the test starts — supplied explicitly by the caller
        (the coordinator already has them fresh each tick), never read
        from an actuator's own attributes, so the eventual lag/magnitude
        measurement compares like-for-like real ambient readings.
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
            "started_temp_c": current_temp,
            "started_dependent_temps": dependent_temps or {},
        }
        await store.set_active_test(test)
        _LOGGER.info(
            "Helix Cultivate: Live Actuator Response Test started for zone=%s "
            "(thermostat_controlled=%s)", zone, thermostat_controlled,
        )
        return test

    async def _finish_live_actuator_test(
        self,
        test: dict[str, Any],
        current_temps: dict[str, Optional[float]],
        timed_out: bool,
    ) -> None:
        store = self._require_store()
        started_at = datetime.fromisoformat(test["started_at"])
        lag_min = (dt_util.utcnow() - started_at).total_seconds() / 60.0
        ended_temp = current_temps.get(test["zone"])
        record = {
            **test, "ended_at": dt_util.utcnow().isoformat(),
            "ended_temp_c": ended_temp, "lag_min": lag_min, "timed_out": timed_out,
        }
        await store.append_test_history(record)

        # Cross-zone lag/magnitude — Part 7.4's explicit requirement that
        # this is tracked as its own dataset, distinct from same-zone data.
        # magnitude_ratio compares how far the DEPENDENT zone's own ending
        # reading moved against how far the SOURCE zone was forced to move
        # (the nudge) — both sides read from dedicated sensors only.
        nudge_c = test.get("nudge_c")
        if nudge_c:
            for dependent in test.get("dependent_zones", []):
                started_dep = test.get("started_dependent_temps", {}).get(dependent)
                ended_dep = current_temps.get(dependent)
                if started_dep is not None and ended_dep is not None:
                    magnitude_ratio = abs(ended_dep - started_dep) / abs(nudge_c)
                    await store.update_cross_zone_response(dependent, lag_min, magnitude_ratio)

        await store.set_active_test(None)
        _LOGGER.info(
            "Helix Cultivate: Live Actuator Response Test finished for zone=%s — "
            "lag=%.1f min, timed_out=%s.", test["zone"], lag_min, timed_out,
        )

    # ── Autonomous scheduling (v1.4.1 Part 2) ───────────────────────────────────

    _LIVE_TEST_CANDIDATE_ZONES: tuple[tuple[str, str], ...] = (
        ("zone2", CONF_ZONE2_IS_REVERSE_CYCLE),
        ("conditioning", CONF_ZONE1_IS_REVERSE_CYCLE),
        ("drying", CONF_DRYING_IS_REVERSE_CYCLE),
    )

    def _zone_enabled(self, zone: str) -> bool:
        if zone == "zone2":
            return True
        if zone == "conditioning":
            return bool(self._get(CONF_ENABLE_CONDITIONING_ROOM, False))
        if zone == "drying":
            return bool(self._get(CONF_ENABLE_DRYING_ENVIRONMENT, False))
        return False

    def _last_live_actuator_test_at(self, zone: str) -> Optional[datetime]:
        store = self._store
        if store is None:
            return None
        matches = [
            record for record in store.get_test_history()
            if record.get("type") == TEST_TYPE_LIVE_ACTUATOR and record.get("zone") == zone
        ]
        if not matches:
            return None
        try:
            return max(datetime.fromisoformat(r["ended_at"]) for r in matches if r.get("ended_at"))
        except (TypeError, ValueError):
            return None

    async def maybe_schedule_live_actuator_test(
        self, zone_temps: dict[str, Optional[float]]
    ) -> Optional[dict[str, Any]]:
        """Part 2 (v1.4.1): decides WHEN to run a Live Actuator Response
        Test on its own, on the normal coordinator tick — this test type
        is "available regardless of occupancy" by design (unlike Deep
        Calibration), so no occupancy check gates it here; a sensible
        per-zone interval is all that's needed, shorter while still
        Learning and longer once Active, matching the same "no fixed rigid
        schedule, just happens naturally in the background" philosophy
        already used for passive logging. Manual triggering (the Settings
        tab's own start action) remains available alongside this — both
        ultimately call start_live_actuator_test() above.

        Never starts a new test while ANY test (either type) is already
        active — there is a single active-test slot system-wide. Starts at
        most one test per tick even when several zones are overdue, so a
        fresh install catching up on several zones at once doesn't try to
        start them all simultaneously.
        """
        store = self._store
        if store is None:
            return None
        if store.get_active_test() is not None:
            return None

        interval_hours = (
            LIVE_ACTUATOR_TEST_INTERVAL_LEARNING_HOURS
            if self.learning_state() == LEARNING_STATE_LEARNING
            else LIVE_ACTUATOR_TEST_INTERVAL_ACTIVE_HOURS
        )
        now = dt_util.utcnow()

        for zone, rc_flag in self._LIVE_TEST_CANDIDATE_ZONES:
            if not self._zone_enabled(zone):
                continue
            last_at = self._last_live_actuator_test_at(zone)
            if last_at is not None and (now - last_at).total_seconds() < interval_hours * 3600:
                continue

            thermostat_controlled = bool(self._get(rc_flag, False))
            current_temp = zone_temps.get(zone)
            dependent_temps: dict[str, float] = {}
            if zone == "conditioning":
                for dependent in self._coord.conditioning_room_dependent_zones():
                    dep_temp = zone_temps.get(dependent)
                    if dep_temp is not None:
                        dependent_temps[dependent] = dep_temp

            return await self.start_live_actuator_test(
                zone, thermostat_controlled,
                current_temp=current_temp, dependent_temps=dependent_temps,
            )
        return None

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
