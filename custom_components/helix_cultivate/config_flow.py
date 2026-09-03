"""Config flow for Helix Cultivate integration.

Rapid 2-step onboarding:
  Step 1 (user)  — Operating mode (Coordinated / Standalone)
  Step 2 (zones) — Zone names with helper text to match HA Area/Room names
                   → async_create_entry immediately; sidebar panel registers
                     via async_setup_entry.

All hardware mapping is deferred to the options flow so onboarding is never
blocked by offline or missing devices.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DRYING_ENABLED,
    CONF_DRYING_ZONE_NAME,
    CONF_ENABLE_CONDITIONING_ROOM,
    CONF_ENABLE_DRYING_ENVIRONMENT,
    CONF_TOPOLOGY,
    CONF_ZONE1_NAME,
    CONF_ZONE2_NAME,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    DEFAULT_DRYING_ZONE_NAME,
    DEFAULT_ZONE1_NAME,
    DEFAULT_ZONE2_NAME,
    DOMAIN,
    TOPOLOGY_COORDINATED,
    TOPOLOGY_OPTIONS,
    TOPOLOGY_STANDALONE,
)
from .options_flow import HelixOptionsFlow

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Selector helpers
# ─────────────────────────────────────────────────────────────────────────────

def _topology_selector() -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {
                    "value": TOPOLOGY_COORDINATED,
                    "label": "Coordinated — Primary Grow Space + Conditioning Room",
                },
                {
                    "value": TOPOLOGY_STANDALONE,
                    "label": "Standalone — Primary Grow Space Only",
                },
            ],
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _text_selector() -> selector.TextSelector:
    return selector.TextSelector(
        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
    )


def _bool_selector() -> selector.BooleanSelector:
    return selector.BooleanSelector()


# ─────────────────────────────────────────────────────────────────────────────
# Step schemas
# ─────────────────────────────────────────────────────────────────────────────

def _step1_schema(user_input: Optional[dict[str, Any]] = None) -> vol.Schema:
    """Step 1 — Operating mode selection."""
    d = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_TOPOLOGY,
                default=d.get(CONF_TOPOLOGY, TOPOLOGY_COORDINATED),
            ): _topology_selector(),
        }
    )


def _step2_schema(
    topology: str,
    user_input: Optional[dict[str, Any]] = None,
) -> vol.Schema:
    """Step 2 — Zone naming.

    Helper text in the UI encourages users to match HA Area/Room names for
    seamless entity grouping. Conditioning Room field shown only in Coordinated mode.
    Drying zone toggle always present.
    """
    d = user_input or {}
    schema_dict: dict[Any, Any] = {
        vol.Optional(
            CONF_ZONE1_NAME,
            default=d.get(CONF_ZONE1_NAME, DEFAULT_ZONE1_NAME),
        ): _text_selector(),
    }
    if topology == TOPOLOGY_COORDINATED:
        schema_dict[
            vol.Optional(
                CONF_ZONE2_NAME,
                default=d.get(CONF_ZONE2_NAME, DEFAULT_ZONE2_NAME),
            )
        ] = _text_selector()

    schema_dict[
        vol.Optional(
            CONF_DRYING_ENABLED,
            default=d.get(CONF_DRYING_ENABLED, False),
        )
    ] = _bool_selector()

    schema_dict[
        vol.Optional(
            CONF_DRYING_ZONE_NAME,
            default=d.get(CONF_DRYING_ZONE_NAME, DEFAULT_DRYING_ZONE_NAME),
        )
    ] = _text_selector()

    return vol.Schema(schema_dict)


# ─────────────────────────────────────────────────────────────────────────────
# Config Flow
# ─────────────────────────────────────────────────────────────────────────────

class HelixCultivateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Helix Cultivate rapid 2-step config flow.

    All device / hardware configuration is handled in the options flow so
    onboarding never stalls on missing or offline devices.
    """

    VERSION = CONFIG_VERSION
    MINOR_VERSION = CONFIG_MINOR_VERSION

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: Operating mode ────────────────────────────────────────────────

    async def async_step_user(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1 — Choose operating mode (Coordinated or Standalone)."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_zones()

        return self.async_show_form(
            step_id="user",
            data_schema=_step1_schema(user_input),
            errors={},
            description_placeholders={},
        )

    # ── Step 2: Zone names ────────────────────────────────────────────────────

    async def async_step_zones(
        self, user_input: Optional[dict[str, Any]] = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2 — Name zones. Tip: match HA Area/Room names for best entity grouping.

        On submit → async_create_entry immediately (sidebar panel registers via
        async_setup_entry). All hardware mapping is handled in the options flow.
        """
        topology: str = self._data.get(CONF_TOPOLOGY, TOPOLOGY_COORDINATED)

        if user_input is not None:
            self._data.update(user_input)

            # ── Derive module enable flags from topology choice ────────────────
            # These flags are the canonical source of truth that drive both the
            # climate engine and the frontend tab visibility. They can be
            # overridden later in the options flow without changing topology.
            topology_choice: str = self._data.get(CONF_TOPOLOGY, TOPOLOGY_COORDINATED)
            self._data.setdefault(
                CONF_ENABLE_CONDITIONING_ROOM,
                topology_choice == TOPOLOGY_COORDINATED,
            )
            # Drying environment flag derives from the explicit drying_enabled toggle
            self._data.setdefault(
                CONF_ENABLE_DRYING_ENVIRONMENT,
                bool(self._data.get(CONF_DRYING_ENABLED, False)),
            )

            return self.async_create_entry(
                title="Helix Cultivate",
                data=self._data,
            )

        return self.async_show_form(
            step_id="zones",
            data_schema=_step2_schema(topology, user_input),
            errors={},
            description_placeholders={
                "tip": (
                    "Tip: Use names that match your Home Assistant Area / Room names "
                    "for seamless entity grouping (e.g. 'Grow Tent', 'Veg Room')."
                ),
            },
        )

    # ── Options flow link ─────────────────────────────────────────────────────

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HelixOptionsFlow:
        """Return the options flow handler for live reconfiguration."""
        return HelixOptionsFlow(config_entry)
