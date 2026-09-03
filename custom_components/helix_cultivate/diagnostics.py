"""Helix Cultivate — Config entry diagnostics.

Home Assistant automatically discovers `async_get_config_entry_diagnostics`
from this module when the user requests diagnostics for a config entry via
Settings > Devices & Services > Helix Cultivate > ⋮ > Download Diagnostics.
No explicit platform registration is required.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HelixCoordinator

TO_REDACT: set[str] = {
    "harvest_value_per_oz",
    "electricity_rate",
    "notify_target",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics data for a Helix Cultivate config entry."""
    coord: HelixCoordinator = hass.data[DOMAIN][entry.entry_id]
    stage_manager = coord.stage_manager

    return {
        "config_entry_data": async_redact_data(dict(entry.data), TO_REDACT),
        "config_entry_options": async_redact_data(dict(entry.options), TO_REDACT),
        "coordinator_data": async_redact_data(coord.data or {}, TO_REDACT),
        "stage_manager": {
            "current_stage": stage_manager.current_stage,
            "cycle_complete": stage_manager.cycle_complete,
            "elapsed_days": stage_manager.elapsed_days,
            "stage_duration": stage_manager.stage_duration,
            "smooth_glides_active": stage_manager.smooth_glides_active,
        },
        "energy": {
            "cycle_kwh": coord.cycle_kwh,
        },
        "appliance_unavail_since": {
            k: v.isoformat() if v else None
            for k, v in coord._appliance_unavail_since.items()
        },
        "vpd_target": {
            "target": coord.vpd_target,
            "min": coord.vpd_target_min,
            "max": coord.vpd_target_max,
        },
    }
