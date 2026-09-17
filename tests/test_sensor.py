"""Tests for the Zoraxy sensor platform, focused on the audit-fixed behavior.

Access-control and static-web-server sensors must become unavailable when
their module fails to report data (Finding 2 of the 2026-09-15 audit) —
before the fix they only showed "unknown" while staying available.
"""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import MOCK_BASE_URL, MOCK_NODE_UUID, mock_zoraxy_endpoints


async def _entity_id(hass: HomeAssistant, domain: str, key: str) -> str:
    """Look up an entity_id by its known unique_id suffix."""
    registry = er.async_get(hass)
    unique_id = f"{MOCK_NODE_UUID}_{key}"
    entity_id = registry.async_get_entity_id(domain, "zoraxy", unique_id)
    assert entity_id is not None, f"no {domain} entity registered for key {key}"
    return entity_id


async def _enable_disabled_by_default_entities(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry, *entity_ids: str
) -> None:
    """Enable disabled-by-default entities and reload so they get a state.

    Several of the newer sensors (access-control, static-web-server) are
    diagnostic and disabled by default, so they never reach hass.states
    until explicitly enabled and reloaded — same as a real user flipping
    them on via Settings -> Entities.
    """
    registry = er.async_get(hass)
    for entity_id in entity_ids:
        registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()


async def test_access_control_sensor_available_when_reported(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The blacklisted-IPs sensor reports a value while access control works."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list",
        json=[{"ID": "default", "BlackListIP": {"1.2.3.4": True}}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "blacklisted_ips")
    await _enable_disabled_by_default_entities(hass, mock_config_entry, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == "1"


async def test_country_sensors_expose_the_actual_country_codes(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Blacklisted/whitelisted-country sensors list the codes, not just a count."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list",
        json=[
            {
                "ID": "default",
                "BlackListContryCode": {"RU": True, "CN": True},
                "WhiteListCountryCode": {"DE": True, "AT": True},
            }
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    blacklisted_id = await _entity_id(hass, "sensor", "blacklisted_countries")
    whitelisted_id = await _entity_id(hass, "sensor", "whitelisted_countries")
    await _enable_disabled_by_default_entities(
        hass, mock_config_entry, blacklisted_id, whitelisted_id
    )

    blacklisted_state = hass.states.get(blacklisted_id)
    assert blacklisted_state.state == "2"
    assert blacklisted_state.attributes["country_codes"] == ["CN", "RU"]

    whitelisted_state = hass.states.get(whitelisted_id)
    assert whitelisted_state.state == "2"
    assert whitelisted_state.attributes["country_codes"] == ["AT", "DE"]


async def test_access_control_sensor_unavailable_when_module_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The access-control sensors become unavailable, not just 'unknown'.

    Regression test for the audit fix: previously ZoraxyServerSensor had no
    available override, so these stayed "available" with state "unknown"
    instead — contradicting the behavior documented in the README.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    keys = (
        "blacklisted_ips",
        "blacklisted_countries",
        "whitelisted_ips",
        "whitelisted_countries",
    )
    entity_ids = [await _entity_id(hass, "sensor", key) for key in keys]
    await _enable_disabled_by_default_entities(hass, mock_config_entry, *entity_ids)

    for key, entity_id in zip(keys, entity_ids, strict=True):
        state = hass.states.get(entity_id)
        assert state.state == STATE_UNAVAILABLE, f"{key} should be unavailable"


async def test_webserver_port_sensor_unavailable_when_module_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The static-web-server port sensor becomes unavailable when it fails to report."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/webserv/status", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "static_web_server_port")
    await _enable_disabled_by_default_entities(hass, mock_config_entry, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == STATE_UNAVAILABLE


async def test_proxy_server_port_sensor(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The reverse-proxy server port sensor reports the configured port.

    Regression test for audit Finding 8: ZoraxyStatus.port was parsed but
    never surfaced anywhere except diagnostics.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/status",
        json={"Running": True, "Option": {"Port": 443}},
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "proxy_server_port")
    await _enable_disabled_by_default_entities(hass, mock_config_entry, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == "443"


async def test_webserver_port_sensor_reports_data_when_available(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The static-web-server port sensor reports the port and attributes."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/webserv/status",
        json={
            "Running": True,
            "ListeningPort": 8080,
            "EnableDirectoryListing": False,
            "WebRoot": "/www",
            "DisableListenToAllInterface": False,
        },
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "static_web_server_port")
    await _enable_disabled_by_default_entities(hass, mock_config_entry, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == "8080"
    assert state.attributes["web_root"] == "/www"
    assert state.attributes["listen_all_interfaces"] is True


async def test_quickban_sensor_reports_top_ips(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The quick-ban sensor counts entries and ranks the top ones by count."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/quickban/list",
        json=[
            {"IpAddr": "1.1.1.1", "Count": 5, "CountryCode": "US"},
            {"IpAddr": "2.2.2.2", "Count": 50, "CountryCode": "DE"},
        ],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "quickban_entries")
    await _enable_disabled_by_default_entities(hass, mock_config_entry, entity_id)

    state = hass.states.get(entity_id)
    assert state.state == "2"
    assert state.attributes["top_ips"][0]["ip"] == "2.2.2.2"
    assert state.attributes["top_ips"][0]["count"] == 50


async def test_host_latency_sensor_none_when_all_upstreams_offline(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The latency sensor reports unknown when no upstream is online."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/utm/list",
        json={"example.com": [{"Online": False, "Latency": 999}]},
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "zoraxy", f"{MOCK_NODE_UUID}_host_example.com_latency"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == STATE_UNKNOWN


async def test_sensors_not_backed_by_optional_module_stay_unaffected(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failing access-control module doesn't affect unrelated sensors."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/access/list", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "proxy_hosts")
    state = hass.states.get(entity_id)
    assert state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)


async def test_system_resource_sensors_report_values(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The host CPU/RAM/disk sensors report Zoraxy's system-resource data."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cpu_id = await _entity_id(hass, "sensor", "cpu_usage")
    ram_id = await _entity_id(hass, "sensor", "ram_usage")
    disk_id = await _entity_id(hass, "sensor", "disk_usage")
    await _enable_disabled_by_default_entities(
        hass, mock_config_entry, cpu_id, ram_id, disk_id
    )

    cpu_state = hass.states.get(cpu_id)
    assert cpu_state.state == "12.5"
    assert cpu_state.attributes["host_os"] == "linux"
    assert cpu_state.attributes["host_arch"] == "amd64"
    assert cpu_state.attributes["host_name"] == "zoraxy-host"

    ram_state = hass.states.get(ram_id)
    assert ram_state.state == "25.6"
    assert ram_state.attributes["used"] == "512 MB"
    assert ram_state.attributes["total"] == "2 GB"

    disk_state = hass.states.get(disk_id)
    assert disk_state.state == "1.25"
    assert disk_state.attributes["used_bytes"] == 12345678
    assert disk_state.attributes["total_bytes"] == 987654321
    assert disk_state.attributes["path"] == "/"


async def test_system_resource_sensors_unknown_before_first_sample(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The sensors report 'unknown' (not 0) before Zoraxy's first background sample."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/stats/system",
        json={"CPUUsage": 0, "RAMUsage": 0, "DiskUsage": 0, "Ready": False},
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_ids = [
        await _entity_id(hass, "sensor", key)
        for key in ("cpu_usage", "ram_usage", "disk_usage")
    ]
    await _enable_disabled_by_default_entities(hass, mock_config_entry, *entity_ids)

    for entity_id in entity_ids:
        assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_system_resource_sensors_unavailable_when_module_fails(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The sensors become unavailable if Zoraxy fails to report system resources."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/stats/system", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_ids = [
        await _entity_id(hass, "sensor", key)
        for key in ("cpu_usage", "ram_usage", "disk_usage")
    ]
    await _enable_disabled_by_default_entities(hass, mock_config_entry, *entity_ids)

    for entity_id in entity_ids:
        assert hass.states.get(entity_id).state == STATE_UNAVAILABLE


async def test_expired_domains_sensor_reports_affected_domains(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The expired-domains sensor counts and lists domains Zoraxy flags as expired."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/acme/listExpiredDomains",
        json={"domain": ["example.com", "other.example.com"]},
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = await _entity_id(hass, "sensor", "expired_domains")
    state = hass.states.get(entity_id)
    assert state.state == "2"
    assert state.attributes["domains"] == ["example.com", "other.example.com"]


async def test_host_requests_sensor_reports_value(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The per-host requests-today sensor reads from the full stats summary."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/stats/summary",
        json={
            "TotalRequest": 5,
            "ValidRequest": 5,
            "ErrorRequest": 0,
            "Downstreams": {"example.com": 5},
        },
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "zoraxy", f"{MOCK_NODE_UUID}_host_example.com_host_requests_today"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "5"


async def test_host_requests_sensor_unavailable_when_host_not_in_breakdown(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A host absent from Zoraxy's per-host breakdown reports unavailable."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/list",
        json=[{"RootOrMatchingDomain": "example.com"}],
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", "zoraxy", f"{MOCK_NODE_UUID}_host_example.com_host_requests_today"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == STATE_UNAVAILABLE
