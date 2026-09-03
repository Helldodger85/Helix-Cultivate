"""Helix Cultivate — Select platform (8 select entities)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ALGO_LABELS,
    ALGO_OPTIONS,
    DOMAIN,
    FAN_CONTROL_LABELS,
    FAN_CONTROL_OPTIONS,
    FAN_TIER_LOWER,
    FAN_TIER_MID,
    FAN_TIER_UPPER,
    LIGHT_TYPE_LABELS,
    LIGHT_TYPE_OPTIONS,
    PROG_LABELS,
    PROG_OPTIONS,
    SELECT_CONTROL_ALGORITHM,
    SELECT_GROW_STAGE,
    SELECT_LIGHT_TYPE,
    SELECT_LOWER_FAN_CONTROL,
    SELECT_MID_FAN_CONTROL,
    SELECT_PROGRESSION_MODE,
    SELECT_TOPOLOGY,
    SELECT_UPPER_FAN_CONTROL,
    STAGE_LABELS,
    STAGE_SEQUENCE,
    TOPOLOGY_LABELS,
    TOPOLOGY_OPTIONS,
)
from .coordinator import HelixCoordinator


@dataclass(frozen=True)
class HelixSelectDescription(SelectEntityDescription):
    """Extended select entity description."""

    options_list: list[str] = field(default_factory=list)
    label_map: dict[str, str] = field(default_factory=dict)   # slug → display label
    value_fn: Callable[["HelixCoordinator"], str] = field(default=lambda c: "")
    set_fn: Callable[["HelixCoordinator", str], None] = field(default=lambda c, v: None)


def _persistent_setter(config_key: str) -> Callable[["HelixCoordinator", str], None]:
    """Build a setter that mutates in-memory config AND persists to the config entry."""

    def _set(c: "HelixCoordinator", v: str) -> None:
        c._config[config_key] = v
        c.queue_option_write(config_key, v)

    return _set


def _stage_setter() -> Callable[["HelixCoordinator", str], None]:
    """Setter for the grow-stage select — updates the state machine AND persists the slug."""

    def _set(c: "HelixCoordinator", v: str) -> None:
        c.stage_manager.set_stage(v)
        new_options = {**c._entry.options, "current_stage": v}
        c.hass.config_entries.async_update_entry(c._entry, options=new_options)

    return _set


SELECT_DESCRIPTIONS: tuple[HelixSelectDescription, ...] = (
    # ── Topology ──────────────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_TOPOLOGY,
        name="Topology Mode",
        icon="mdi:home-roof",
        options_list=TOPOLOGY_OPTIONS,
        label_map=TOPOLOGY_LABELS,
        value_fn=lambda c: c._config.get("topology", "coordinated"),
        set_fn=_persistent_setter("topology"),
    ),
    # ── Grow stage ────────────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_GROW_STAGE,
        name="Grow Stage",
        icon="mdi:cannabis",
        options_list=STAGE_SEQUENCE,
        label_map=STAGE_LABELS,
        value_fn=lambda c: c.stage_manager.current_stage,
        set_fn=_stage_setter(),
    ),
    # ── Progression mode ──────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_PROGRESSION_MODE,
        name="Stage Progression Mode",
        icon="mdi:calendar-clock",
        options_list=PROG_OPTIONS,
        label_map=PROG_LABELS,
        value_fn=lambda c: c._config.get("progression_mode", "manual"),
        set_fn=_persistent_setter("progression_mode"),
    ),
    # ── Control algorithm ─────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_CONTROL_ALGORITHM,
        name="Control Algorithm",
        icon="mdi:tune-variant",
        options_list=ALGO_OPTIONS,
        label_map=ALGO_LABELS,
        value_fn=lambda c: c._config.get("control_algorithm", "bang_bang"),
        set_fn=_persistent_setter("control_algorithm"),
    ),
    # ── Fan control modes ─────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_UPPER_FAN_CONTROL,
        name="Upper Canopy Fan Control Mode",
        icon="mdi:fan",
        options_list=FAN_CONTROL_OPTIONS,
        label_map=FAN_CONTROL_LABELS,
        value_fn=lambda c: c._config.get(f"fan_control_mode_{FAN_TIER_UPPER}", c._config.get("fan_control_mode", "continuous")),
        set_fn=_persistent_setter(f"fan_control_mode_{FAN_TIER_UPPER}"),
    ),
    HelixSelectDescription(
        key=SELECT_MID_FAN_CONTROL,
        name="Mid Canopy Fan Control Mode",
        icon="mdi:fan",
        options_list=FAN_CONTROL_OPTIONS,
        label_map=FAN_CONTROL_LABELS,
        value_fn=lambda c: c._config.get(f"fan_control_mode_{FAN_TIER_MID}", c._config.get("fan_control_mode", "continuous")),
        set_fn=_persistent_setter(f"fan_control_mode_{FAN_TIER_MID}"),
    ),
    HelixSelectDescription(
        key=SELECT_LOWER_FAN_CONTROL,
        name="Lower Canopy Fan Control Mode",
        icon="mdi:fan",
        options_list=FAN_CONTROL_OPTIONS,
        label_map=FAN_CONTROL_LABELS,
        value_fn=lambda c: c._config.get(f"fan_control_mode_{FAN_TIER_LOWER}", c._config.get("fan_control_mode", "continuous")),
        set_fn=_persistent_setter(f"fan_control_mode_{FAN_TIER_LOWER}"),
    ),
    # ── Light type ────────────────────────────────────────────────────────────
    HelixSelectDescription(
        key=SELECT_LIGHT_TYPE,
        name="Grow Light Type",
        icon="mdi:lightbulb-cfl",
        options_list=LIGHT_TYPE_OPTIONS,
        label_map=LIGHT_TYPE_LABELS,
        value_fn=lambda c: c._config.get("light_type", "led"),
        set_fn=_persistent_setter("light_type"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Helix Cultivate select entities from a config entry."""
    coordinator: HelixCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        HelixSelect(coordinator, description) for description in SELECT_DESCRIPTIONS
    )


class HelixSelect(CoordinatorEntity[HelixCoordinator], SelectEntity):
    """A single Helix Cultivate select entity."""

    entity_description: HelixSelectDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HelixCoordinator,
        description: HelixSelectDescription,
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
        # HA requires `options` attribute on SelectEntity to contain human-readable labels
        # We expose slug options directly — label_map used for display in panel
        self._attr_options = description.options_list

    @property
    def current_option(self) -> Optional[str]:
        """Return the currently selected option slug."""
        try:
            val = self.entity_description.value_fn(self.coordinator)
            if val in self.entity_description.options_list:
                return val
            return self.entity_description.options_list[0]
        except Exception:  # noqa: BLE001
            return self.entity_description.options_list[0] if self.entity_description.options_list else None

    async def async_select_option(self, option: str) -> None:
        """Handle option selection from HA UI or automations."""
        if option not in self.entity_description.options_list:
            return
        try:
            self.entity_description.set_fn(self.coordinator, option)
        except Exception as exc:  # noqa: BLE001
            pass
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the human-readable label for the current option."""
        label_map = self.entity_description.label_map
        current = self.current_option or ""
        return {
            "label": label_map.get(current, current),
            "available_labels": {slug: label_map.get(slug, slug) for slug in self.entity_description.options_list},
        }

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success
