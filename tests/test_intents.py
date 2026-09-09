"""Tests for the Helix Cultivate Voice Assist intent handlers (intents.py).

Builds a real `homeassistant.helpers.intent.Intent` (a plain data holder) with
a MagicMock hass and a MagicMock coordinator standing in for HelixCoordinator,
registered where `_first_coordinator()` looks for it — no running Home
Assistant core required.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.core import Context
from homeassistant.helpers import intent as ha_intent

from custom_components.helix_cultivate.const import DOMAIN, NS_CLIMATE
from custom_components.helix_cultivate.coordinator import HelixCoordinator
from custom_components.helix_cultivate.intents import (
    GetStageIntentHandler,
    GetVpdIntentHandler,
    HarvestEstimateIntentHandler,
)


def _make_intent(hass, intent_type: str) -> ha_intent.Intent:
    return ha_intent.Intent(
        hass=hass,
        platform="test",
        intent_type=intent_type,
        slots={},
        text_input=None,
        context=Context(),
        language="en",
    )


@pytest.fixture
def fake_hass_with_coordinator():
    hass = MagicMock()
    coord = MagicMock(spec=HelixCoordinator)
    coord.data = {NS_CLIMATE: {"leaf_vpd_kpa": 1.0}}
    coord.vpd_target_min = 0.8
    coord.vpd_target_max = 1.2

    stage_manager = MagicMock()
    stage_manager.cycle_complete = False
    stage_manager.current_stage = "peak_flower"
    stage_manager.elapsed_days = 10
    stage_manager.stage_duration = 28
    stage_manager.planned_stage_durations = MagicMock(
        return_value={
            "germination": 4, "seedling": 10, "early_veg": 14, "late_veg": 14,
            "stretch": 14, "peak_flower": 28, "ripening": 14, "drying": 10,
        }
    )
    coord.stage_manager = stage_manager

    hass.data = {DOMAIN: {"some_entry_id": coord}}
    return hass, coord


@pytest.mark.asyncio
async def test_get_vpd_in_range(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    intent_obj = _make_intent(hass, "HelixCultivateGetVpd")
    response = await GetVpdIntentHandler().async_handle(intent_obj)
    assert "1.00" in response.speech["plain"]["speech"]
    assert "target range" in response.speech["plain"]["speech"]
    assert "below" not in response.speech["plain"]["speech"]
    assert "above" not in response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_get_vpd_below_range(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    coord.data = {NS_CLIMATE: {"leaf_vpd_kpa": 0.5}}
    intent_obj = _make_intent(hass, "HelixCultivateGetVpd")
    response = await GetVpdIntentHandler().async_handle(intent_obj)
    assert "below" in response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_get_vpd_above_range(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    coord.data = {NS_CLIMATE: {"leaf_vpd_kpa": 1.8}}
    intent_obj = _make_intent(hass, "HelixCultivateGetVpd")
    response = await GetVpdIntentHandler().async_handle(intent_obj)
    assert "above" in response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_get_vpd_no_coordinator():
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    intent_obj = _make_intent(hass, "HelixCultivateGetVpd")
    response = await GetVpdIntentHandler().async_handle(intent_obj)
    assert "isn't set up" in response.speech["plain"]["speech"]


@pytest.mark.asyncio
async def test_get_stage(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    intent_obj = _make_intent(hass, "HelixCultivateGetStage")
    response = await GetStageIntentHandler().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert "Peak Flower" in speech
    assert "day 10" in speech
    assert "28" in speech


@pytest.mark.asyncio
async def test_harvest_estimate_sums_remaining_stages(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    # peak_flower: 28 - 10 = 18 remaining; then ripening (14); drying excluded.
    intent_obj = _make_intent(hass, "HelixCultivateHarvestEstimate")
    response = await HarvestEstimateIntentHandler().async_handle(intent_obj)
    speech = response.speech["plain"]["speech"]
    assert "32 days" in speech  # 18 + 14


@pytest.mark.asyncio
async def test_harvest_estimate_already_drying(fake_hass_with_coordinator):
    hass, coord = fake_hass_with_coordinator
    coord.stage_manager.current_stage = "drying"
    intent_obj = _make_intent(hass, "HelixCultivateHarvestEstimate")
    response = await HarvestEstimateIntentHandler().async_handle(intent_obj)
    assert "already" in response.speech["plain"]["speech"]
