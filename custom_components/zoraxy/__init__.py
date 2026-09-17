"""The Zoraxy integration."""

from __future__ import annotations

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .api import ZoraxyClient, ZoraxyError
from .const import (
    ATTR_COMMENT,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_IP_ADDRESS,
    DEFAULT_PORT,
    DOMAIN,
    SERVICE_BAN_IP,
    SERVICE_UNBAN_IP,
)
from .coordinator import ZoraxyConfigEntry, ZoraxyData, ZoraxyDataUpdateCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]

BAN_IP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): str,
        vol.Required(ATTR_IP_ADDRESS): cv.string,
        vol.Optional(ATTR_COMMENT, default=""): cv.string,
    }
)
UNBAN_IP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): str,
        vol.Required(ATTR_IP_ADDRESS): cv.string,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register Zoraxy's config-entry-scoped service actions."""

    def _get_coordinator(config_entry_id: str) -> ZoraxyDataUpdateCoordinator:
        """Resolve a loaded Zoraxy config entry from a service call."""
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="config_entry_not_found",
                translation_placeholders={"config_entry_id": config_entry_id},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="config_entry_not_loaded",
                translation_placeholders={"config_entry_id": config_entry_id},
            )
        return entry.runtime_data

    async def _async_ban_ip(call: ServiceCall) -> None:
        """Add an IP address to the Zoraxy blacklist."""
        coordinator = _get_coordinator(call.data[ATTR_CONFIG_ENTRY_ID])
        ip_address = call.data[ATTR_IP_ADDRESS]
        try:
            await coordinator.client.async_add_ip_to_blacklist(
                ip_address, call.data[ATTR_COMMENT]
            )
        except ZoraxyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="ban_ip_failed",
                translation_placeholders={"ip_address": ip_address, "error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    async def _async_unban_ip(call: ServiceCall) -> None:
        """Remove an IP address from the Zoraxy blacklist."""
        coordinator = _get_coordinator(call.data[ATTR_CONFIG_ENTRY_ID])
        ip_address = call.data[ATTR_IP_ADDRESS]
        try:
            await coordinator.client.async_remove_ip_from_blacklist(ip_address)
        except ZoraxyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unban_ip_failed",
                translation_placeholders={"ip_address": ip_address, "error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    hass.services.async_register(
        DOMAIN, SERVICE_BAN_IP, _async_ban_ip, schema=BAN_IP_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UNBAN_IP, _async_unban_ip, schema=UNBAN_IP_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ZoraxyConfigEntry) -> bool:
    """Set up Zoraxy from a config entry."""
    # Dedicated session: the unsafe cookie jar is required so the Zoraxy
    # session cookie is also stored when the host is an IP address.
    session = async_create_clientsession(
        hass,
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
        cookie_jar=CookieJar(unsafe=True),
    )
    client = ZoraxyClient(
        session=session,
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        use_ssl=entry.data.get(CONF_SSL, False),
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )

    coordinator = ZoraxyDataUpdateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    @callback
    def _async_cleanup_stale_devices() -> None:
        """Remove devices for hosts/stream-proxy rules no longer in Zoraxy.

        Their entities already become unavailable on their own (see the
        ``available`` overrides in entity.py); this additionally removes the
        now-orphaned device itself instead of leaving it for manual cleanup
        from the device page.
        """
        server_id = entry.unique_id or entry.entry_id
        active_ids = _active_device_ids(server_id, coordinator.data)
        device_registry = dr.async_get(hass)
        for device in dr.async_entries_for_config_entry(
            device_registry, entry.entry_id
        ):
            zoraxy_ids = {
                identifier for domain, identifier in device.identifiers
                if domain == DOMAIN
            }
            if zoraxy_ids and zoraxy_ids.isdisjoint(active_ids):
                device_registry.async_remove_device(device.id)

    _async_cleanup_stale_devices()
    entry.async_on_unload(
        coordinator.async_add_listener(_async_cleanup_stale_devices)
    )
    return True


def _active_device_ids(server_id: str, data: ZoraxyData) -> set[str]:
    """Return the device identifiers that are still active in Zoraxy.

    Shared by the stale-device cleanup listener and
    ``async_remove_config_entry_device``, so both agree on what "still
    exists" means.
    """
    return (
        {server_id}
        | {f"{server_id}_host_{host_key}" for host_key in data.hosts}
        | {
            f"{server_id}_streamproxy_{proxy_uuid}"
            for proxy_uuid in data.stream_proxies
        }
    )


async def async_unload_entry(hass: HomeAssistant, entry: ZoraxyConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ZoraxyConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ZoraxyConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing devices of proxy hosts that no longer exist.

    Normally redundant now that stale devices are cleaned up automatically
    (see ``_async_cleanup_stale_devices`` above), but still needed for the
    brief window between an object disappearing in Zoraxy and the next
    coordinator refresh, and as a safety net if that listener doesn't fire.
    """
    coordinator = entry.runtime_data
    server_id = entry.unique_id or entry.entry_id
    active_ids = _active_device_ids(server_id, coordinator.data)
    return not any(
        identifier[1] in active_ids
        for identifier in device_entry.identifiers
        if identifier[0] == DOMAIN
    )
