"""Helix Cultivate — Switch platform (5 switches)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    SWITCH_BREEZE_LOWER,
    SWITCH_BREEZE_MID,
    SWITCH_BREEZE_UPPER,
    SWITCH_DLI_EXTENSION,
    SWITCH_SMOOTH_GLIDES,
)
from .coordinator import HelixCoordinator


@dataclass(frozen=True)
class HelixSwitchDescription(SwitchEntityDescription):
    """Extended switch description."""

    coordinator_attr: str = ""


SWITCH_DESCRIPTIONS: tuple[HelixSwitchDescription, ...] = (
    HelixSwitchDescription(
        key=SWITCH_SMOOTH_GLIDES,
        name="Smooth Glides",
        icon="mdi:chart-line",
        coordinator_attr="smooth_glides_enabled",
    ),
    HelixSwitchDescription(
        key=SWITCH_BREEZE_UPPER,
        name="Upper Canopy Breeze Mode",
        icon="mdi:weather-windy",
        coordinator_attr="breeze_upper_enabled",
    ),
    HelixSwitchDescription(
        key=SWITCH_BREEZE_MID,
        name="Mid Canopy Breeze Mode",
        icon="mdi:weather-windy",
        coordinator_attr="breeze_mid_enabled",
    ),
    HelixSwitchDescription(
        key=SWITCH_BREEZE_LOWER,
        name="Lower Canopy Breeze Mode",
        icon="mdi:weather-windy",
        coordinator_attr="breeze_lower_enabled",
    ),
    HelixSwitchDescription(
        key=SWITCH_DLI_EXTENSION,
        name="DLI Photoperiod Extension",
        icon="mdi:weather-sunset-up",
        coordinator_attr="dli_extension_enabled",
    ),
)

# Map breeze switch keys → fan tier
_BREEZE_TIER_MAP: dict[str, str] = {
    SWITCH_BREEZE_UPPER: FAN_TIER_UPPER,
    SWITCH_BREEZE_MID: FAN_TIER_MID,
    SWITCH_BREEZE_LOWER: FAN_TIER_LOWER,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Helix Cultivate switches from a config entry."""
    coordinator: HelixCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HelixSwitch(coordinator, description) for description in SWITCH_DESCRIPTIONS
    )


class HelixSwitch(CoordinatorEntity[HelixCoordinator], SwitchEntity):
    """A single Helix Cultivate switch entity."""

    entity_description: HelixSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HelixCoordinator,
        description: HelixSwitchDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator._entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator._entry.entry_id)},
            "name": "Helix Cultivate",
            "manufacturer": "Helix Cultivate",
            "model": "Environmental Controller",
            "sw_version": "1.0.0",
        }

    @property
    def is_on(self) -> bool:
        """Return the current switch state from the coordinator attribute."""
        attr = self.entity_description.coordinator_attr
        return bool(getattr(self.coordinator, attr, False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch — update coordinator attribute."""
        attr = self.entity_description.coordinator_attr
        setattr(self.coordinator, attr, True)

        # For breeze switches: start the breeze task
        tier = _BREEZE_TIER_MAP.get(self.entity_description.key)
        if tier is not None:
            self.coordinator._start_breeze_task(tier)

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch — update coordinator attribute."""
        attr = self.entity_description.coordinator_attr
        setattr(self.coordinator, attr, False)

        # For breeze switches: stop the breeze task
        tier = _BREEZE_TIER_MAP.get(self.entity_description.key)
        if tier is not None:
            self.coordinator._stop_breeze_task(tier)

        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
