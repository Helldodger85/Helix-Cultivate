"""Tests for the Energy & ROI gear icon's backend surface:
- _current_tariff_rate() correctly selecting Peak/Shoulder/Off-Peak based on
  simulated times crossing each configured window boundary.
- _accumulate_energy()'s per-zone tracking, the fixed incremental-cost bug
  (previously recomputed from total_kwh * current_rate, which silently
  mispriced time-of-use cycles), per-zone EM enable/disable exclusion from
  the Global aggregate (while still accumulating in the background), and no
  double-counting of Global's own direct EM slots.
- reset_energy_cycle() archiving current totals and zeroing every
  accumulator, with the archived data remaining retrievable afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate.coordinator as coordinator_module
from custom_components.helix_cultivate.const import (
    CONF_EM_DRYING_ENABLED,
    CONF_EM_DRYING_S1,
    CONF_EM_GLOBAL_S1,
    CONF_EM_ZONE1_ENABLED,
    CONF_EM_ZONE1_S1,
    CONF_EM_ZONE2_ENABLED,
    CONF_EM_ZONE2_S1,
    CONF_TARIFF_ANYTIME,
    CONF_TARIFF_MODE,
    CONF_TARIFF_OFFPEAK,
    CONF_TARIFF_PEAK,
    CONF_TARIFF_PEAK_END,
    CONF_TARIFF_PEAK_START,
    CONF_TARIFF_SHOULDER,
    CONF_TARIFF_SHOULDER_END,
    CONF_TARIFF_SHOULDER_START,
    NS_ENERGY,
    TARIFF_ANYTIME,
    TARIFF_DUAL,
    TARIFF_TRIPLE,
)
from custom_components.helix_cultivate.coordinator import HelixCoordinator

DOMAIN = "helix_cultivate"


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 15, hour, minute, 0, tzinfo=timezone.utc)


@pytest.fixture
def fake_coord(monkeypatch):
    coord = MagicMock()
    coord._config = {}
    coord._get = lambda key, default=None: coord._config.get(key, default)
    coord.hass = MagicMock()
    coord.hass.states = MagicMock()
    coord.hass.states.get = MagicMock(return_value=None)
    coord.hass.data = {DOMAIN: {}}
    coord._entry = MagicMock(entry_id="entry123")
    coord.data = {NS_ENERGY: {}}

    coord._zone1_cycle_kwh = 0.0
    coord._zone2_cycle_kwh = 0.0
    coord._drying_cycle_kwh = 0.0
    coord._global_cycle_kwh = 0.0
    coord._zone1_cycle_cost = 0.0
    coord._zone2_cycle_cost = 0.0
    coord._drying_cycle_cost = 0.0
    coord._global_cycle_cost = 0.0
    coord._cycle_kwh = 0.0
    coord._cycle_cost = 0.0
    coord._last_energy_tick = None

    coord._safe_read_watts = lambda eid: HelixCoordinator._safe_read_watts(coord, eid)
    coord._zone_em_watts = lambda keys: HelixCoordinator._zone_em_watts(coord, keys)
    coord._current_tariff_rate = lambda: HelixCoordinator._current_tariff_rate(coord)
    coord._accumulate_energy = lambda interval: HelixCoordinator._accumulate_energy(coord, interval)
    coord.reset_energy_cycle = lambda: HelixCoordinator.reset_energy_cycle(coord)

    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(12))
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(12))
    return coord


def _mock_watt_state(value: float):
    return MagicMock(state=str(value))


# ── _current_tariff_rate ─────────────────────────────────────────────────────

def test_anytime_mode_uses_flat_rate(fake_coord):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_ANYTIME
    fake_coord._config[CONF_TARIFF_ANYTIME] = 0.28
    assert fake_coord._current_tariff_rate() == 0.28


def test_dual_mode_inside_peak_window(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_DUAL
    fake_coord._config[CONF_TARIFF_PEAK_START] = "07:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(12))
    assert fake_coord._current_tariff_rate() == 0.45


def test_dual_mode_outside_peak_window_falls_to_offpeak(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_DUAL
    fake_coord._config[CONF_TARIFF_PEAK_START] = "07:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(23))
    assert fake_coord._current_tariff_rate() == 0.15


def test_dual_mode_at_exact_peak_start_boundary_is_inclusive(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_DUAL
    fake_coord._config[CONF_TARIFF_PEAK_START] = "07:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(7, 0))
    assert fake_coord._current_tariff_rate() == 0.45


def test_dual_mode_at_exact_peak_end_boundary_is_exclusive(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_DUAL
    fake_coord._config[CONF_TARIFF_PEAK_START] = "07:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(21, 0))
    assert fake_coord._current_tariff_rate() == 0.15


def test_triple_mode_inside_shoulder_window(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_TRIPLE
    fake_coord._config[CONF_TARIFF_PEAK_START] = "17:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_START] = "07:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_END] = "17:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_SHOULDER] = 0.30
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(12))
    assert fake_coord._current_tariff_rate() == 0.30


def test_triple_mode_inside_peak_window_beats_shoulder(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_TRIPLE
    fake_coord._config[CONF_TARIFF_PEAK_START] = "17:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_START] = "07:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_END] = "22:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_SHOULDER] = 0.30
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(18))
    assert fake_coord._current_tariff_rate() == 0.45


def test_triple_mode_outside_all_windows_falls_to_offpeak(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_TRIPLE
    fake_coord._config[CONF_TARIFF_PEAK_START] = "17:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_START] = "07:00"
    fake_coord._config[CONF_TARIFF_SHOULDER_END] = "17:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.45
    fake_coord._config[CONF_TARIFF_SHOULDER] = 0.30
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.15
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(2))
    assert fake_coord._current_tariff_rate() == 0.15


# ── _accumulate_energy: incremental cost fix ────────────────────────────────

def test_cost_accumulates_incrementally_not_repriced_at_current_rate(fake_coord, monkeypatch):
    """Regression test for the fixed bug: cost must reflect each interval's
    own rate at the time it was accumulated, not total_kwh * whatever rate
    happens to be active when last queried."""
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_DUAL
    fake_coord._config[CONF_TARIFF_PEAK_START] = "07:00"
    fake_coord._config[CONF_TARIFF_PEAK_END] = "21:00"
    fake_coord._config[CONF_TARIFF_PEAK] = 0.40
    fake_coord._config[CONF_TARIFF_OFFPEAK] = 0.10
    fake_coord._config[CONF_EM_GLOBAL_S1] = "sensor.global_meter"
    fake_coord.hass.states.get = MagicMock(return_value=_mock_watt_state(1000.0))  # 1kW

    # First tick: seed _last_energy_tick, no accumulation yet.
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(12, 0))
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(12, 0))
    fake_coord._accumulate_energy(3600)

    # Second tick, 1 hour later, still inside Peak window (0.40/kWh).
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(13, 0))
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(13, 0))
    fake_coord._accumulate_energy(3600)
    # 1kW for 1h = 1 kWh at Peak (0.40) => cost so far = 0.40
    assert fake_coord._cycle_kwh == pytest.approx(1.0)
    assert fake_coord._cycle_cost == pytest.approx(0.40)

    # Third tick, 9 hours later (22:00), now Off-Peak (0.10/kWh) — the
    # PREVIOUS hour's cost must stay priced at Peak; only this new 9-hour
    # span prices at Off-Peak.
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(22, 0))
    monkeypatch.setattr(coordinator_module.dt_util, "now", lambda: _at(22, 0))
    fake_coord._accumulate_energy(3600)
    assert fake_coord._cycle_kwh == pytest.approx(10.0)  # 1kWh (12-13h) + 9kWh (13-22h)
    # Correct: 1kWh@0.40 + 9kWh@0.10 = 0.40 + 0.90 = 1.30. The old buggy
    # formula (total_kwh * current_rate) would give 10.0 * 0.10 = 1.00 instead.
    assert fake_coord._cycle_cost == pytest.approx(1.30)


# ── Per-zone enable/disable exclusion + no double-counting ─────────────────

def test_disabled_zone_excluded_from_total_but_keeps_accumulating(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_ANYTIME
    fake_coord._config[CONF_TARIFF_ANYTIME] = 0.20
    fake_coord._config[CONF_EM_ZONE2_S1] = "sensor.zone2_meter"
    fake_coord._config[CONF_EM_ZONE2_ENABLED] = False

    def states_get(eid):
        if eid == "sensor.zone2_meter":
            return _mock_watt_state(1000.0)
        return None
    fake_coord.hass.states.get = MagicMock(side_effect=states_get)

    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(12, 0))
    fake_coord._accumulate_energy(3600)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(13, 0))
    fake_coord._accumulate_energy(3600)

    # Zone 2 kept accumulating in the background...
    assert fake_coord._zone2_cycle_kwh == pytest.approx(1.0)
    # ...but is excluded from the displayed aggregate while disabled.
    assert fake_coord._cycle_kwh == pytest.approx(0.0)
    assert fake_coord._cycle_cost == pytest.approx(0.0)

    # Re-enabling resumes with the true accumulated total, not a gap.
    fake_coord._config[CONF_EM_ZONE2_ENABLED] = True
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(14, 0))
    fake_coord._accumulate_energy(3600)
    assert fake_coord._cycle_kwh == pytest.approx(2.0)  # 1.0 background + 1.0 this tick


def test_global_and_enabled_zones_summed_without_double_counting(fake_coord, monkeypatch):
    fake_coord._config[CONF_TARIFF_MODE] = TARIFF_ANYTIME
    fake_coord._config[CONF_TARIFF_ANYTIME] = 1.0  # $1/kWh for easy arithmetic
    fake_coord._config[CONF_EM_ZONE1_S1] = "sensor.zone1_meter"
    fake_coord._config[CONF_EM_ZONE2_S1] = "sensor.zone2_meter"
    fake_coord._config[CONF_EM_DRYING_S1] = "sensor.drying_meter"
    fake_coord._config[CONF_EM_GLOBAL_S1] = "sensor.global_meter"

    watts = {
        "sensor.zone1_meter": 500.0,
        "sensor.zone2_meter": 1000.0,
        "sensor.drying_meter": 250.0,
        "sensor.global_meter": 2000.0,
    }
    fake_coord.hass.states.get = MagicMock(
        side_effect=lambda eid: _mock_watt_state(watts[eid]) if eid in watts else None
    )

    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(12, 0))
    fake_coord._accumulate_energy(3600)
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: _at(13, 0))
    fake_coord._accumulate_energy(3600)

    # Sum of all four zones' watts for 1h = (500+1000+250+2000)/1000 = 3.75 kWh
    assert fake_coord._cycle_kwh == pytest.approx(3.75)
    assert fake_coord._cycle_cost == pytest.approx(3.75)


# ── reset_energy_cycle ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset_archives_and_zeroes_all_accumulators(fake_coord):
    journal = MagicMock()
    journal.async_set_previous_cycle_energy = AsyncMock(
        return_value={"cycle_kwh": 12.5, "cycle_cost_usd": 3.75, "archived_at": "2026-01-15T12:00:00+00:00"}
    )
    fake_coord.hass.data = {DOMAIN: {"journal_store": journal}}
    fake_coord._cycle_kwh = 12.5
    fake_coord._cycle_cost = 3.75
    fake_coord._zone1_cycle_kwh = 4.0
    fake_coord._zone2_cycle_kwh = 8.5
    fake_coord._global_cycle_kwh = 0.0
    fake_coord._zone1_cycle_cost = 1.2
    fake_coord._zone2_cycle_cost = 2.55
    fake_coord._last_energy_tick = _at(12)

    record = await fake_coord.reset_energy_cycle()

    journal.async_set_previous_cycle_energy.assert_awaited_once_with("entry123", 12.5, 3.75)
    assert record["cycle_kwh"] == 12.5
    assert record["cycle_cost_usd"] == 3.75

    assert fake_coord._cycle_kwh == 0.0
    assert fake_coord._cycle_cost == 0.0
    assert fake_coord._zone1_cycle_kwh == 0.0
    assert fake_coord._zone2_cycle_kwh == 0.0
    assert fake_coord._drying_cycle_kwh == 0.0
    assert fake_coord._global_cycle_kwh == 0.0
    assert fake_coord._zone1_cycle_cost == 0.0
    assert fake_coord._zone2_cycle_cost == 0.0
    assert fake_coord._last_energy_tick is None
    assert fake_coord.data[NS_ENERGY]["cycle_kwh"] == 0.0
    assert fake_coord.data[NS_ENERGY]["cycle_cost_usd"] == 0.0
