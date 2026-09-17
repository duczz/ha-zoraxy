"""DataUpdateCoordinator for the Zoraxy integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    ZoraxyAccessRule,
    ZoraxyAuthError,
    ZoraxyCertificate,
    ZoraxyClient,
    ZoraxyError,
    ZoraxyInfo,
    ZoraxyProxyHost,
    ZoraxyQuickBanEntry,
    ZoraxyStats,
    ZoraxyStatus,
    ZoraxyStreamProxy,
    ZoraxySystemResource,
    ZoraxyUptimeTarget,
    ZoraxyWebServerStatus,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN, HOST_REQUEST_STATS_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Explicit TypeAlias: without it, mypy (running here without the real
# homeassistant package installed) doesn't recognize this as a type, which
# cascades into "not valid as a type" / spurious attribute errors wherever
# ZoraxyConfigEntry is used as an annotation. Kept as a TypeAlias rather
# than the newer PEP 695 `type` statement so this still parses on the
# oldest Python version our supported HA floor (see hacs.json) might run.
ZoraxyConfigEntry: TypeAlias = ConfigEntry["ZoraxyDataUpdateCoordinator"]


@dataclass(slots=True)
class ZoraxyData:
    """All data fetched from Zoraxy in one update cycle."""

    info: ZoraxyInfo
    status: ZoraxyStatus
    hosts: dict[str, ZoraxyProxyHost]
    uptime: dict[str, ZoraxyUptimeTarget]
    stats: ZoraxyStats | None
    certs: dict[str, ZoraxyCertificate]
    access_rule: ZoraxyAccessRule | None
    quickban: list[ZoraxyQuickBanEntry]
    webserver: ZoraxyWebServerStatus | None
    stream_proxies: dict[str, ZoraxyStreamProxy]
    system_resources: ZoraxySystemResource | None
    auto_renew_enabled: bool | None
    expired_domains: list[str]
    host_request_counts: dict[str, int]


def uptime_targets_for_host(
    data: ZoraxyData, host_key: str
) -> list[ZoraxyUptimeTarget]:
    """Return the uptime targets belonging to a proxy host.

    Zoraxy keys uptime targets by the matching domain; rules with multiple
    upstreams get one target per upstream, suffixed with " (upstream:N)".
    """
    prefix = f"{host_key} (upstream:"
    return [
        target
        for target_id, target in data.uptime.items()
        if target_id == host_key or target_id.startswith(prefix)
    ]


class ZoraxyDataUpdateCoordinator(DataUpdateCoordinator[ZoraxyData]):
    """Coordinator polling a single Zoraxy instance."""

    config_entry: ZoraxyConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ZoraxyConfigEntry,
        client: ZoraxyClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
        )
        self.client = client
        self._last_host_stats_fetch: datetime | None = None

    async def _async_update_data(self) -> ZoraxyData:
        """Fetch all data from Zoraxy."""
        try:
            info = await self.client.async_get_info()
            status = await self.client.async_get_status()
            hosts = await self.client.async_list_proxy_hosts()

            uptime: dict[str, ZoraxyUptimeTarget] = {}
            try:
                uptime = await self.client.async_get_uptime()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                # The uptime monitor returns HTTP 500 while it is still
                # initializing after a Zoraxy restart; don't fail the update.
                _LOGGER.debug("Uptime monitor data unavailable: %s", err)

            stats: ZoraxyStats | None = None
            try:
                stats = await self.client.async_get_stats()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Statistics unavailable: %s", err)

            certs: dict[str, ZoraxyCertificate] = {}
            try:
                certs = await self.client.async_list_certificates()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Certificate list unavailable: %s", err)

            access_rule: ZoraxyAccessRule | None = None
            try:
                access_rule = await self.client.async_get_access_rule()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Access control rule unavailable: %s", err)

            quickban: list[ZoraxyQuickBanEntry] = []
            try:
                quickban = await self.client.async_list_quickban()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Quick-ban list unavailable: %s", err)

            webserver: ZoraxyWebServerStatus | None = None
            try:
                webserver = await self.client.async_get_webserver_status()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Static web server status unavailable: %s", err)

            stream_proxies: dict[str, ZoraxyStreamProxy] = {}
            try:
                stream_proxies = await self.client.async_list_stream_proxies()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Stream proxy list unavailable: %s", err)

            system_resources: ZoraxySystemResource | None = None
            try:
                system_resources = await self.client.async_get_system_resources()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Host system resources unavailable: %s", err)

            auto_renew_enabled: bool | None = None
            try:
                auto_renew_enabled = await self.client.async_get_auto_renew_enabled()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("ACME auto-renew state unavailable: %s", err)

            expired_domains: list[str] = []
            try:
                expired_domains = await self.client.async_list_expired_domains()
            except ZoraxyAuthError:
                raise
            except ZoraxyError as err:
                _LOGGER.debug("Expired-domain list unavailable: %s", err)

            # Much heavier payload than everything else polled here, so it's
            # fetched on its own, longer cadence instead of every refresh.
            # Between fetches, keep the previous value instead of resetting
            # it to empty.
            host_request_counts = (
                self.data.host_request_counts if self.data else {}
            )
            now = dt_util.utcnow()
            if (
                self._last_host_stats_fetch is None
                or now - self._last_host_stats_fetch
                >= timedelta(seconds=HOST_REQUEST_STATS_INTERVAL)
            ):
                try:
                    host_request_counts = (
                        await self.client.async_get_host_request_counts()
                    )
                    self._last_host_stats_fetch = now
                except ZoraxyAuthError:
                    raise
                except ZoraxyError as err:
                    _LOGGER.debug("Per-host request counts unavailable: %s", err)
        except ZoraxyAuthError as err:
            raise ConfigEntryAuthFailed(
                f"Authentication with Zoraxy failed: {err}"
            ) from err
        except ZoraxyError as err:
            raise UpdateFailed(f"Error communicating with Zoraxy: {err}") from err

        return ZoraxyData(
            info=info,
            status=status,
            hosts=hosts,
            uptime=uptime,
            stats=stats,
            certs=certs,
            access_rule=access_rule,
            quickban=quickban,
            webserver=webserver,
            stream_proxies=stream_proxies,
            system_resources=system_resources,
            auto_renew_enabled=auto_renew_enabled,
            expired_domains=expired_domains,
            host_request_counts=host_request_counts,
        )
