"""Sensor platform for the Zoraxy integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import ZoraxyConfigEntry, ZoraxyData, uptime_targets_for_host
from .entity import ZoraxyCertEntity, ZoraxyHostEntity, ZoraxyServerEntity

# Entities only read from the coordinator, they don't issue their own
# requests, so there is nothing to serialize.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class ZoraxyServerSensorDescription(SensorEntityDescription):
    """Describes a sensor of the Zoraxy instance."""

    value_fn: Callable[[ZoraxyData], StateType]
    available_fn: Callable[[ZoraxyData], bool] | None = None
    attributes_fn: Callable[[ZoraxyData], dict[str, Any] | None] | None = None


SERVER_SENSORS: tuple[ZoraxyServerSensorDescription, ...] = (
    ZoraxyServerSensorDescription(
        key="proxy_hosts",
        translation_key="proxy_hosts",
        value_fn=lambda data: len(data.hosts),
    ),
    ZoraxyServerSensorDescription(
        key="active_proxy_hosts",
        translation_key="active_proxy_hosts",
        value_fn=lambda data: sum(host.enabled for host in data.hosts.values()),
    ),
    ZoraxyServerSensorDescription(
        key="proxy_server_port",
        translation_key="proxy_server_port",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.status.port,
    ),
    ZoraxyServerSensorDescription(
        key="total_requests_today",
        translation_key="total_requests_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.stats.total_requests if data.stats else None,
    ),
    ZoraxyServerSensorDescription(
        key="valid_requests_today",
        translation_key="valid_requests_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.stats.valid_requests if data.stats else None,
    ),
    ZoraxyServerSensorDescription(
        key="error_requests_today",
        translation_key="error_requests_today",
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.stats.error_requests if data.stats else None,
    ),
    ZoraxyServerSensorDescription(
        key="blacklisted_ips",
        translation_key="blacklisted_ips",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.access_rule.blacklisted_ip_count if data.access_rule else None
        ),
        available_fn=lambda data: data.access_rule is not None,
    ),
    ZoraxyServerSensorDescription(
        key="blacklisted_countries",
        translation_key="blacklisted_countries",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.access_rule.blacklisted_country_count if data.access_rule else None
        ),
        available_fn=lambda data: data.access_rule is not None,
        attributes_fn=lambda data: (
            {
                "country_codes": data.access_rule.blacklisted_countries,
                "country_names": data.access_rule.blacklisted_country_names,
            }
            if data.access_rule
            else None
        ),
    ),
    ZoraxyServerSensorDescription(
        key="whitelisted_ips",
        translation_key="whitelisted_ips",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.access_rule.whitelisted_ip_count if data.access_rule else None
        ),
        available_fn=lambda data: data.access_rule is not None,
    ),
    ZoraxyServerSensorDescription(
        key="whitelisted_countries",
        translation_key="whitelisted_countries",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.access_rule.whitelisted_country_count if data.access_rule else None
        ),
        available_fn=lambda data: data.access_rule is not None,
        attributes_fn=lambda data: (
            {
                "country_codes": data.access_rule.whitelisted_countries,
                "country_names": data.access_rule.whitelisted_country_names,
            }
            if data.access_rule
            else None
        ),
    ),
    ZoraxyServerSensorDescription(
        key="cpu_usage",
        translation_key="cpu_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.system_resources.cpu_usage
            if data.system_resources and data.system_resources.ready
            else None
        ),
        available_fn=lambda data: data.system_resources is not None,
        attributes_fn=lambda data: (
            {
                "host_os": data.system_resources.host_os,
                "host_arch": data.system_resources.host_arch,
                "host_name": data.system_resources.host_name,
            }
            if data.system_resources
            else None
        ),
    ),
    ZoraxyServerSensorDescription(
        key="ram_usage",
        translation_key="ram_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.system_resources.ram_usage
            if data.system_resources and data.system_resources.ready
            else None
        ),
        available_fn=lambda data: data.system_resources is not None,
        attributes_fn=lambda data: (
            {
                "used": data.system_resources.used_ram,
                "total": data.system_resources.total_ram,
            }
            if data.system_resources
            else None
        ),
    ),
    ZoraxyServerSensorDescription(
        key="disk_usage",
        translation_key="disk_usage",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: (
            data.system_resources.disk_usage
            if data.system_resources and data.system_resources.ready
            else None
        ),
        available_fn=lambda data: data.system_resources is not None,
        attributes_fn=lambda data: (
            {
                "used_bytes": data.system_resources.disk_used,
                "total_bytes": data.system_resources.disk_total,
                "path": data.system_resources.disk_path,
            }
            if data.system_resources
            else None
        ),
    ),
)

QUICKBAN_DESCRIPTION = SensorEntityDescription(
    key="quickban_entries",
    translation_key="quickban_entries",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)

WEBSERVER_PORT_DESCRIPTION = SensorEntityDescription(
    key="static_web_server_port",
    translation_key="static_web_server_port",
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,
)

LATENCY_DESCRIPTION = SensorEntityDescription(
    key="latency",
    translation_key="latency",
    native_unit_of_measurement=UnitOfTime.MILLISECONDS,
    state_class=SensorStateClass.MEASUREMENT,
)

HOST_REQUESTS_DESCRIPTION = SensorEntityDescription(
    key="host_requests_today",
    translation_key="host_requests_today",
    state_class=SensorStateClass.TOTAL_INCREASING,
)

CERT_EXPIRY_DESCRIPTION = SensorEntityDescription(
    key="cert_expiry",
    translation_key="cert_expiry",
    device_class=SensorDeviceClass.TIMESTAMP,
)

EXPIRED_DOMAINS_DESCRIPTION = SensorEntityDescription(
    key="expired_domains",
    translation_key="expired_domains",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoraxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zoraxy sensors."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            *(
                ZoraxyServerSensor(coordinator, description)
                for description in SERVER_SENSORS
            ),
            ZoraxyQuickBanSensor(coordinator, QUICKBAN_DESCRIPTION),
            ZoraxyWebServerPortSensor(coordinator, WEBSERVER_PORT_DESCRIPTION),
            ZoraxyExpiredDomainsSensor(coordinator, EXPIRED_DOMAINS_DESCRIPTION),
        ]
    )

    known_latency_hosts: set[str] = set()
    known_request_hosts: set[str] = set()
    known_certs: set[str] = set()

    @callback
    def _async_add_dynamic_sensors() -> None:
        """Add sensors for newly discovered hosts and certificates."""
        new_latency_sensors = [
            ZoraxyHostLatencySensor(
                coordinator,
                LATENCY_DESCRIPTION,
                host_key,
                on_remove=known_latency_hosts.discard,
            )
            for host_key in coordinator.data.hosts
            if host_key not in known_latency_hosts
            and uptime_targets_for_host(coordinator.data, host_key)
        ]
        known_latency_hosts.update(entity.host_key for entity in new_latency_sensors)
        new_request_sensors = [
            ZoraxyHostRequestsSensor(
                coordinator,
                HOST_REQUESTS_DESCRIPTION,
                host_key,
                on_remove=known_request_hosts.discard,
            )
            for host_key in coordinator.data.hosts
            if host_key not in known_request_hosts
        ]
        known_request_hosts.update(entity.host_key for entity in new_request_sensors)
        new_cert_sensors = [
            ZoraxyCertExpirySensor(
                coordinator,
                CERT_EXPIRY_DESCRIPTION,
                filename,
                on_remove=known_certs.discard,
            )
            for filename in coordinator.data.certs
            if filename not in known_certs
        ]
        known_certs.update(entity.cert_filename for entity in new_cert_sensors)
        new_entities = [*new_latency_sensors, *new_request_sensors, *new_cert_sensors]
        if new_entities:
            async_add_entities(new_entities)

    _async_add_dynamic_sensors()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_dynamic_sensors))


class ZoraxyServerSensor(ZoraxyServerEntity, SensorEntity):
    """Sensor on the Zoraxy instance device."""

    entity_description: ZoraxyServerSensorDescription

    @property
    def available(self) -> bool:
        """Unavailable while a required backing module hasn't reported data."""
        available_fn = self.entity_description.available_fn
        return super().available and (
            available_fn is None or available_fn(self.coordinator.data)
        )

    @property
    def native_value(self) -> StateType:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sensor's extra attributes, if it defines any."""
        attributes_fn = self.entity_description.attributes_fn
        return None if attributes_fn is None else attributes_fn(self.coordinator.data)


class ZoraxyCertExpirySensor(ZoraxyCertEntity, SensorEntity):
    """Expiry timestamp of a TLS certificate."""

    @property
    def native_value(self) -> datetime | None:
        """Return the expiry date of the certificate."""
        cert = self.cert
        return cert.expires_at if cert else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose certificate details."""
        cert = self.cert
        if cert is None:
            return None
        return {
            "domain": cert.domain,
            "filename": cert.filename,
            "remaining_days": cert.remaining_days,
            "dns_challenge": cert.use_dns,
            "fallback_certificate": cert.is_fallback,
        }


class ZoraxyHostLatencySensor(ZoraxyHostEntity, SensorEntity):
    """Upstream latency of a proxy host, measured by the uptime monitor."""

    @property
    def native_value(self) -> StateType:
        """Return the average latency of all online upstreams."""
        latencies = [
            target.latency_ms
            for target in uptime_targets_for_host(self.coordinator.data, self.host_key)
            if target.online
        ]
        if not latencies:
            return None
        return round(sum(latencies) / len(latencies))

    @property
    def available(self) -> bool:
        """Only available while the uptime monitor reports this host."""
        return super().available and bool(
            uptime_targets_for_host(self.coordinator.data, self.host_key)
        )


class ZoraxyHostRequestsSensor(ZoraxyHostEntity, SensorEntity):
    """Requests handled today by a single proxy host.

    Backed by a much heavier API call than the rest of the data, fetched on
    its own longer cadence (see the coordinator) — this can lag behind the
    other, more frequently updated entities by several minutes.
    """

    @property
    def available(self) -> bool:
        """Unavailable until the per-host breakdown has been fetched once."""
        return (
            super().available
            and self.host_key in self.coordinator.data.host_request_counts
        )

    @property
    def native_value(self) -> StateType:
        """Return today's request count for this host."""
        return self.coordinator.data.host_request_counts.get(self.host_key)


class ZoraxyQuickBanSensor(ZoraxyServerEntity, SensorEntity):
    """Distinct client IPs seen today, ranked by request count.

    This mirrors Zoraxy's "quick ban" view: despite the name, it is a live
    ranking derived from today's request statistics, not a persisted list
    of addresses that are actually banned.
    """

    @property
    def native_value(self) -> StateType:
        """Return the number of tracked client IPs."""
        return len(self.coordinator.data.quickban)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the highest-traffic client IPs."""
        top_entries = sorted(
            self.coordinator.data.quickban,
            key=lambda entry: entry.count,
            reverse=True,
        )[:10]
        return {
            "top_ips": [
                {
                    "ip": entry.ip_addr,
                    "count": entry.count,
                    "country_code": entry.country_code,
                }
                for entry in top_entries
            ]
        }


class ZoraxyExpiredDomainsSensor(ZoraxyServerEntity, SensorEntity):
    """Domains whose certificate Zoraxy currently considers expired.

    A non-zero count here means those domains need attention: either
    auto-renewal isn't enabled/working for them, or ACME renewal is failing.
    """

    @property
    def native_value(self) -> StateType:
        """Return the number of domains with an expired certificate."""
        return len(self.coordinator.data.expired_domains)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the affected domain names."""
        return {"domains": self.coordinator.data.expired_domains}


class ZoraxyWebServerPortSensor(ZoraxyServerEntity, SensorEntity):
    """Listening port of the built-in static web server."""

    @property
    def available(self) -> bool:
        """Unavailable while the static web server module hasn't reported data."""
        return super().available and self.coordinator.data.webserver is not None

    @property
    def native_value(self) -> StateType:
        """Return the configured port, if the module reported data."""
        webserver = self.coordinator.data.webserver
        return webserver.port if webserver else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the web root and interface-binding setting."""
        webserver = self.coordinator.data.webserver
        if webserver is None:
            return None
        return {
            "web_root": webserver.web_root,
            "listen_all_interfaces": webserver.listen_all_interfaces,
        }
