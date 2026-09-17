"""Diagnostics support for the Zoraxy integration."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import ZoraxyConfigEntry

TO_REDACT = {CONF_HOST, CONF_PASSWORD, CONF_USERNAME, "node_uuid"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ZoraxyConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "info": async_redact_data(asdict(data.info), TO_REDACT),
        "status": asdict(data.status),
        "hosts": [asdict(host) for host in data.hosts.values()],
        "uptime": {
            target_id: asdict(target) for target_id, target in data.uptime.items()
        },
        "stats": asdict(data.stats) if data.stats else None,
        "certs": [asdict(cert) for cert in data.certs.values()],
        "access_rule": asdict(data.access_rule) if data.access_rule else None,
        "quickban": [asdict(entry) for entry in data.quickban],
        "webserver": asdict(data.webserver) if data.webserver else None,
        "stream_proxies": [asdict(proxy) for proxy in data.stream_proxies.values()],
    }
