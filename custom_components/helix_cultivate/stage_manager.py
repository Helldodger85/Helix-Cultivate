"""Helix Cultivate — Stage Manager: state machine, recipe loader, smooth glides."""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .coordinator import HelixCoordinator

from .const import (
    CONF_DRYING_CUSTOM_UNLOCKED,
    CONF_PROGRESSION_MODE,
    CONF_RECIPE_FILE,
    CONF_SMOOTH_GLIDES,
    CONF_STAGE_START_DATE,
    DEFAULT_DRYING_CUSTOM_UNLOCKED,
    DOMAIN,
    DRYING_LOCKED_TEMP_C,
    PROG_MANUAL,
    PROG_TIMEFRAME,
    STAGE_DAYNIGHT_DEFAULTS,
    STAGE_DEFAULT_DURATIONS,
    STAGE_DRYING,
    STAGE_GERMINATION,
    STAGE_SEQUENCE,
)

_LOGGER = logging.getLogger(__name__)


# Default environmental profiles per stage (used when no recipe is loaded)
_STAGE_DEFAULTS: dict[str, dict[str, float]] = {
    "germination":  {"vpd_kpa": 0.40, "temp_c": 24.0, "rh_pct": 80.0, "photoperiod_h": 20.0},
    "seedling":     {"vpd_kpa": 0.60, "temp_c": 23.5, "rh_pct": 75.0, "photoperiod_h": 20.0},
    "early_veg":    {"vpd_kpa": 0.80, "temp_c": 24.0, "rh_pct": 70.0, "photoperiod_h": 18.0},
    "late_veg":     {"vpd_kpa": 0.95, "temp_c": 24.0, "rh_pct": 65.0, "photoperiod_h": 18.0},
    "stretch":      {"vpd_kpa": 1.05, "temp_c": 25.0, "rh_pct": 60.0, "photoperiod_h": 12.0},
    "peak_flower":  {"vpd_kpa": 1.20, "temp_c": 26.0, "rh_pct": 50.0, "photoperiod_h": 12.0},
    "ripening":     {"vpd_kpa": 1.40, "temp_c": 24.0, "rh_pct": 45.0, "photoperiod_h": 12.0},
    "drying":       {"vpd_kpa": 1.10, "temp_c": 18.0, "rh_pct": 55.0, "photoperiod_h":  0.0},
}


def _load_recipe(hass: HomeAssistant, recipe_filename: str) -> Optional[dict[str, Any]]:
    """Load and parse a YAML recipe file from the recipes/ directory.

    Returns the parsed dict or None if loading fails (fallback to hardcoded defaults).
    """
    if not recipe_filename or not recipe_filename.strip():
        return None

    # Sanitise filename to prevent path traversal
    basename = os.path.basename(recipe_filename.strip())
    recipe_path = hass.config.path(f"custom_components/{DOMAIN}/recipes/{basename}")

    if not os.path.isfile(recipe_path):
        _LOGGER.error(
            "Helix Cultivate: recipe file not found: %s. Using built-in defaults.", recipe_path
        )
        return None

    try:
        import yaml  # HA ships with PyYAML

        with open(recipe_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict) or "stages" not in data:
            _LOGGER.error(
                "Helix Cultivate: recipe file %s has invalid structure. Using built-in defaults.",
                recipe_path,
            )
            return None
        _LOGGER.info("Helix Cultivate: loaded recipe '%s'", data.get("strain_name", basename))
        return data
    except Exception as exc:  # noqa: BLE001
        _LOGGER.error(
            "Helix Cultivate: failed to parse recipe file %s: %s. Using built-in defaults.",
            recipe_path,
            exc,
        )
        return None


class StageManager:
    """Manages the grow stage state machine, smooth glides interpolation, and recipe setpoints.

    The stage manager is updated every coordinator cycle via `tick()`.
    It exposes interpolated setpoints (VPD, Temp, RH) that the coordinator
    writes into `self.vpd_target`, `self.temp_setpoint`, `self.rh_setpoint`.
    """

    def __init__(self, hass: HomeAssistant, config: dict[str, Any]) -> None:
        self._hass = hass
        self._config: dict[str, Any] = config
        self._recipe: Optional[dict[str, Any]] = None
        self._recipe_loaded_from: Optional[str] = None

        # Current stage — initialised from config
        self._current_stage: str = config.get("initial_stage", STAGE_GERMINATION)

        # Stage start date
        raw_start = config.get(CONF_STAGE_START_DATE)
        self._stage_start_date: Optional[date] = self._parse_date(raw_start)

        self._cycle_complete: bool = False

        # Actual days spent in each stage this cycle (Phase 11B harvest report).
        # Updated in `_advance_stage()` when leaving a stage; the currently
        # active stage's running total is computed on-demand in
        # `actual_stage_durations()` via `_elapsed_days()`.
        self._stage_entry_day: dict[str, int] = {}

        # Back-reference to the coordinator (set after coordinator is constructed)
        self._coord_ref: Optional["HelixCoordinator"] = None

        # Load recipe if configured
        self._maybe_reload_recipe()

    def set_coordinator_ref(self, coord: "HelixCoordinator") -> None:
        """Store a back-reference to the coordinator for override flag clearing."""
        self._coord_ref = coord

    # ── Config update ─────────────────────────────────────────────────────────

    def update_config(self, config: dict[str, Any]) -> None:
        """Called each coordinator tick with the merged config/options dict."""
        self._config = config
        self._maybe_reload_recipe()

        # Stage may have been changed externally via select entity
        new_stage = config.get("current_stage", self._current_stage)
        if new_stage in STAGE_SEQUENCE and new_stage != self._current_stage:
            _LOGGER.info(
                "Helix Cultivate: stage changed externally to '%s'", new_stage
            )
            self._current_stage = new_stage
            self._stage_start_date = date.today()

    # ── Recipe loader ─────────────────────────────────────────────────────────

    def _maybe_reload_recipe(self) -> None:
        """Reload the recipe file if the filename changed."""
        recipe_file = self._config.get(CONF_RECIPE_FILE, "")
        if recipe_file != self._recipe_loaded_from:
            self._recipe = _load_recipe(self._hass, recipe_file)
            self._recipe_loaded_from = recipe_file

    # ── Date helper ───────────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(value: Any) -> Optional[date]:
        """Parse a date from a string 'YYYY-MM-DD' or a date/datetime object."""
        if value is None:
            return None
        if isinstance(value, (date, datetime)):
            return value if isinstance(value, date) else value.date()
        try:
            return date.fromisoformat(str(value))
        except (ValueError, TypeError):
            return None

    # ── Stage profile lookup ──────────────────────────────────────────────────

    def _profile(self, stage: str) -> dict[str, Any]:
        """Return the environmental profile for a stage.

        Layered resolution (later layers override earlier ones):
          1. STAGE_DAYNIGHT_DEFAULTS built-in day/night/VPD-range profile
          2. Legacy _STAGE_DEFAULTS single-point profile (vpd_kpa/temp_c/rh_pct)
          3. Recipe YAML stage overrides (if a recipe is loaded)
          4. User-persisted stage_targets_{stage} from config entry options
        """
        base: dict[str, Any] = dict(
            STAGE_DAYNIGHT_DEFAULTS.get(stage, STAGE_DAYNIGHT_DEFAULTS[STAGE_GERMINATION])
        )
        legacy = _STAGE_DEFAULTS.get(stage, _STAGE_DEFAULTS[STAGE_GERMINATION])
        for k, v in legacy.items():
            base.setdefault(k, v)

        if self._recipe:
            stages_data = self._recipe.get("stages", {})
            stage_data = stages_data.get(stage, {})
            if stage_data:
                if "vpd_target_kpa" in stage_data:
                    base["vpd_kpa"] = float(stage_data["vpd_target_kpa"])
                if "temp_c" in stage_data:
                    base["temp_c"] = float(stage_data["temp_c"])
                if "rh_pct" in stage_data:
                    base["rh_pct"] = float(stage_data["rh_pct"])
                if "photoperiod_h" in stage_data:
                    base["photoperiod_h"] = float(stage_data["photoperiod_h"])
                for k, v in stage_data.items():
                    if k in STAGE_DAYNIGHT_DEFAULTS.get(stage, {}):
                        base[k] = v

        user_targets = self._config.get(f"stage_targets_{stage}", {})
        if isinstance(user_targets, dict):
            base.update(user_targets)

        return base

    def _duration(self, stage: str) -> int:
        """Return the target duration (days) for a stage."""
        if self._recipe:
            stages_data = self._recipe.get("stages", {})
            stage_data = stages_data.get(stage, {})
            if "duration_days" in stage_data:
                return int(stage_data["duration_days"])
        return STAGE_DEFAULT_DURATIONS.get(stage, 14)

    # ── Elapsed days ──────────────────────────────────────────────────────────

    def _elapsed_days(self) -> int:
        """Days elapsed since stage start date, 0 if start not set."""
        if self._stage_start_date is None:
            return 0
        delta = date.today() - self._stage_start_date
        return max(0, delta.days)

    # ── State machine tick ────────────────────────────────────────────────────

    def tick(self) -> None:
        """Evaluate stage progression. Called every coordinator update cycle."""
        if self._cycle_complete:
            return

        prog_mode = self._config.get(CONF_PROGRESSION_MODE, PROG_MANUAL)
        if prog_mode != PROG_TIMEFRAME:
            return  # Manual mode — do nothing

        elapsed = self._elapsed_days()
        duration = self._duration(self._current_stage)

        if elapsed >= duration:
            self._advance_stage()

    def _advance_stage(self) -> None:
        """Advance to the next stage in the sequence."""
        if self._current_stage == STAGE_DRYING:
            self._stage_entry_day[self._current_stage] = self._elapsed_days()
            self._cycle_complete = True
            _LOGGER.info("Helix Cultivate: Grow cycle complete — reached end of Drying stage.")
            return

        # Record actual days spent in the stage being left (for harvest report)
        self._stage_entry_day[self._current_stage] = self._elapsed_days()

        idx = STAGE_SEQUENCE.index(self._current_stage)
        next_stage = STAGE_SEQUENCE[idx + 1]
        _LOGGER.info(
            "Helix Cultivate: Advancing stage %s → %s", self._current_stage, next_stage
        )
        self._current_stage = next_stage
        self._stage_start_date = date.today()
        # Persist the new stage back into config so entities reflect it
        self._config["current_stage"] = self._current_stage
        # Clear manual override flags — fresh stage = fresh glide
        if self._coord_ref is not None:
            self._coord_ref.temp_setpoint_manual_override = False
            self._coord_ref.vpd_target_manual_override = False
            self._coord_ref.rh_setpoint_manual_override = False

    # ── Manual stage override (called by select entity) ───────────────────────

    def set_stage(self, stage: str) -> None:
        """Manually override the current stage."""
        if stage not in STAGE_SEQUENCE:
            _LOGGER.warning("Helix Cultivate: invalid stage '%s' — ignoring", stage)
            return
        _LOGGER.info("Helix Cultivate: manual stage set to '%s'", stage)
        self._current_stage = stage
        self._stage_start_date = date.today()
        self._cycle_complete = False
        self._config["current_stage"] = stage
        # Clear manual override flags — fresh stage = fresh glide
        if self._coord_ref is not None:
            self._coord_ref.temp_setpoint_manual_override = False
            self._coord_ref.vpd_target_manual_override = False
            self._coord_ref.rh_setpoint_manual_override = False

    # ── Smooth glides interpolation ───────────────────────────────────────────

    def _interpolate(self, key: str) -> Optional[float]:
        """Linearly interpolate a setpoint between current and next stage profiles.

        Returns None if smooth glides is disabled or this is the final stage.
        """
        return self._interpolate_key(key)

    def _interpolate_key(self, key: str) -> Optional[float]:
        """Linearly interpolate an arbitrary profile key between current and next stage.

        Generalised version of `_interpolate()` — works for any numeric key
        present in the resolved `_profile()` dict (vpd_kpa, temp_c, rh_pct,
        day_temp_c, night_vpd_min, fan_speed_pct, etc).

        Returns None if smooth glides is disabled or this is the final stage.
        """
        smooth = self._config.get(CONF_SMOOTH_GLIDES, True)
        if not smooth:
            return None

        elapsed = self._elapsed_days()
        duration = self._duration(self._current_stage)

        if duration <= 0:
            return None

        current_profile = self._profile(self._current_stage)

        # Find next stage for interpolation target
        idx = STAGE_SEQUENCE.index(self._current_stage)
        if idx >= len(STAGE_SEQUENCE) - 1:
            val = current_profile.get(key)
            return float(val) if val is not None else None

        next_profile = self._profile(STAGE_SEQUENCE[idx + 1])
        start_val = current_profile.get(key)
        end_val = next_profile.get(key)

        if start_val is None or end_val is None:
            return float(start_val) if start_val is not None else None

        t = min(1.0, max(0.0, elapsed / duration))
        return float(start_val) + (float(end_val) - float(start_val)) * t

    # ── Public setpoint accessors ─────────────────────────────────────────────

    def current_vpd_target(self) -> Optional[float]:
        """Return the current (possibly interpolated) VPD target [kPa]."""
        interp = self._interpolate("vpd_kpa")
        if interp is not None:
            return interp
        return self._profile(self._current_stage).get("vpd_kpa")

    def current_temp_setpoint(self) -> Optional[float]:
        """Return the current (possibly interpolated) temperature setpoint [°C]."""
        interp = self._interpolate("temp_c")
        if interp is not None:
            return interp
        return self._profile(self._current_stage).get("temp_c")

    def current_rh_setpoint(self) -> Optional[float]:
        """Return the current (possibly interpolated) RH setpoint [%]."""
        interp = self._interpolate("rh_pct")
        if interp is not None:
            return interp
        return self._profile(self._current_stage).get("rh_pct")

    def current_photoperiod_h(self) -> float:
        """Return the target photoperiod [hours] for the current stage."""
        return self._profile(self._current_stage).get("photoperiod_h", 12.0)

    # ── Drying zone lock (Phase 8) ─────────────────────────────────────────────

    def is_drying_unlocked(self) -> bool:
        """Return True only if the operator has explicitly enabled custom drying profiles."""
        return bool(
            self._config.get(CONF_DRYING_CUSTOM_UNLOCKED, DEFAULT_DRYING_CUSTOM_UNLOCKED)
        )

    # ── Day/night range-aware accessors (Phase 5, locked-aware Phase 8) ───────

    def current_vpd_range(self, is_day: bool) -> tuple[float, float]:
        """Return (vpd_min, vpd_max) interpolated between current and next stage.

        When the current stage is drying and the operator has not explicitly
        unlocked custom profiles, returns a tight locked band around the fixed
        15.5°C / 60% RH cure profile (leaf VPD ≈ 1.09 kPa, leaf offset −2.5°C)
        so the predictive dVPD/dt engine stays stable regardless of recipe or
        user-persisted stage_targets overrides.
        """
        if self._current_stage == STAGE_DRYING and not self.is_drying_unlocked():
            return (1.05, 1.15)
        min_key = "day_vpd_min" if is_day else "night_vpd_min"
        max_key = "day_vpd_max" if is_day else "night_vpd_max"
        vpd_min = self._interpolate_key(min_key)
        vpd_max = self._interpolate_key(max_key)
        if vpd_min is None:
            vpd_min = self._profile(self._current_stage).get(min_key, 0.8)
        if vpd_max is None:
            vpd_max = self._profile(self._current_stage).get(max_key, 1.2)
        return (float(vpd_min), float(vpd_max))

    def current_temp_anchor(self, is_day: bool) -> float:
        """Return the interpolated day or night temperature anchor [°C].

        Locked-drying guard: see `current_vpd_range()` docstring.
        """
        if self._current_stage == STAGE_DRYING and not self.is_drying_unlocked():
            return DRYING_LOCKED_TEMP_C
        key = "day_temp_c" if is_day else "night_temp_c"
        val = self._interpolate_key(key)
        if val is not None:
            return float(val)
        return float(self._profile(self._current_stage).get(key, 24.0))

    def current_fan_speed_pct(self) -> float:
        """Return the interpolated base fan speed [%] for the current stage."""
        val = self._interpolate_key("fan_speed_pct")
        if val is not None:
            return float(val)
        return float(self._profile(self._current_stage).get("fan_speed_pct", 50.0))

    # ── Public status accessors ───────────────────────────────────────────────

    @property
    def current_stage(self) -> str:
        """Return the slug of the current grow stage."""
        return self._current_stage

    @property
    def elapsed_days(self) -> int:
        """Days elapsed in the current stage."""
        return self._elapsed_days()

    @property
    def stage_duration(self) -> int:
        """Target duration (days) of the current stage."""
        return self._duration(self._current_stage)

    @property
    def cycle_complete(self) -> bool:
        """True when the grow cycle has reached the end of the Drying stage."""
        return self._cycle_complete

    @property
    def smooth_glides_active(self) -> bool:
        """True when smooth glides interpolation is enabled."""
        return bool(self._config.get(CONF_SMOOTH_GLIDES, True))

    # ── Harvest close-out helpers (Phase 11B) ─────────────────────────────────

    def actual_stage_durations(self) -> dict[str, int]:
        """Return {stage: actual_days_spent} for this completed cycle.

        Stages already left use the value recorded in `_stage_entry_day`
        (captured in `_advance_stage()`); the currently active stage's
        running total is computed live via `_elapsed_days()`.
        """
        durations: dict[str, int] = dict(self._stage_entry_day)
        durations[self._current_stage] = self._elapsed_days()
        return durations

    def planned_stage_durations(self) -> dict[str, int]:
        """Return {stage: planned_duration_days} for every stage in sequence."""
        return {stage: self._duration(stage) for stage in STAGE_SEQUENCE}

    def reset_cycle(self) -> None:
        """Reset the state machine to the beginning of a fresh grow cycle.

        Called by `HelixCoordinator.close_out_harvest()` after the harvest
        record has been successfully archived.
        """
        self._current_stage = STAGE_SEQUENCE[0]
        self._stage_start_date = date.today()
        self._stage_entry_day = {}
        self._cycle_complete = False
        self._config["current_stage"] = self._current_stage
        _LOGGER.info("Helix Cultivate: cycle reset — new grow cycle started at '%s'", self._current_stage)

    # ── Recipe export / import round-trip (Phase 11E) ─────────────────────────

    def export_current_recipe(self) -> str:
        """Serialise the currently-resolved per-stage profiles to YAML text."""
        import yaml

        stages: dict[str, Any] = {}
        for stage in STAGE_SEQUENCE:
            p = self._profile(stage)
            vpd_kpa = p.get("vpd_kpa", 1.0)
            temp_c = p.get("temp_c", 24.0)
            stages[stage] = {
                "duration_days": self._duration(stage),
                "vpd_target_kpa": vpd_kpa,
                "day_vpd_min": p.get("day_vpd_min", vpd_kpa),
                "day_vpd_max": p.get("day_vpd_max", vpd_kpa),
                "night_vpd_min": p.get("night_vpd_min", vpd_kpa),
                "night_vpd_max": p.get("night_vpd_max", vpd_kpa),
                "temp_c": temp_c,
                "day_temp_c": p.get("day_temp_c", temp_c),
                "night_temp_c": p.get("night_temp_c", temp_c),
                "rh_pct": p.get("rh_pct", 60.0),
                "photoperiod_h": p.get("photoperiod_h", 12.0),
            }
        return yaml.safe_dump({"stages": stages}, sort_keys=False, allow_unicode=True)

    def import_recipe(self, yaml_text: str) -> None:
        """Validate and apply a pasted recipe YAML, persisting each stage's
        values under the existing `stage_targets_{stage}` config-entry option
        pattern so they immediately take precedence per `_profile()`'s
        layered resolution order.

        Raises ValueError with a human-readable message on any schema
        violation. Does not touch the config entry directly — the caller
        (WS handler) is responsible for persisting via async_update_entry.
        """
        import yaml

        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc

        if not isinstance(data, dict) or "stages" not in data:
            raise ValueError("Recipe must be a mapping with a top-level 'stages' key")

        stages_data = data["stages"]
        if not isinstance(stages_data, dict):
            raise ValueError("'stages' must be a mapping of stage-slug → profile")

        missing = [s for s in STAGE_SEQUENCE if s not in stages_data]
        if missing:
            raise ValueError(f"Recipe is missing required stages: {', '.join(missing)}")

        required_keys = ("duration_days", "vpd_target_kpa", "temp_c", "rh_pct", "photoperiod_h")
        new_stage_targets: dict[str, dict[str, Any]] = {}

        for stage in STAGE_SEQUENCE:
            stage_data = stages_data[stage]
            if not isinstance(stage_data, dict):
                raise ValueError(f"Stage '{stage}' profile must be a mapping")
            missing_keys = [k for k in required_keys if k not in stage_data]
            if missing_keys:
                raise ValueError(
                    f"Stage '{stage}' is missing required keys: {', '.join(missing_keys)}"
                )
            try:
                vpd_kpa = float(stage_data["vpd_target_kpa"])
                temp_c = float(stage_data["temp_c"])
                rh_pct = float(stage_data["rh_pct"])
                photoperiod_h = float(stage_data["photoperiod_h"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Stage '{stage}' has non-numeric required field: {exc}") from exc

            # Backward compatibility: populate day/night from single-value keys
            # when the imported recipe predates the day/night schema.
            targets: dict[str, Any] = {
                "vpd_kpa": vpd_kpa,
                "temp_c": temp_c,
                "rh_pct": rh_pct,
                "photoperiod_h": photoperiod_h,
                "day_vpd_min": float(stage_data.get("day_vpd_min", vpd_kpa)),
                "day_vpd_max": float(stage_data.get("day_vpd_max", vpd_kpa)),
                "night_vpd_min": float(stage_data.get("night_vpd_min", vpd_kpa)),
                "night_vpd_max": float(stage_data.get("night_vpd_max", vpd_kpa)),
                "day_temp_c": float(stage_data.get("day_temp_c", temp_c)),
                "night_temp_c": float(stage_data.get("night_temp_c", temp_c)),
            }
            new_stage_targets[stage] = targets

        # Apply to in-memory config immediately so subsequent _profile() calls
        # within this same tick reflect the imported recipe.
        for stage, targets in new_stage_targets.items():
            self._config[f"stage_targets_{stage}"] = targets

        _LOGGER.info("Helix Cultivate: recipe imported and applied to %d stages", len(new_stage_targets))
