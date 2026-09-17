"""Switch platform for the Zoraxy integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import ZoraxyClient, ZoraxyError
from .const import DOMAIN
from .coordinator import ZoraxyConfigEntry, ZoraxyData
from .entity import ZoraxyHostEntity, ZoraxyServerEntity, ZoraxyStreamProxyEntity

# Write actions (turn_on/turn_off) hit the same Zoraxy admin API as
# other platforms; serialize them instead of firing several at once.
PARALLEL_UPDATES = 1

PROXY_RULE_DESCRIPTION = SwitchEntityDescription(
    key="proxy_rule",
    translation_key="proxy_rule",
)


@dataclass(frozen=True, kw_only=True)
class ZoraxyServerSwitchDescription(SwitchEntityDescription):
    """Describes a switch for a global Zoraxy setting."""

    is_on_fn: Callable[[ZoraxyData], bool]
    set_fn: Callable[[ZoraxyClient, bool], Awaitable[None]]
    apply_local_fn: Callable[[ZoraxyData, bool], None]


SERVER_SWITCHES: tuple[ZoraxyServerSwitchDescription, ...] = (
    ZoraxyServerSwitchDescription(
        key="proxy_server",
        translation_key="proxy_server",
        entity_category=EntityCategory.CONFIG,
        # Stopping the whole proxy server can cut you off from every service
        # behind Zoraxy, so this switch must be enabled deliberately.
        entity_registry_enabled_default=False,
        is_on_fn=lambda data: data.status.running,
        set_fn=lambda client, value: client.async_set_proxy_running(value),
        apply_local_fn=lambda data, value: setattr(data.status, "running", value),
    ),
    ZoraxyServerSwitchDescription(
        key="https_redirect",
        translation_key="https_redirect",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: data.status.force_https_redirect,
        set_fn=lambda client, value: client.async_set_https_redirect(value),
        apply_local_fn=lambda data, value: setattr(
            data.status, "force_https_redirect", value
        ),
    ),
    ZoraxyServerSwitchDescription(
        key="port80",
        translation_key="port80",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda data: data.status.listen_on_port_80,
        set_fn=lambda client, value: client.async_set_port80_listener(value),
        apply_local_fn=lambda data, value: setattr(
            data.status, "listen_on_port_80", value
        ),
    ),
)


@dataclass(frozen=True, kw_only=True)
class ZoraxyOptionalSwitchDescription(SwitchEntityDescription):
    """Describes a switch backed by a sub-object that may be unavailable.

    Some Zoraxy modules (access control, static web server) can fail to
    report data independently of the rest of the instance (see the
    coordinator), so unlike ``ZoraxyServerSwitchDescription`` these
    callables work against that sub-object directly, and the entity
    becomes unavailable when ``get_root_fn`` returns ``None``.
    """

    get_root_fn: Callable[[ZoraxyData], Any | None]
    is_on_fn: Callable[[Any], bool]
    set_fn: Callable[[ZoraxyClient, Any, bool], Awaitable[None]]
    apply_local_fn: Callable[[Any, bool], None]


ACCESS_RULE_SWITCHES: tuple[ZoraxyOptionalSwitchDescription, ...] = (
    ZoraxyOptionalSwitchDescription(
        key="blacklist_enabled",
        translation_key="blacklist_enabled",
        entity_category=EntityCategory.CONFIG,
        get_root_fn=lambda data: data.access_rule,
        is_on_fn=lambda rule: rule.blacklist_enabled,
        set_fn=lambda client, rule, value: client.async_set_blacklist_enabled(
            value, rule_id=rule.rule_id
        ),
        apply_local_fn=lambda rule, value: setattr(rule, "blacklist_enabled", value),
    ),
    ZoraxyOptionalSwitchDescription(
        key="whitelist_enabled",
        translation_key="whitelist_enabled",
        entity_category=EntityCategory.CONFIG,
        get_root_fn=lambda data: data.access_rule,
        is_on_fn=lambda rule: rule.whitelist_enabled,
        set_fn=lambda client, rule, value: client.async_set_whitelist_enabled(
            value, rule_id=rule.rule_id
        ),
        apply_local_fn=lambda rule, value: setattr(rule, "whitelist_enabled", value),
    ),
    ZoraxyOptionalSwitchDescription(
        key="whitelist_allow_local",
        translation_key="whitelist_allow_local",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        get_root_fn=lambda data: data.access_rule,
        is_on_fn=lambda rule: rule.whitelist_allow_local,
        set_fn=lambda client, rule, value: client.async_set_whitelist_allow_local(
            value, rule_id=rule.rule_id
        ),
        apply_local_fn=lambda rule, value: setattr(
            rule, "whitelist_allow_local", value
        ),
    ),
    ZoraxyOptionalSwitchDescription(
        key="trust_proxy_headers_only",
        translation_key="trust_proxy_headers_only",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        get_root_fn=lambda data: data.access_rule,
        is_on_fn=lambda rule: rule.trust_proxy_headers_only,
        set_fn=lambda client, rule, value: client.async_set_trust_proxy_headers_only(
            value, rule_id=rule.rule_id
        ),
        apply_local_fn=lambda rule, value: setattr(
            rule, "trust_proxy_headers_only", value
        ),
    ),
)

WEBSERVER_SWITCHES: tuple[ZoraxyOptionalSwitchDescription, ...] = (
    ZoraxyOptionalSwitchDescription(
        key="static_web_server",
        translation_key="static_web_server",
        entity_category=EntityCategory.CONFIG,
        get_root_fn=lambda data: data.webserver,
        is_on_fn=lambda status: status.running,
        set_fn=lambda client, status, value: client.async_set_webserver_running(
            value
        ),
        apply_local_fn=lambda status, value: setattr(status, "running", value),
    ),
    ZoraxyOptionalSwitchDescription(
        key="static_web_server_dir_listing",
        translation_key="static_web_server_dir_listing",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        get_root_fn=lambda data: data.webserver,
        is_on_fn=lambda status: status.directory_listing,
        set_fn=lambda client, status, value: client.async_set_webserver_dir_listing(
            value
        ),
        apply_local_fn=lambda status, value: setattr(
            status, "directory_listing", value
        ),
    ),
)

STREAM_PROXY_DESCRIPTION = SwitchEntityDescription(
    key="stream_proxy",
    translation_key="stream_proxy",
)

AUTO_RENEW_DESCRIPTION = SwitchEntityDescription(
    key="auto_renew",
    translation_key="auto_renew",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ZoraxyConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Zoraxy switches."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            *(
                ZoraxyServerSwitch(coordinator, description)
                for description in SERVER_SWITCHES
            ),
            *(
                ZoraxyOptionalSwitch(coordinator, description)
                for description in (*ACCESS_RULE_SWITCHES, *WEBSERVER_SWITCHES)
            ),
            ZoraxyAutoRenewSwitch(coordinator, AUTO_RENEW_DESCRIPTION),
        ]
    )

    known_hosts: set[str] = set()
    known_stream_proxies: set[str] = set()

    @callback
    def _async_add_host_switches() -> None:
        """Add rule switches for newly discovered proxy hosts."""
        new_entities = [
            ZoraxyProxyRuleSwitch(
                coordinator,
                PROXY_RULE_DESCRIPTION,
                host_key,
                on_remove=known_hosts.discard,
            )
            for host_key in coordinator.data.hosts
            if host_key not in known_hosts
        ]
        if new_entities:
            known_hosts.update(entity.host_key for entity in new_entities)
            async_add_entities(new_entities)

    @callback
    def _async_add_stream_proxy_switches() -> None:
        """Add switches for newly discovered stream-proxy rules."""
        new_entities = [
            ZoraxyStreamProxySwitch(
                coordinator,
                STREAM_PROXY_DESCRIPTION,
                proxy_uuid,
                on_remove=known_stream_proxies.discard,
            )
            for proxy_uuid in coordinator.data.stream_proxies
            if proxy_uuid not in known_stream_proxies
        ]
        if new_entities:
            known_stream_proxies.update(entity.proxy_uuid for entity in new_entities)
            async_add_entities(new_entities)

    _async_add_host_switches()
    entry.async_on_unload(coordinator.async_add_listener(_async_add_host_switches))
    _async_add_stream_proxy_switches()
    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_stream_proxy_switches)
    )


class ZoraxyProxyRuleSwitch(ZoraxyHostEntity, SwitchEntity):
    """Enable or disable a single proxy rule."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the proxy rule is enabled."""
        host = self.host
        return host.enabled if host else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose rule details."""
        host = self.host
        if host is None:
            return None
        return {
            "aliases": host.aliases,
            "upstreams": host.upstreams,
            "inactive_upstreams": host.inactive_upstreams,
            "tags": host.tags,
            "uptime_monitor_disabled": host.uptime_monitor_disabled,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the proxy rule."""
        await self._async_set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the proxy rule."""
        await self._async_set_enabled(False)

    async def _async_set_enabled(self, enabled: bool) -> None:
        """Toggle the rule and update the local state optimistically."""
        try:
            await self.coordinator.client.async_set_rule_enabled(
                self.host_key, enabled
            )
        except ZoraxyError as err:
            translation_key = (
                "proxy_rule_enable_failed" if enabled else "proxy_rule_disable_failed"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={
                    "host_key": self.host_key,
                    "error": str(err),
                },
            ) from err
        if (host := self.host) is not None:
            host.enabled = enabled
            self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZoraxyServerSwitch(ZoraxyServerEntity, SwitchEntity):
    """Switch for a global Zoraxy setting."""

    entity_description: ZoraxyServerSwitchDescription

    @property
    def is_on(self) -> bool:
        """Return the state of the setting."""
        return self.entity_description.is_on_fn(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Apply the setting and update the local state optimistically.

        Zoraxy rejects some transitions with an error message (e.g. stopping
        the proxy server in loopback mode, enabling the HTTPS redirect while
        listening on port 80, or enabling port 80 while it is occupied).
        """
        try:
            await self.entity_description.set_fn(self.coordinator.client, value)
        except ZoraxyError as err:
            translation_key = (
                "switch_enable_failed" if value else "switch_disable_failed"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"name": str(self.name), "error": str(err)},
            ) from err
        self.entity_description.apply_local_fn(self.coordinator.data, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZoraxyOptionalSwitch(ZoraxyServerEntity, SwitchEntity):
    """Switch backed by a coordinator sub-object that may be unavailable.

    Used for modules (access control, static web server) that can fail to
    report data independently of the rest of the instance.
    """

    entity_description: ZoraxyOptionalSwitchDescription

    @property
    def available(self) -> bool:
        """Unavailable while the backing module hasn't reported data."""
        root = self.entity_description.get_root_fn(self.coordinator.data)
        return super().available and root is not None

    @property
    def is_on(self) -> bool | None:
        """Return the state of the setting, if known."""
        root = self.entity_description.get_root_fn(self.coordinator.data)
        return self.entity_description.is_on_fn(root) if root is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the setting."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the setting."""
        await self._async_set(False)

    async def _async_set(self, value: bool) -> None:
        """Apply the setting and update the local state optimistically."""
        root = self.entity_description.get_root_fn(self.coordinator.data)
        if root is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="feature_unavailable",
                translation_placeholders={"name": str(self.name)},
            )
        try:
            await self.entity_description.set_fn(self.coordinator.client, root, value)
        except ZoraxyError as err:
            translation_key = (
                "switch_enable_failed" if value else "switch_disable_failed"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"name": str(self.name), "error": str(err)},
            ) from err
        self.entity_description.apply_local_fn(root, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZoraxyStreamProxySwitch(ZoraxyStreamProxyEntity, SwitchEntity):
    """Start or stop a single TCP/UDP stream-proxy rule."""

    @property
    def is_on(self) -> bool | None:
        """Return True if the rule is currently running."""
        proxy = self.proxy
        return proxy.running if proxy else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose rule details."""
        proxy = self.proxy
        if proxy is None:
            return None
        protocols = [
            protocol
            for protocol, used in (("tcp", proxy.use_tcp), ("udp", proxy.use_udp))
            if used
        ]
        return {
            "listening_address": proxy.listening_address,
            "target_address": proxy.target_address,
            "protocols": protocols,
            "logging_enabled": proxy.enable_logging,
            "timeout": proxy.timeout,
            "proxy_protocol_version": proxy.proxy_protocol_version,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the rule."""
        await self._async_set_running(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the rule."""
        await self._async_set_running(False)

    async def _async_set_running(self, running: bool) -> None:
        """Toggle the rule and update the local state optimistically."""
        try:
            await self.coordinator.client.async_set_stream_proxy_running(
                self.proxy_uuid, running
            )
        except ZoraxyError as err:
            translation_key = (
                "switch_enable_failed" if running else "switch_disable_failed"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"name": str(self.name), "error": str(err)},
            ) from err
        if (proxy := self.proxy) is not None:
            proxy.running = running
            self.async_write_ha_state()
        await self.coordinator.async_request_refresh()


class ZoraxyAutoRenewSwitch(ZoraxyServerEntity, SwitchEntity):
    """Enable or disable Zoraxy's built-in ACME certificate auto-renewal."""

    @property
    def available(self) -> bool:
        """Unavailable while Zoraxy hasn't reported the auto-renew state."""
        return (
            super().available
            and self.coordinator.data.auto_renew_enabled is not None
        )

    @property
    def is_on(self) -> bool | None:
        """Return whether auto-renewal is currently enabled."""
        return self.coordinator.data.auto_renew_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-renewal."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-renewal."""
        await self._async_set(False)

    async def _async_set(self, enabled: bool) -> None:
        """Apply the setting and update the local state optimistically.

        Zoraxy rejects enabling this while no ACME e-mail is configured.
        """
        try:
            await self.coordinator.client.async_set_auto_renew_enabled(enabled)
        except ZoraxyError as err:
            translation_key = (
                "switch_enable_failed" if enabled else "switch_disable_failed"
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=translation_key,
                translation_placeholders={"name": str(self.name), "error": str(err)},
            ) from err
        self.coordinator.data.auto_renew_enabled = enabled
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
