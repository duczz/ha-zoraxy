"""Tests for the Zoraxy config flow."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.zoraxy.const import DOMAIN

from .conftest import (
    MOCK_BASE_URL,
    MOCK_NODE_UUID,
    MOCK_USER_INPUT,
    mock_zoraxy_endpoints,
)


async def test_user_flow_success(
    hass: HomeAssistant, mock_zoraxy: AiohttpClientMocker
) -> None:
    """A valid connection creates an entry, keyed by the instance's node UUID."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Zoraxy ({MOCK_USER_INPUT['host']})"
    assert result["data"] == MOCK_USER_INPUT
    assert result["result"].unique_id == MOCK_NODE_UUID


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Wrong credentials show an invalid_auth error and keep the form open."""
    mock_zoraxy_endpoints(aioclient_mock, login_status=401)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A connection error shows a cannot_connect error and keeps the form open."""
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/login.html",
        exc=aiohttp.ClientConnectionError("connection refused"),
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_already_configured(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A second entry for the same Zoraxy instance (same node UUID) aborts."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Successful re-authentication updates the entry and reloads it."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-secret"


async def test_reauth_flow_wrong_instance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Re-authenticating against a different Zoraxy instance aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_zoraxy_endpoints(aioclient_mock, node_uuid="a-different-node-uuid")

    result = await mock_config_entry.start_reauth_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_instance"


async def test_reconfigure_flow_success(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfiguring updates the connection details without a new entry."""
    mock_config_entry.add_to_hass(hass)
    new_host = "new-zoraxy.local"
    mock_zoraxy_endpoints(aioclient_mock, base_url=f"http://{new_host}:8000")

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {**MOCK_USER_INPUT, "host": new_host},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_config_entry.data["host"] == new_host


async def test_options_flow(
    hass: HomeAssistant,
    mock_zoraxy: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The options flow updates the scan interval.

    Exercises ZoraxyOptionsFlow.config_entry, the property that only exists
    automatically on HA >= 2024.12.0 (see hacs.json / gotchas.md #10) — this
    test fails immediately with AttributeError if that regresses.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 60}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_SCAN_INTERVAL] == 60


async def test_user_flow_unknown_error(
    hass: HomeAssistant, mock_zoraxy: AiohttpClientMocker
) -> None:
    """An unexpected exception during validation shows an 'unknown' error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with patch(
        "custom_components.zoraxy.config_flow._async_validate",
        side_effect=ValueError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], MOCK_USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_reauth_flow_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A connection error during reauth keeps the form open with an error."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/login.html",
        exc=aiohttp.ClientConnectionError("connection refused"),
    )

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_invalid_auth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Wrong credentials during reconfigure keep the form open with an error."""
    mock_config_entry.add_to_hass(hass)
    mock_zoraxy_endpoints(aioclient_mock, login_status=401)

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauth_flow_unknown_error(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An unexpected exception during reauth shows an 'unknown' error."""
    mock_config_entry.add_to_hass(hass)
    result = await mock_config_entry.start_reauth_flow(hass)

    with patch(
        "custom_components.zoraxy.config_flow._async_validate",
        side_effect=ValueError("boom"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "admin", CONF_PASSWORD: "new-secret"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_reconfigure_flow_cannot_connect(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A connection error during reconfigure keeps the form open with an error."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/login.html",
        exc=aiohttp.ClientConnectionError("connection refused"),
    )

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reconfigure_flow_wrong_instance(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reconfiguring against a different Zoraxy instance aborts."""
    mock_config_entry.add_to_hass(hass)
    mock_zoraxy_endpoints(aioclient_mock, node_uuid="a-different-node-uuid")

    result = await mock_config_entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MOCK_USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_instance"
