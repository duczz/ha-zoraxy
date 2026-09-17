"""Tests for the coordinator's per-module defensive fetch behavior.

Ten of the thirteen Zoraxy endpoints polled each cycle (everything except
info/status/hosts) are fetched defensively: a generic failure there must
not fail the whole update, but an auth failure must still propagate and
trigger reauth. Covers coordinator.py's try/except ladder branch by branch.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.zoraxy.const import DOMAIN, HOST_REQUEST_STATS_INTERVAL

from .conftest import MOCK_BASE_URL, mock_zoraxy_endpoints

# path, ZoraxyData attribute, "empty" value for that attribute
DEFENSIVE_MODULES = [
    ("/api/utm/list", "uptime", {}),
    ("/api/stats/summary", "stats", None),
    ("/api/cert/list", "certs", {}),
    ("/api/access/list", "access_rule", None),
    ("/api/quickban/list", "quickban", []),
    ("/api/webserv/status", "webserver", None),
    ("/api/streamprox/config/list", "stream_proxies", {}),
    ("/api/stats/system", "system_resources", None),
    ("/api/acme/autoRenew/enable", "auto_renew_enabled", None),
    ("/api/acme/listExpiredDomains", "expired_domains", []),
]


@pytest.mark.parametrize(("path", "attr", "empty_value"), DEFENSIVE_MODULES)
async def test_module_failure_does_not_break_setup(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    path: str,
    attr: str,
    empty_value: object,
) -> None:
    """A generic failure in one module leaves the rest of the update intact."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{MOCK_BASE_URL}{path}", status=500, text="internal error")
    mock_zoraxy_endpoints(aioclient_mock)

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert getattr(coordinator.data, attr) == empty_value
    # The rest of the update still went through.
    assert coordinator.data.info.version == "3.3.3"


@pytest.mark.parametrize(("path", "attr", "empty_value"), DEFENSIVE_MODULES)
async def test_module_auth_failure_triggers_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    path: str,
    attr: str,
    empty_value: object,
) -> None:
    """An auth failure in a defensively-fetched module still triggers reauth.

    Unlike a generic error, this must not be swallowed — the whole point of
    re-raising ZoraxyAuthError in each except block.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{MOCK_BASE_URL}{path}", status=401)
    mock_zoraxy_endpoints(aioclient_mock)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)


async def test_primary_fetch_failure_fails_the_whole_update(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """A failure in a non-defensive fetch (info/status/hosts) fails the update.

    Contrasts with the defensive modules above: these three are not wrapped
    in their own try/except, so any failure aborts the whole refresh.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/proxy/status", status=500, text="internal error"
    )
    mock_zoraxy_endpoints(aioclient_mock)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


def _full_summary_calls(aioclient_mock: AiohttpClientMocker) -> list:
    """Return recorded calls to the un-throttled, full stats/summary fetch."""
    return [
        call
        for call in aioclient_mock.mock_calls
        if "stats/summary" in str(call[1]) and "fast" not in str(call[1])
    ]


async def test_host_request_counts_fetched_less_often_than_the_rest(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The heavier per-host breakdown isn't refetched on every coordinator cycle.

    It shares the /api/stats/summary endpoint with the cheap, always-fetched
    fast=true counters, so distinguishing them relies on the query string.
    """
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
    assert len(_full_summary_calls(aioclient_mock)) == 1

    coordinator = mock_config_entry.runtime_data
    assert coordinator.data.host_request_counts == {"example.com": 5}

    # A refresh right away must not refetch the heavier full summary.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(_full_summary_calls(aioclient_mock)) == 1
    assert coordinator.data.host_request_counts == {"example.com": 5}

    # Once the throttle window has elapsed, the next refresh fetches again.
    coordinator._last_host_stats_fetch = dt_util.utcnow() - timedelta(
        seconds=HOST_REQUEST_STATS_INTERVAL + 1
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert len(_full_summary_calls(aioclient_mock)) == 2


async def test_host_request_counts_auth_failure_triggers_reauth(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """An auth failure specifically on the throttled full-summary fetch reauths too.

    Registers the fast=true counters as succeeding and only the full-summary
    variant as unauthorized, so this exercises the auth branch of the
    host-request-counts fetch specifically, not the (already covered) fast
    counters fetch that runs earlier in the same update.
    """
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{MOCK_BASE_URL}/api/stats/summary",
        params={"fast": "true"},
        json={"TotalRequest": 0, "ValidRequest": 0, "ErrorRequest": 0},
    )
    aioclient_mock.get(f"{MOCK_BASE_URL}/api/stats/summary", status=401)
    mock_zoraxy_endpoints(aioclient_mock)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"]["source"] == "reauth" for flow in flows)
