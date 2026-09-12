"""Tests for Part 2: frontend cache-busting on the panel and glance card JS
URLs, tied to the actual manifest.json release version (not
CONFIG_VERSION/CONFIG_MINOR_VERSION, which only bump on a config-entry
schema migration — far less often than every release).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.helix_cultivate as helix_init


@pytest.fixture
def fake_hass():
    hass = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    hass.config.path = MagicMock(return_value="/config/custom_components/helix_cultivate/www")
    return hass


@pytest.mark.asyncio
async def test_panel_and_glance_urls_include_manifest_version(fake_hass, monkeypatch):
    fake_integration = MagicMock()
    fake_integration.version = "1.2.8"
    monkeypatch.setattr(
        helix_init, "async_get_integration", AsyncMock(return_value=fake_integration)
    )

    captured_panel = {}
    captured_glance = {}
    monkeypatch.setattr(
        helix_init, "async_register_built_in_panel",
        lambda hass, **kwargs: captured_panel.update(kwargs),
    )
    monkeypatch.setattr(
        helix_init, "add_extra_js_url",
        lambda hass, url: captured_glance.update(url=url),
    )

    await helix_init._async_register_panel(fake_hass)

    panel_module_url = captured_panel["config"]["_panel_custom"]["module_url"]
    assert panel_module_url == "/helix_cultivate_www/helix-panel.js?v=1.2.8"
    assert captured_glance["url"] == "/helix_cultivate_www/helix-glance-card.js?v=1.2.8"


@pytest.mark.asyncio
async def test_cache_bust_updates_across_versions_with_no_config_migration(fake_hass, monkeypatch):
    """The exact bug this fixes: two releases can share the same
    CONFIG_VERSION/CONFIG_MINOR_VERSION (no schema migration needed) while
    still being genuinely different manifest.json releases — the
    cache-busting value must still change between them."""
    for version in ("1.2.6", "1.2.7"):
        fake_integration = MagicMock()
        fake_integration.version = version
        monkeypatch.setattr(
            helix_init, "async_get_integration", AsyncMock(return_value=fake_integration)
        )
        captured = {}
        monkeypatch.setattr(
            helix_init, "async_register_built_in_panel",
            lambda hass, **kwargs: captured.update(kwargs),
        )
        monkeypatch.setattr(helix_init, "add_extra_js_url", lambda hass, url: None)

        await helix_init._async_register_panel(fake_hass)

        module_url = captured["config"]["_panel_custom"]["module_url"]
        assert module_url == f"/helix_cultivate_www/helix-panel.js?v={version}"


@pytest.mark.asyncio
async def test_falls_back_to_config_schema_version_if_integration_lookup_fails(fake_hass, monkeypatch):
    monkeypatch.setattr(
        helix_init, "async_get_integration", AsyncMock(side_effect=Exception("not found"))
    )
    captured = {}
    monkeypatch.setattr(
        helix_init, "async_register_built_in_panel",
        lambda hass, **kwargs: captured.update(kwargs),
    )
    monkeypatch.setattr(helix_init, "add_extra_js_url", lambda hass, url: None)

    await helix_init._async_register_panel(fake_hass)

    module_url = captured["config"]["_panel_custom"]["module_url"]
    assert module_url.startswith("/helix_cultivate_www/helix-panel.js?v=")
    assert "None" not in module_url
