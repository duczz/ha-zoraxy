"""Binary sensor platform for the Zoraxy integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CERT_WARNING_DAYS
from .coordinator import ZoraxyConfigEntry, uptime_targets_for_host
from .entity import ZoraxyCertEntity, ZoraxyHostEntity, ZoraxyServerEntity

# Entities only read from the coordinator, they don't issue their own
# requests, so there is nothing to serialize.
PARALLEL_UPDATES = 0

RUNNING_DESCRIPTION = BinarySensorEntityDescription(
    key="running",
    translation_key="running",
    device_class=BinarySensorDeviceClass.RUNNING,
)

ONLINE_DESCRIPTION = BinarySensorEntityDescription(
    key="online",
    translation_key="online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
)

CERT_EXPIRING_DESCRIPTION = BinarySensorEntityDescription(
    key="cert_expiring_soon",
    translation_key="cert_expiring_soon",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoraxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zoraxy binary sensors."""
    coordinator = entry.runtime_data

    async_add_entities([ZoraxyRunningBinarySensor(coordinator, RUNNING_DESCRIPTION)])

    known_hosts: set[str] = set()
    known_certs: set[str] = set()

    @callback
    def _async_add_dynamic_sensors() -> None:
        """Add sensors for newly discovered hosts and certificates."""
        new_host_sensors = [
            ZoraxyHostOnlineBinarySensor(
                coordinator, ONLINE_DESCRIPTION, host_key, on_remove=known_hosts.discard
            )
            for host_key in coordinator.data.hosts
            if host_key not in known_hosts
            and uptime_targets_for_host(coordinator.data, host_key)
        ]
        known_hosts.update(entity.host_key for entity in new_host_sensors)
        new_cert_sensors = [
            ZoraxyCertExpiringSoonBinarySensor(
                coordinator,
                CERT_EXPIRING_DESCRIPTION,
                filename,
                on_remove=known_certs.discard,
            )
            for filename in coordinator.data.certs
            if filename not in known_certs
        ]
        known_certs.update(entity.cert_filename for entity in new_cert_sensors)
        if new_host_sensors or new_cert_sensors:
            async_add_entities([*new_host_sensors, *new_cert_sensors])

    _async_add_dynamic_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_dynamic_sensors))


class ZoraxyRunningBinarySensor(ZoraxyServerEntity, BinarySensorEntity):
    """Whether the reverse proxy server is running."""

    @property
    def is_on(self) -> bool:
        """Return True if the proxy server is running."""
        return self.coordinator.data.status.running


class ZoraxyCertExpiringSoonBinarySensor(ZoraxyCertEntity, BinarySensorEntity):
    """Whether a TLS certificate expires within the warning window."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the certificate expires soon (or already has)."""
        cert = self.cert
        if cert is None:
            return None
        return cert.remaining_days <= CERT_WARNING_DAYS

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the remaining days and warning threshold."""
        cert = self.cert
        if cert is None:
            return None
        return {
            "remaining_days": cert.remaining_days,
            "warning_days": CERT_WARNING_DAYS,
        }


class ZoraxyHostOnlineBinarySensor(ZoraxyHostEntity, BinarySensorEntity):
    """Whether the upstream(s) of a proxy host are reachable."""

    @property
    def is_on(self) -> bool | None:
        """Return True if at least one upstream is online."""
        targets = uptime_targets_for_host(self.coordinator.data, self.host_key)
        if not targets:
            return None
        return any(target.online for target in targets)

    @property
    def available(self) -> bool:
        """Only available while the uptime monitor reports this host."""
        return super().available and bool(
            uptime_targets_for_host(self.coordinator.data, self.host_key)
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose per-upstream details."""
        return {
            "upstreams": [
                {
                    "name": target.name,
                    "url": target.url,
                    "online": target.online,
                    "status_code": target.status_code,
                    "latency_ms": target.latency_ms,
                    "last_check": dt_util.utc_from_timestamp(
                        target.timestamp
                    ).isoformat()
                    if target.timestamp
                    else None,
                }
                for target in uptime_targets_for_host(
                    self.coordinator.data, self.host_key
                )
            ]
        }
