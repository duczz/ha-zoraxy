"""Tests for the Zoraxy diagnostics platform."""

from __future__ import annotations

from homeassistant.components.diagnostics.const import REDACTED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.zoraxy.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_includes_all_modules(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Diagnostics include access-control, static-web-server, quick-ban and
    stream-proxy data.

    Regression test for audit Finding 5: these four fields were added to
    ZoraxyData in commit c220253 but never wired into diagnostics.py.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    for key in (
        "info",
        "status",
        "hosts",
        "uptime",
        "stats",
        "certs",
        "access_rule",
        "quickban",
        "webserver",
        "stream_proxies",
    ):
        assert key in result, f"diagnostics missing '{key}'"

    assert result["entry"]["data"]["host"] == REDACTED
