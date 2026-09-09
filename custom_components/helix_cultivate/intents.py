"""Helix Cultivate — Voice Assist intents.

Registers a small set of custom intents so users can ask HA's Assist (voice
or text) about their grow's current state — "What's my VPD right now",
"How many days until harvest", "What stage is my grow in". Responses are
kept to a sentence since they're spoken aloud, not a data dump.

Paired sentence triggers live in custom_sentences/en/helix_cultivate.yaml.
This module is for spoken/typed Q&A only — see docs/events.md for the HA
bus events used to build automations against grow-state changes instead.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent

from .const import DOMAIN, NS_CLIMATE, STAGE_DRYING, STAGE_LABELS, STAGE_SEQUENCE
from .coordinator import HelixCoordinator

_LOGGER = logging.getLogger(__name__)

INTENT_GET_VPD: str = "HelixCultivateGetVpd"
INTENT_HARVEST_ESTIMATE: str = "HelixCultivateHarvestEstimate"
INTENT_GET_STAGE: str = "HelixCultivateGetStage"


def _first_coordinator(hass: HomeAssistant) -> Optional[HelixCoordinator]:
    """Return the coordinator for the (single) Helix Cultivate config entry."""
    domain_data: dict[str, Any] = hass.data.get(DOMAIN, {})
    for value in domain_data.values():
        if isinstance(value, HelixCoordinator):
            return value
    return None


class _HelixIntentHandler(intent.IntentHandler):
    """Base class sharing the "integration not set up" fallback response."""

    def _not_configured_response(
        self, intent_obj: intent.Intent
    ) -> intent.IntentResponse:
        response = intent_obj.create_response()
        response.async_set_speech("Helix Cultivate isn't set up yet.")
        return response


class GetVpdIntentHandler(_HelixIntentHandler):
    """Handle "What's my VPD right now"."""

    intent_type = INTENT_GET_VPD
    description = "Reports the current leaf VPD reading and whether it's in range"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        coordinator = _first_coordinator(intent_obj.hass)
        if coordinator is None:
            return self._not_configured_response(intent_obj)

        leaf_vpd = (coordinator.data or {}).get(NS_CLIMATE, {}).get("leaf_vpd_kpa")
        response = intent_obj.create_response()
        if leaf_vpd is None:
            response.async_set_speech("I don't have a current VPD reading yet.")
            return response

        vmin, vmax = coordinator.vpd_target_min, coordinator.vpd_target_max
        if vmin <= leaf_vpd <= vmax:
            speech = f"Your VPD is {leaf_vpd:.2f} kilopascals, right in your target range."
        elif leaf_vpd < vmin:
            speech = (
                f"Your VPD is {leaf_vpd:.2f} kilopascals, below your target range of "
                f"{vmin:.2f} to {vmax:.2f}."
            )
        else:
            speech = (
                f"Your VPD is {leaf_vpd:.2f} kilopascals, above your target range of "
                f"{vmin:.2f} to {vmax:.2f}."
            )
        response.async_set_speech(speech)
        return response


class HarvestEstimateIntentHandler(_HelixIntentHandler):
    """Handle "How many days until harvest"."""

    intent_type = INTENT_HARVEST_ESTIMATE
    description = "Estimates days remaining until harvest based on the current recipe"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        coordinator = _first_coordinator(intent_obj.hass)
        response = intent_obj.create_response()
        if coordinator is None:
            return self._not_configured_response(intent_obj)

        stage_mgr = coordinator.stage_manager
        if stage_mgr.cycle_complete or stage_mgr.current_stage == STAGE_DRYING:
            response.async_set_speech(
                "Your plant has already reached the drying stage — harvest is done."
            )
            return response

        remaining_current = max(0, stage_mgr.stage_duration - stage_mgr.elapsed_days)
        planned = stage_mgr.planned_stage_durations()
        idx = STAGE_SEQUENCE.index(stage_mgr.current_stage)
        remaining_future = sum(
            planned.get(stage, 0)
            for stage in STAGE_SEQUENCE[idx + 1 :]
            if stage != STAGE_DRYING
        )
        days_until_harvest = remaining_current + remaining_future

        response.async_set_speech(
            f"About {days_until_harvest} days until harvest, based on your current recipe."
        )
        return response


class GetStageIntentHandler(_HelixIntentHandler):
    """Handle "What stage is my grow in"."""

    intent_type = INTENT_GET_STAGE
    description = "Reports the current grow stage and day count"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        coordinator = _first_coordinator(intent_obj.hass)
        response = intent_obj.create_response()
        if coordinator is None:
            return self._not_configured_response(intent_obj)

        stage_mgr = coordinator.stage_manager
        stage_label = STAGE_LABELS.get(stage_mgr.current_stage, stage_mgr.current_stage)
        response.async_set_speech(
            f"Your grow is in the {stage_label} stage, day {stage_mgr.elapsed_days} "
            f"of {stage_mgr.stage_duration}."
        )
        return response


def async_register_intents(hass: HomeAssistant) -> None:
    """Register Helix Cultivate's Voice Assist intents (idempotent across reloads)."""
    if hass.data.get(DOMAIN, {}).get("_intents_registered"):
        return
    intent.async_register(hass, GetVpdIntentHandler())
    intent.async_register(hass, HarvestEstimateIntentHandler())
    intent.async_register(hass, GetStageIntentHandler())
    hass.data.setdefault(DOMAIN, {})["_intents_registered"] = True
    _LOGGER.info("Helix Cultivate: Voice Assist intents registered")
