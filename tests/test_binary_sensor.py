"""Tests for the Zoraxy binary_sensor platform."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import MOCK_BASE_URL, MOCK_NODE_UUID, mock_zoraxy_endpoints


async def test_running_binary_sensor_reflects_proxy_status(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The running sensor mirrors the reverse-proxy server's Running flag."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/status",
        json={"Running": False, "Option": {}},
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", "zoraxy", f"{MOCK_NODE_UUID}_running"
    )
    assert hass.states.get(entity_id).state == STATE_OFF


async def test_cert_expiring_soon_binary_sensor(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A certificate inside the warning window turns the sensor on."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/cert/list",
        json=[
            {
                "Domain": "example.com",
                "Filename": "example.com.pem",
                "ExpireDate": "2026-09-20 00:00:00",
                "RemainingDays": 5,
            }
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor",
        "zoraxy",
        f"{MOCK_NODE_UUID}_cert_example.com.pem_cert_expiring_soon",
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON


async def test_host_online_binary_sensor_unavailable_without_uptime_target(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A host without uptime-monitor data gets no online sensor at all.

    Per coordinator.py's uptime_targets_for_host, the sensor is only created
    when the uptime monitor actually reports the host.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "no-monitor.example.com"}],
    )
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/utm/list", json={})
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor",
        "zoraxy",
        f"{MOCK_NODE_UUID}_host_no-monitor.example.com_online",
    )
    assert entity_id is None


async def test_host_online_binary_sensor_with_uptime_target(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A monitored, reachable host reports the online sensor as on."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "monitored.example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/utm/list",
        json={
            "monitored.example.com": [
                {"Online": True, "StatusCode": 200, "Latency": 12}
            ]
        },
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor",
        "zoraxy",
        f"{MOCK_NODE_UUID}_host_monitored.example.com_online",
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_ON
