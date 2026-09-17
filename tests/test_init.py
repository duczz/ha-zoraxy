"""Tests for the Zoraxy integration setup, unload and device removal."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.zoraxy import async_remove_config_entry_device
from custom_components.zoraxy.const import DOMAIN

from .conftest import MOCK_BASE_URL, MOCK_NODE_UUID, mock_zoraxy_endpoints


async def test_setup_and_unload_entry(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The entry sets up successfully and unloads cleanly."""
    mock_config_entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_entry_auth_failure_triggers_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A login failure during setup starts a reauth flow instead of a hard failure."""
    mock_config_entry.add_to_hass(hass)
    mock_zoraxy_endpoints(aioclient_mock, login_status=401)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


def _device_entry(*identifiers: str) -> SimpleNamespace:
    """Build a minimal stand-in for a DeviceEntry with the given identifiers."""
    return SimpleNamespace(
        identifiers={(DOMAIN, identifier) for identifier in identifiers}
    )


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Active host/stream-proxy devices are protected; orphaned ones can be removed."""
    mock_config_entry.add_to_hass(hass)
    # Registered before mock_zoraxy_endpoints(): first match wins, so these
    # overrides must be in place before the bare defaults are added below.
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "active-host.example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[{"UUID": "active-stream-uuid", "Name": "Active stream rule"}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    server_id = mock_config_entry.unique_id or mock_config_entry.entry_id
    assert server_id == MOCK_NODE_UUID

    # The instance device itself is never removable this way while loaded.
    assert not await async_remove_config_entry_device(
        hass, mock_config_entry, _device_entry(server_id)
    )

    # An active proxy-host device is protected.
    assert not await async_remove_config_entry_device(
        hass,
        mock_config_entry,
        _device_entry(f"{server_id}_host_active-host.example.com"),
    )
    # An orphaned proxy-host device (rule no longer exists) can be removed.
    assert await async_remove_config_entry_device(
        hass,
        mock_config_entry,
        _device_entry(f"{server_id}_host_gone-host.example.com"),
    )

    # An active stream-proxy device is protected (regression test for the
    # audit fix — this was missing entirely before, see gotchas.md).
    assert not await async_remove_config_entry_device(
        hass,
        mock_config_entry,
        _device_entry(f"{server_id}_streamproxy_active-stream-uuid"),
    )
    # An orphaned stream-proxy device can be removed.
    assert await async_remove_config_entry_device(
        hass,
        mock_config_entry,
        _device_entry(f"{server_id}_streamproxy_gone-uuid"),
    )


async def test_stale_devices_removed_automatically(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Host/stream-proxy devices are removed automatically once they vanish
    from Zoraxy, without requiring a manual device-page deletion.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[{"UUID": "stream-1", "Name": "TCP forward"}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    server_id = mock_config_entry.unique_id or mock_config_entry.entry_id
    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{server_id}_host_example.com"), mock_config_entry.entry_id
        )
        is not None
    )
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{server_id}_streamproxy_stream-1"), mock_config_entry.entry_id
        )
        is not None
    )

    # Both objects disappear from Zoraxy; a refresh should remove their devices.
    aioclient_mock.clear_requests()
    mock_zoraxy_endpoints(aioclient_mock)

    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{server_id}_host_example.com"), mock_config_entry.entry_id
        )
        is None
    )
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{server_id}_streamproxy_stream-1"), mock_config_entry.entry_id
        )
        is None
    )
    # The instance device itself is untouched.
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, server_id), mock_config_entry.entry_id
        )
        is not None
    )


async def test_ban_ip_service_adds_to_blacklist(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The ban_ip service posts the IP to Zoraxy and refreshes the coordinator."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_zoraxy.post(f"{MOCK_BASE_URL}/api/blacklist/ip/add", json="OK")
    # A second, empty access-control refresh is enough to prove the service
    # triggered a coordinator refresh after the write.
    mock_zoraxy.get(f"{MOCK_BASE_URL}/api/access/list", json=[])

    await hass.services.async_call(
        DOMAIN,
        "ban_ip",
        {
            "config_entry_id": mock_config_entry.entry_id,
            "ip_address": "203.0.113.42",
            "comment": "Repeated login failures",
        },
        blocking=True,
    )

    add_calls = [
        call for call in mock_zoraxy.mock_calls if "blacklist/ip/add" in str(call[1])
    ]
    assert len(add_calls) == 1
    assert add_calls[0][2] == {
        "id": "default",
        "ip": "203.0.113.42",
        "comment": "Repeated login failures",
    }


async def test_unban_ip_service_removes_from_blacklist(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The unban_ip service posts the removal to Zoraxy."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_zoraxy.post(f"{MOCK_BASE_URL}/api/blacklist/ip/remove", json="OK")

    await hass.services.async_call(
        DOMAIN,
        "unban_ip",
        {
            "config_entry_id": mock_config_entry.entry_id,
            "ip_address": "203.0.113.42",
        },
        blocking=True,
    )

    remove_calls = [
        call
        for call in mock_zoraxy.mock_calls
        if "blacklist/ip/remove" in str(call[1])
    ]
    assert len(remove_calls) == 1
    assert remove_calls[0][2] == {"id": "default", "ip": "203.0.113.42"}


async def test_ban_ip_service_surfaces_zoraxy_error(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A Zoraxy-side rejection raises HomeAssistantError instead of failing silently."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_zoraxy.post(
        f"{MOCK_BASE_URL}/api/blacklist/ip/add",
        json={"error": "invalid ip address"},
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "ban_ip",
            {
                "config_entry_id": mock_config_entry.entry_id,
                "ip_address": "not-an-ip",
            },
            blocking=True,
        )


async def test_unban_ip_service_surfaces_zoraxy_error(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A Zoraxy-side rejection on unban raises HomeAssistantError too."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    mock_zoraxy.post(
        f"{MOCK_BASE_URL}/api/blacklist/ip/remove",
        json={"error": "ip not found in blacklist"},
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN,
            "unban_ip",
            {
                "config_entry_id": mock_config_entry.entry_id,
                "ip_address": "203.0.113.42",
            },
            blocking=True,
        )


async def test_ban_ip_service_rejects_unknown_config_entry(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unknown config_entry_id is a validation error, not a crash."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "ban_ip",
            {"config_entry_id": "does-not-exist", "ip_address": "203.0.113.42"},
            blocking=True,
        )


async def test_ban_ip_service_rejects_unloaded_config_entry(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A config entry that exists but isn't loaded is rejected, not crashed into."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "ban_ip",
            {
                "config_entry_id": mock_config_entry.entry_id,
                "ip_address": "203.0.113.42",
            },
            blocking=True,
        )
