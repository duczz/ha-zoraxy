"""Tests for the Zoraxy switch platform, focused on the audit-fixed behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import MOCK_BASE_URL, MOCK_NODE_UUID, mock_zoraxy_endpoints

NO_REFRESH = patch(
    "custom_components.zoraxy.coordinator.ZoraxyDataUpdateCoordinator.async_request_refresh"
)


async def test_proxy_server_switch_disabled_by_default(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The proxy-server switch stays disabled by default (self-lockout safety net).

    Regression test for the decision in gotchas.md #1 / decisions.md: this
    must never flip to enabled-by-default without a deliberate choice.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entry = registry.async_get(
        registry.async_get_entity_id(
            "switch", "zoraxy", f"{MOCK_NODE_UUID}_proxy_server"
        )
    )
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION


async def test_stream_proxy_switch_turn_on_off(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The stream-proxy switch starts/stops the rule via the API."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[
            {
                "UUID": "stream-1",
                "Name": "TCP forward",
                "Running": False,
                "ListeningAddress": ":9000",
                "ProxyTargetAddr": "192.168.1.10:9000",
                "UseTCP": True,
            }
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)
    aioclient_mock.post(f"{MOCK_BASE_URL}/api/streamprox/config/start", json="OK")

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_streamproxy_stream-1_stream_proxy"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "off"

    # The mocked list endpoint is static, so the coordinator refresh that
    # follows the optimistic write would immediately revert it to the old
    # ("off") value. Isolate the optimistic write itself, which is what a
    # user actually sees the instant after the switch is toggled.
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
    await hass.async_block_till_done()

    assert hass.states.get(entity_id).state == "on"
    start_calls = [
        call
        for call in aioclient_mock.mock_calls
        if "streamprox/config/start" in str(call[1])
    ]
    assert len(start_calls) == 1


async def test_stream_proxy_device_has_no_firmware_version(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Stream-proxy devices don't inherit the instance's firmware version.

    Regression test for audit Finding 3: ZoraxyStreamProxyEntity used to
    extend ZoraxyServerEntity and inherit its device_info override that
    always stamps sw_version onto every device using it.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[{"UUID": "stream-1", "Name": "TCP forward", "UseTCP": True}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    instance_device = device_registry.async_get_device_by_identifier(
        ("zoraxy", MOCK_NODE_UUID), mock_config_entry.entry_id
    )
    stream_device = device_registry.async_get_device_by_identifier(
        ("zoraxy", f"{MOCK_NODE_UUID}_streamproxy_stream-1"), mock_config_entry.entry_id
    )

    assert instance_device is not None
    assert instance_device.sw_version == "3.3.3"
    assert stream_device is not None
    assert stream_device.sw_version is None


async def test_host_and_stream_proxy_devices_link_to_the_instance_device(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Host and stream-proxy devices are linked via via_device_id.

    Regression test for the via_device -> via_device_id migration
    (gotchas.md #14): the deprecated `via_device` parameter resolved by
    identifier, `via_device_id` needs the actual registry id, looked up at
    device_info access time in entity.py's `_instance_device_id`.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[{"UUID": "stream-1", "Name": "TCP forward", "UseTCP": True}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    instance_device = device_registry.async_get_device_by_identifier(
        ("zoraxy", MOCK_NODE_UUID), mock_config_entry.entry_id
    )
    host_device = device_registry.async_get_device_by_identifier(
        ("zoraxy", f"{MOCK_NODE_UUID}_host_example.com"), mock_config_entry.entry_id
    )
    stream_device = device_registry.async_get_device_by_identifier(
        ("zoraxy", f"{MOCK_NODE_UUID}_streamproxy_stream-1"), mock_config_entry.entry_id
    )

    assert instance_device is not None
    assert host_device is not None
    assert host_device.via_device_id == instance_device.id
    assert stream_device is not None
    assert stream_device.via_device_id == instance_device.id


async def test_access_control_switch_unavailable_when_module_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The blacklist switch becomes unavailable when access control fails to report."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_blacklist_enabled"
    )
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_proxy_rule_switch_turn_off_and_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The proxy-rule switch toggles a host and surfaces Zoraxy rejections."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[
            {
                "RootOrMatchingDomain": "example.com",
                "DisableUptimeMonitor": True,
            }
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_host_example.com_proxy_rule"
    )
    assert hass.states.get(entity_id).state == "on"
    assert hass.states.get(entity_id).attributes["upstreams"] == []
    assert hass.states.get(entity_id).attributes["uptime_monitor_disabled"] is True

    aioclient_mock.post(f"{MOCK_BASE_URL}/api/proxy/toggle", json="OK")
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "off"

    aioclient_mock.clear_requests()
    mock_zoraxy_endpoints(aioclient_mock)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    aioclient_mock.post(
        f"{MOCK_BASE_URL}/api/proxy/toggle", json={"error": "rule is locked"}
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )


async def test_server_switch_turn_on_and_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A global setting switch applies the change and surfaces rejections."""
    mock_config_entry.add_to_hass(hass)
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_port80"
    )
    assert hass.states.get(entity_id).state == "on"

    aioclient_mock.post(f"{MOCK_BASE_URL}/api/proxy/listenPort80", json="OK")
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "off"

    aioclient_mock.clear_requests()
    mock_zoraxy_endpoints(aioclient_mock)
    aioclient_mock.post(
        f"{MOCK_BASE_URL}/api/proxy/listenPort80",
        json={"error": "port 80 is occupied"},
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )


async def test_optional_switch_turn_on_and_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An optional switch applies the change and surfaces Zoraxy rejections.

    The "feature_unavailable" branch in ZoraxyOptionalSwitch._async_set (root
    is None) is not covered here: HA's service-call layer already filters out
    unavailable entities before dispatch (confirmed by trying it — the call
    is silently skipped with a "referenced entities ... not available"
    warning, never reaching the entity code), so that branch is unreachable
    through normal use and not worth faking around.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list",
        json=[{"ID": "default", "BlacklistEnabled": False}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_blacklist_enabled"
    )
    assert hass.states.get(entity_id).state == "off"

    aioclient_mock.post(f"{MOCK_BASE_URL}/api/blacklist/enable", json="OK")
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "on"

    aioclient_mock.clear_requests()
    mock_zoraxy_endpoints(aioclient_mock)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list",
        json=[{"ID": "default", "BlacklistEnabled": True}],
    )
    aioclient_mock.post(
        f"{MOCK_BASE_URL}/api/blacklist/enable", json={"error": "rule set is locked"}
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )


async def test_stream_proxy_switch_turn_off_and_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The stream-proxy switch stops a rule and surfaces Zoraxy rejections."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[
            {
                "UUID": "stream-1",
                "Name": "TCP forward",
                "Running": True,
                "ProxyProtocolVersion": 2,
            }
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_streamproxy_stream-1_stream_proxy"
    )
    assert hass.states.get(entity_id).state == "on"
    assert hass.states.get(entity_id).attributes["protocols"] == []
    assert hass.states.get(entity_id).attributes["proxy_protocol_version"] == 2

    aioclient_mock.post(f"{MOCK_BASE_URL}/api/streamprox/config/stop", json="OK")
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "off"

    aioclient_mock.clear_requests()
    mock_zoraxy_endpoints(aioclient_mock)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/streamprox/config/list",
        json=[{"UUID": "stream-1", "Name": "TCP forward", "Running": False}],
    )
    aioclient_mock.post(
        f"{MOCK_BASE_URL}/api/streamprox/config/start",
        json={"error": "listener already in use"},
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )


async def test_auto_renew_switch_turn_on_and_off(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The auto-renew switch reflects Zoraxy's ACME auto-renew state."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_auto_renew"
    )
    assert hass.states.get(entity_id).state == "off"

    mock_zoraxy.post(f"{MOCK_BASE_URL}/api/acme/autoRenew/enable", json="OK")
    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "on"

    with NO_REFRESH:
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert hass.states.get(entity_id).state == "off"


async def test_auto_renew_switch_turn_on_error(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Zoraxy rejecting auto-renew (e.g. no ACME e-mail set) surfaces as an error."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_auto_renew"
    )

    mock_zoraxy.post(
        f"{MOCK_BASE_URL}/api/acme/autoRenew/enable",
        json={"error": "Email is not set"},
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )


async def test_auto_renew_switch_unavailable_when_module_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The auto-renew switch is unavailable if Zoraxy fails to report its state."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/acme/autoRenew/enable", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "switch", "zoraxy", f"{MOCK_NODE_UUID}_auto_renew"
    )
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
