"""Base entities for the Zoraxy integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ZoraxyCertificate, ZoraxyProxyHost, ZoraxyStreamProxy
from .const import DOMAIN, MANUFACTURER
from .coordinator import ZoraxyDataUpdateCoordinator


class ZoraxyEntity(CoordinatorEntity[ZoraxyDataUpdateCoordinator]):
    """Common base for all Zoraxy entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ZoraxyDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.entity_description = description
        entry = coordinator.config_entry
        self._server_id = entry.unique_id or entry.entry_id

    def _instance_device_id(self) -> str | None:
        """Return the instance device's registry id, if it's registered yet.

        Used to link a per-item device (host, stream-proxy rule) to the main
        instance device via ``via_device_id``, which — unlike the deprecated
        ``via_device`` — needs the already-resolved registry id rather than
        the identifier tuple. The instance device is normally registered
        before any per-item device (its entity is always added first within
        each platform's ``async_setup_entry``), but this returns ``None``
        instead of raising if it isn't, same as Home Assistant's own
        fallback when resolving the deprecated ``via_device``.
        """
        entry = self.coordinator.config_entry
        device = dr.async_get(self.coordinator.hass).async_get_device_by_identifier(
            (DOMAIN, self._server_id), entry.entry_id
        )
        return device.id if device else None


class ZoraxyServerEntity(ZoraxyEntity):
    """Entity attached to the Zoraxy instance device."""

    def __init__(
        self,
        coordinator: ZoraxyDataUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator, description)
        self._attr_unique_id = f"{self._server_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._server_id)},
            name=coordinator.config_entry.title,
            manufacturer=MANUFACTURER,
            model="Reverse proxy server",
            sw_version=coordinator.data.info.version,
            configuration_url=coordinator.client.base_url,
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, keeping the firmware version current.

        Overridden (instead of only setting ``_attr_device_info`` once in
        ``__init__``) so a Zoraxy version change is reflected in the device
        registry on the next update, without waiting for the integration to
        be reloaded.
        """
        info = cast(DeviceInfo, dict(self._attr_device_info or {}))
        info["sw_version"] = self.coordinator.data.info.version
        return info


class ZoraxyCertEntity(ZoraxyServerEntity):
    """Entity for a TLS certificate, attached to the instance device."""

    def __init__(
        self,
        coordinator: ZoraxyDataUpdateCoordinator,
        description: EntityDescription,
        cert_filename: str,
        *,
        on_remove: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the entity.

        ``on_remove`` is called with the certificate filename when this
        entity is actually removed from Home Assistant (e.g. because its
        device was deleted from the device page). The platform uses it to
        forget the filename from its "known certificates" set, so a
        certificate that reappears later under the same filename gets a
        fresh entity instead of being silently ignored forever.
        """
        super().__init__(coordinator, description)
        self.cert_filename = cert_filename
        self._removed_callback = on_remove
        self._attr_unique_id = (
            f"{self._server_id}_cert_{cert_filename}_{description.key}"
        )
        cert = coordinator.data.certs.get(cert_filename)
        self._attr_translation_placeholders = {
            "domain": cert.domain if cert else cert_filename
        }

    @property
    def cert(self) -> ZoraxyCertificate | None:
        """Return the certificate data, if it still exists."""
        return self.coordinator.data.certs.get(self.cert_filename)

    @property
    def available(self) -> bool:
        """Entities become unavailable when the certificate is removed."""
        return super().available and self.cert_filename in self.coordinator.data.certs

    async def async_will_remove_from_hass(self) -> None:
        """Notify the platform that this certificate's key is free again."""
        await super().async_will_remove_from_hass()
        if self._removed_callback is not None:
            self._removed_callback(self.cert_filename)


class ZoraxyHostEntity(ZoraxyEntity):
    """Entity attached to a proxy-host device."""

    def __init__(
        self,
        coordinator: ZoraxyDataUpdateCoordinator,
        description: EntityDescription,
        host_key: str,
        *,
        on_remove: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the entity.

        ``on_remove`` is called with the host key when this entity is
        actually removed from Home Assistant (e.g. because its device was
        deleted from the device page). The platform uses it to forget the
        key from its "known hosts" set, so a host that reappears later
        under the same key gets a fresh entity instead of being silently
        ignored forever.
        """
        super().__init__(coordinator, description)
        self.host_key = host_key
        self._removed_callback = on_remove
        self._attr_unique_id = f"{self._server_id}_host_{host_key}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._server_id}_host_{host_key}")},
            name=host_key,
            manufacturer=MANUFACTURER,
            model="Proxy host",
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, linked to the instance device.

        ``via_device_id`` is typed as plain ``str`` (not optional) on
        ``DeviceInfo`` — the key must be omitted entirely rather than set to
        ``None`` when the instance device isn't registered yet.
        """
        info = cast(DeviceInfo, dict(self._attr_device_info or {}))
        if via_device_id := self._instance_device_id():
            info["via_device_id"] = via_device_id
        return info

    @property
    def host(self) -> ZoraxyProxyHost | None:
        """Return the proxy host data, if it still exists."""
        return self.coordinator.data.hosts.get(self.host_key)

    @property
    def available(self) -> bool:
        """Entities become unavailable when the rule is deleted in Zoraxy."""
        return super().available and self.host_key in self.coordinator.data.hosts

    async def async_will_remove_from_hass(self) -> None:
        """Notify the platform that this host's key is free again."""
        await super().async_will_remove_from_hass()
        if self._removed_callback is not None:
            self._removed_callback(self.host_key)


class ZoraxyStreamProxyEntity(ZoraxyEntity):
    """Entity for a TCP/UDP stream-proxy rule, with its own device.

    Deliberately extends ``ZoraxyEntity`` rather than ``ZoraxyServerEntity``:
    the latter's ``device_info`` property always stamps the Zoraxy instance's
    firmware version onto ``sw_version``, which doesn't apply to a stream-proxy
    rule's own device (same reasoning as ``ZoraxyHostEntity``).
    """

    def __init__(
        self,
        coordinator: ZoraxyDataUpdateCoordinator,
        description: EntityDescription,
        proxy_uuid: str,
        *,
        on_remove: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize the entity.

        ``on_remove`` is called with the rule's UUID when this entity is
        actually removed from Home Assistant (e.g. because its device was
        deleted from the device page). The platform uses it to forget the
        UUID from its "known stream proxies" set, so a rule that reappears
        later under the same UUID gets a fresh entity instead of being
        silently ignored forever.
        """
        super().__init__(coordinator, description)
        self.proxy_uuid = proxy_uuid
        self._removed_callback = on_remove
        self._attr_unique_id = (
            f"{self._server_id}_streamproxy_{proxy_uuid}_{description.key}"
        )
        proxy = coordinator.data.stream_proxies.get(proxy_uuid)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{self._server_id}_streamproxy_{proxy_uuid}")},
            name=proxy.name if proxy else proxy_uuid,
            manufacturer=MANUFACTURER,
            model="Stream proxy rule",
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info, linked to the instance device.

        ``via_device_id`` is typed as plain ``str`` (not optional) on
        ``DeviceInfo`` — the key must be omitted entirely rather than set to
        ``None`` when the instance device isn't registered yet.
        """
        info = cast(DeviceInfo, dict(self._attr_device_info or {}))
        if via_device_id := self._instance_device_id():
            info["via_device_id"] = via_device_id
        return info

    @property
    def proxy(self) -> ZoraxyStreamProxy | None:
        """Return the stream-proxy rule data, if it still exists."""
        return self.coordinator.data.stream_proxies.get(self.proxy_uuid)

    @property
    def available(self) -> bool:
        """Entities become unavailable when the rule is deleted in Zoraxy."""
        stream_proxies = self.coordinator.data.stream_proxies
        return super().available and self.proxy_uuid in stream_proxies

    async def async_will_remove_from_hass(self) -> None:
        """Notify the platform that this rule's UUID is free again."""
        await super().async_will_remove_from_hass()
        if self._removed_callback is not None:
            self._removed_callback(self.proxy_uuid)
