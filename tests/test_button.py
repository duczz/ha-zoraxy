"""Tests for the Zoraxy button platform (certificate renewal)."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .conftest import MOCK_BASE_URL, MOCK_NODE_UUID, mock_zoraxy_endpoints

CERT_PAYLOAD = [
    {
        "Domain": "example.com",
        "Filename": "example.com.pem",
        "ExpireDate": "2026-12-01 00:00:00",
        "RemainingDays": 60,
    }
]


async def test_renew_cert_button_success(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Pressing the button requests renewal via ACME with the configured e-mail/CA."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/cert/list", json=CERT_PAYLOAD)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/acme/autoRenew/email", json="admin@example.com"
    )
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/acme/autoRenew/ca", json="Let's Encrypt")
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/acme/obtainCert", json="OK")
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", "zoraxy", f"{MOCK_NODE_UUID}_cert_example.com.pem_renew_cert"
    )
    assert entity_id is not None

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()

    obtain_calls = [
        call for call in aioclient_mock.mock_calls if "acme/obtainCert" in str(call[1])
    ]
    assert len(obtain_calls) == 1


async def test_renew_cert_button_fails_without_acme_email(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A missing ACME e-mail configuration surfaces as a HomeAssistantError."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/cert/list", json=CERT_PAYLOAD)
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/acme/autoRenew/email", json="")
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "button", "zoraxy", f"{MOCK_NODE_UUID}_cert_example.com.pem_renew_cert"
    )

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )
