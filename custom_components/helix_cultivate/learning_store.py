"""Helix Cultivate — Environmental Learning System persistent store.

Same lightweight Store-based persistence pattern as journal_store.py — no
external database required. Holds downsampled passive-logging summaries
(not raw per-tick resolution), regression buckets used for
confidence-weighted blending, cross-zone response observations, and durable
in-progress-test state so a restart never leaves an actuator stuck
deliberately disabled with no plan to resume it.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)

LEARNING_STORE_VERSION: int = 1
LEARNING_STORE_KEY: str = "helix_cultivate_learning"

# Hourly logs are capped to bound storage growth — this is roughly 2 years
# of continuous hourly logging per zone at 3 zones, comfortably more history
# than the regression buckets (which are the actual long-term model state)
# need raw rows for.
MAX_HOURLY_LOGS: int = 20000
MAX_TEST_HISTORY: int = 500

EMPTY_LEARNING_STORE: dict[str, Any] = {
    # One row per (zone, hour) — {zone, ts, outdoor_temp_c, indoor_temp_c,
    # actuator_duty_pct, lights_on, light_pct, occupied_hours_weight,
    # cycle_id}. This is Part 7.5/7.6's passive continuous logging.
    "hourly_logs": [],
    # Simple running-mean state keyed by "{zone}|{bucket_key}" (e.g. an
    # outdoor-temp bucket, or the fixed "lights_off_response" key) —
    # {count, mean_response, updated_at}. Used only by Deep Calibration's
    # own decay tracking and the lights-off preheat bucket — both
    # inherently single-condition measurements a multi-variable fit
    # wouldn't add anything to. See regression_models below for the
    # multi-variable model behind confidence-weighted blending (7.3).
    "regression_buckets": {},
    # Cross-zone (Conditioning Room -> dependent zone) response
    # observations from Live Actuator Response Testing (7.4) — keyed by
    # dependent zone name — {count, mean_lag_min, mean_magnitude_ratio}.
    "cross_zone_response": {},
    # Fitted multi-variable OLS regression per zone (v1.4.1 Part 4) — the
    # actual model behind confidence-weighted blending now; regression_
    # buckets above remains a separate, simpler running-mean dataset used
    # only by Deep Calibration's own decay tracking and the lights-off
    # response bucket, neither of which need a multi-variable fit.
    "regression_models": {},
    # Durable in-progress test state (7.7) — None when no test is running.
    "active_test": None,
    "test_history": [],
}


class LearningStore:
    """Manages Environmental Learning System data via HA's Store helper."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass
        self._store: Store = Store(hass, LEARNING_STORE_VERSION, LEARNING_STORE_KEY)
        self._data: dict[str, Any] = copy.deepcopy(EMPTY_LEARNING_STORE)

    async def async_load(self) -> None:
        raw: Optional[dict[str, Any]] = await self._store.async_load()
        if raw is None:
            self._data = copy.deepcopy(EMPTY_LEARNING_STORE)
            return
        merged = copy.deepcopy(EMPTY_LEARNING_STORE)
        merged.update(raw)
        self._data = merged

    async def _save(self) -> None:
        await self._store.async_save(self._data)

    # ── Passive logging (7.5/7.6) ──────────────────────────────────────────────

    async def record_hourly_log(self, entry: dict[str, Any]) -> None:
        entry = {**entry, "ts": entry.get("ts") or datetime.now(timezone.utc).isoformat()}
        self._data["hourly_logs"].append(entry)
        if len(self._data["hourly_logs"]) > MAX_HOURLY_LOGS:
            self._data["hourly_logs"] = self._data["hourly_logs"][-MAX_HOURLY_LOGS:]
        await self._save()

    def get_hourly_logs(self, zone: Optional[str] = None) -> list[dict[str, Any]]:
        logs = self._data.get("hourly_logs", [])
        if zone is None:
            return list(logs)
        return [row for row in logs if row.get("zone") == zone]

    # ── Regression buckets (7.3/7.6) ───────────────────────────────────────────

    @staticmethod
    def _bucket_id(zone: str, bucket_key: str) -> str:
        return f"{zone}|{bucket_key}"

    async def update_regression_bucket(
        self, zone: str, bucket_key: str, observation: float
    ) -> dict[str, Any]:
        """Fold a new observation into a bucket's running mean via simple
        incremental averaging — deliberately not a heavier model: this is
        the confidence-weighted-blending input, not a claim of predictive
        precision beyond what a running mean per condition bucket can
        honestly provide. Returns the updated bucket.
        """
        buckets = self._data.setdefault("regression_buckets", {})
        bid = self._bucket_id(zone, bucket_key)
        bucket = buckets.get(bid, {"count": 0, "mean_response": 0.0})
        count = bucket["count"] + 1
        mean = bucket["mean_response"] + (observation - bucket["mean_response"]) / count
        bucket = {
            "count": count,
            "mean_response": mean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        buckets[bid] = bucket
        await self._save()
        return bucket

    def get_regression_bucket(self, zone: str, bucket_key: str) -> Optional[dict[str, Any]]:
        return self._data.get("regression_buckets", {}).get(self._bucket_id(zone, bucket_key))

    # ── Fitted multi-variable regression model (v1.4.1 Part 4) ─────────────────

    async def set_regression_model(self, zone: str, model: dict[str, Any]) -> None:
        self._data.setdefault("regression_models", {})[zone] = model
        await self._save()

    def get_regression_model(self, zone: str) -> Optional[dict[str, Any]]:
        return self._data.get("regression_models", {}).get(zone)

    # ── Cross-zone response (7.4) ──────────────────────────────────────────────

    async def update_cross_zone_response(
        self, dependent_zone: str, lag_min: float, magnitude_ratio: float
    ) -> dict[str, Any]:
        store = self._data.setdefault("cross_zone_response", {})
        existing = store.get(dependent_zone, {"count": 0, "mean_lag_min": 0.0, "mean_magnitude_ratio": 0.0})
        count = existing["count"] + 1
        mean_lag = existing["mean_lag_min"] + (lag_min - existing["mean_lag_min"]) / count
        mean_mag = existing["mean_magnitude_ratio"] + (magnitude_ratio - existing["mean_magnitude_ratio"]) / count
        record = {"count": count, "mean_lag_min": mean_lag, "mean_magnitude_ratio": mean_mag}
        store[dependent_zone] = record
        await self._save()
        return record

    def get_cross_zone_response(self, dependent_zone: str) -> Optional[dict[str, Any]]:
        return self._data.get("cross_zone_response", {}).get(dependent_zone)

    # ── Active test durability (7.7) ───────────────────────────────────────────

    async def set_active_test(self, test: Optional[dict[str, Any]]) -> None:
        self._data["active_test"] = test
        await self._save()

    def get_active_test(self) -> Optional[dict[str, Any]]:
        active = self._data.get("active_test")
        return dict(active) if active is not None else None

    async def append_test_history(self, record: dict[str, Any]) -> None:
        self._data.setdefault("test_history", []).append(record)
        if len(self._data["test_history"]) > MAX_TEST_HISTORY:
            self._data["test_history"] = self._data["test_history"][-MAX_TEST_HISTORY:]
        await self._save()

    def get_test_history(self) -> list[dict[str, Any]]:
        return list(self._data.get("test_history", []))


async def async_setup_learning_store(hass: HomeAssistant) -> LearningStore:
    """Initialise the learning store once, hass.data-cached like journal_store."""
    from .const import DOMAIN

    if "learning_store" in hass.data.get(DOMAIN, {}):
        return hass.data[DOMAIN]["learning_store"]

    store = LearningStore(hass)
    await store.async_load()
    hass.data.setdefault(DOMAIN, {})["learning_store"] = store
    return store
