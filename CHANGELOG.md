# Changelog

## [0.1.0] - 2026-09-16

Initial release, developed and tested against Zoraxy v3.3.3.

### Added

- Config flow with connection test, re-authentication, reconfigure and options flow (polling interval).
- Zoraxy instance device: running state, proxy-host counters, request statistics, reverse-proxy-server port, global switches (force HTTPS redirect, port 80 listener, reverse-proxy-server start/stop — disabled by default, see README), TLS certificate monitoring with ACME renewal buttons.
- Access control: blacklist/whitelist switches, whitelist local/loopback bypass, trust-proxy-headers-only, diagnostic counters for blacklisted/whitelisted IPs and countries (the actual country codes in the attributes), and a quick-ban candidates sensor.
- `zoraxy.ban_ip` / `zoraxy.unban_ip` actions to add or remove a single IP address from an access rule's blacklist directly from Home Assistant — gives the *Quick ban candidates* sensor something to act on instead of just displaying a ranking.
- Static web server: start/stop switch, directory-listing switch, configured-port sensor.
- One device per proxy rule (host): enable/disable switch (aliases/upstreams/tags in the attributes), upstream-online binary sensor, upstream-latency sensor from Zoraxy's built-in uptime monitor, and a "Requests today" sensor from Zoraxy's daily-statistics breakdown (fetched on its own 5-minute cadence — see README).
- One device per TCP/UDP stream-proxy rule: start/stop switch. Proxy-host and stream-proxy-rule devices are created and removed automatically as rules change in Zoraxy.
- ACME auto-renew switch and an expired-certificates sensor, using Zoraxy's built-in auto-renewal subsystem instead of only the blocking manual renew button.
- Host CPU/RAM/disk usage sensors (diagnostic, disabled by default) for the machine Zoraxy runs on, from Zoraxy's own system-resource endpoint.
- Diagnostics download with redacted credentials.
- English and German translations, brand icon (light/dark).
- Handles malformed/non-JSON API responses and bare `Infinity`/`NaN` values from Zoraxy gracefully instead of crashing.
- Access-control and static-web-server data is fetched defensively, so either module failing to report doesn't affect the rest of the integration — their entities become unavailable instead.
- CI runs ruff, mypy (lightweight and a strict pass against real Home Assistant types), an automated test suite (96% coverage), plus hassfest/HACS validation.
