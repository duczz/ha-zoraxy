"""Fixtures for the Zoraxy integration tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.zoraxy.const import DOMAIN

pytest_plugins = "pytest_homeassistant_custom_component"

MOCK_HOST = "zoraxy.local"
MOCK_PORT = 8000
MOCK_BASE_URL = f"http://{MOCK_HOST}:{MOCK_PORT}"
MOCK_NODE_UUID = "test-node-uuid"

MOCK_USER_INPUT = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
    CONF_SSL: False,
    CONF_VERIFY_SSL: True,
}

LOGIN_HTML = (
    "<html><head>"
    '<meta name="zoraxy.csrf.Token" content="test-csrf-token">'
    "</head></html>"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading this custom integration in every test."""


def mock_zoraxy_endpoints(
    aioclient_mock: AiohttpClientMocker,
    *,
    base_url: str = MOCK_BASE_URL,
    node_uuid: str = MOCK_NODE_UUID,
    login_status: int = 200,
    login_payload: object = "OK",
) -> None:
    """Register the standard set of Zoraxy API endpoint mocks.

    Covers the calls made during a successful config-entry setup (login +
    one coordinator refresh cycle). Tests needing different behavior for a
    specific endpoint register it again afterwards (first match wins, so
    later per-test overrides must be registered before calling this, or the
    endpoint must be re-registered with a fresh mocker).
    """
    aioclient_mock.get(f"{base_url}/login.html", text=LOGIN_HTML)
    aioclient_mock.post(
        f"{base_url}/api/auth/login", status=login_status, json=login_payload
    )
    aioclient_mock.get(
        f"{base_url}/api/info/x",
        json={
            "Version": "3.3.3",
            "NodeUUID": node_uuid,
            "Development": False,
            "BootTime": 1700000000,
        },
    )
    aioclient_mock.get(
        f"{base_url}/api/proxy/status",
        json={
            "Running": True,
            "Option": {
                "Port": 443,
                "UseTls": True,
                "ListenOnPort80": True,
                "ForceHttpsRedirect": True,
            },
        },
    )
    aioclient_mock.get(f"{base_url}/api/proxy/list", json=[])
    aioclient_mock.get(f"{base_url}/api/utm/list", json={})
    aioclient_mock.get(
        f"{base_url}/api/stats/summary",
        json={"TotalRequest": 0, "ValidRequest": 0, "ErrorRequest": 0},
    )
    aioclient_mock.get(f"{base_url}/api/cert/list", json=[])
    aioclient_mock.get(f"{base_url}/api/access/list", json=[])
    aioclient_mock.get(f"{base_url}/api/quickban/list", json=[])
    aioclient_mock.get(f"{base_url}/api/webserv/status", json={})
    aioclient_mock.get(f"{base_url}/api/streamprox/config/list", json=[])
    aioclient_mock.get(
        f"{base_url}/api/stats/system",
        json={
            "CPUUsage": 12.5,
            "UsedRAM": "512 MB",
            "TotalRAM": "2 GB",
            "RAMUsage": 25.6,
            "DiskUsed": 12345678,
            "DiskTotal": 987654321,
            "DiskUsage": 1.25,
            "DiskPath": "/",
            "HostOS": "linux",
            "HostArch": "amd64",
            "HostName": "zoraxy-host",
            "Ready": True,
        },
    )
    aioclient_mock.get(f"{base_url}/api/acme/autoRenew/enable", json=False)
    aioclient_mock.get(f"{base_url}/api/acme/listExpiredDomains", json={"domain": []})


@pytest.fixture
def mock_zoraxy(
    aioclient_mock: AiohttpClientMocker,
) -> Generator[AiohttpClientMocker]:
    """Register the default Zoraxy endpoint mocks for a successful setup."""
    mock_zoraxy_endpoints(aioclient_mock)
    yield aioclient_mock


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a config entry matching MOCK_USER_INPUT, not yet added to hass."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Zoraxy ({MOCK_HOST})",
        data=MOCK_USER_INPUT,
        unique_id=MOCK_NODE_UUID,
    )
