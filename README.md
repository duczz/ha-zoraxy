# Zoraxy Custom Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/dynamic/json?url=https://raw.githubusercontent.com/duczz/ha-zoraxy/main/custom_components/zoraxy/manifest.json&query=$.version&label=version)](https://github.com/duczz/ha-zoraxy/releases)
[![Validate](https://github.com/duczz/ha-zoraxy/actions/workflows/validate.yml/badge.svg)](https://github.com/duczz/ha-zoraxy/actions/workflows/validate.yml)
[![License](https://img.shields.io/github/license/duczz/ha-zoraxy)](LICENSE)

[Zoraxy](https://github.com/tobychui/zoraxy) is an open-source reverse proxy and forwarding tool written in Go. This integration connects your Zoraxy instance to Home Assistant so you can monitor the proxy server, watch the health of your upstream services, and enable or disable individual proxy rules — for example from an automation or a dashboard.

After configuring this integration, the following is available:

- A **device for the Zoraxy instance** with the proxy server status, request statistics of the day, proxy rule counters, global switches (force HTTPS redirect, port 80 listener), TLS certificate monitoring with ACME renewal buttons, and CPU/RAM/disk usage of the host machine Zoraxy runs on.
- **Access control** (blacklist/whitelist) switches and counters, and a **static web server** switch, directory-listing toggle and port sensor — all on the Zoraxy instance device.
- A **device per proxy rule (host)** with a switch to enable/disable the rule, the upstream online state and the measured upstream latency from Zoraxy's built-in uptime monitor, and today's request count for that host.
- A **device per stream proxy rule** (TCP/UDP forwarding) with a switch to start/stop it.
- New proxy rules, certificates and stream-proxy rules created in Zoraxy are picked up automatically while the integration is running. A certificate deleted in Zoraxy makes its entities unavailable; a proxy rule or stream-proxy rule deleted in Zoraxy also removes its device automatically, no manual cleanup needed.

## Entities

### Zoraxy instance device

| Entity | Type | Description |
|---|---|---|
| Running | Binary sensor | Whether the reverse proxy server is running |
| Proxy hosts | Sensor | Number of configured proxy rules |
| Active proxy hosts | Sensor | Number of enabled proxy rules |
| Reverse proxy server port | Sensor | Listening port of the reverse proxy server itself — diagnostic, **disabled by default** |
| Requests today | Sensor | Total requests handled today |
| Valid requests today | Sensor | Successfully forwarded requests today |
| Error requests today | Sensor | Failed/invalid requests today |
| Force HTTPS redirect | Switch | Toggles the global HTTP→HTTPS redirect (not available while Zoraxy listens on port 80) |
| Port 80 listener | Switch | Toggles the additional HTTP listener on port 80 |
| Reverse proxy server | Switch | Starts/stops the whole proxy server — **disabled by default**, see below |
| Certificate *domain* expiry | Sensor | Expiry timestamp per TLS certificate (remaining days in the attributes) |
| Certificate *domain* expiring soon | Binary sensor | On when the certificate expires within 30 days |
| Renew certificate *domain* | Button | Requests a new certificate via ACME (same flow as the renew button in the Zoraxy UI) |
| ACME auto-renew | Switch | Toggles Zoraxy's built-in automatic certificate renewal (requires an ACME e-mail configured in Zoraxy) |
| Expired certificates | Sensor | Number of domains Zoraxy currently considers expired (affected domains in the attributes) |
| Blacklist | Switch | Toggles the access-control blacklist |
| Whitelist | Switch | Toggles the access-control whitelist |
| Whitelist allows local/loopback | Switch | Whether local/loopback addresses bypass the whitelist — **disabled by default** |
| Trust proxy headers only | Switch | Whether access control only trusts the client IP from a reverse-proxy header instead of the raw connection — **disabled by default** |
| Blacklisted IPs | Sensor | Number of IPs on the access-control blacklist — diagnostic, **disabled by default** |
| Blacklisted countries | Sensor | Number of countries on the access-control blacklist (country codes and German display names in the attributes) — diagnostic, **disabled by default** |
| Whitelisted IPs | Sensor | Number of IPs on the access-control whitelist — diagnostic, **disabled by default** |
| Whitelisted countries | Sensor | Number of countries on the access-control whitelist (country codes and German display names in the attributes) — diagnostic, **disabled by default** |
| Quick ban candidates | Sensor | Count of distinct client IPs seen today, ranked by request count (top 10 IPs in the attributes) — diagnostic, **disabled by default** |
| Static web server | Switch | Starts/stops Zoraxy's built-in static web server |
| Static web server directory listing | Switch | Toggles directory listing for the static web server — **disabled by default** |
| Static web server port | Sensor | Listening port of the static web server (web root and interface-binding in the attributes) — diagnostic, **disabled by default** |
| Host CPU usage | Sensor | CPU usage of the machine Zoraxy runs on, in % (host OS/architecture/hostname in the attributes) — diagnostic, **disabled by default** |
| Host RAM usage | Sensor | RAM usage of the machine Zoraxy runs on, in % (used/total in the attributes) — diagnostic, **disabled by default** |
| Host disk usage | Sensor | Disk usage of the volume Zoraxy stores its data on, in % (used/total bytes and the path in the attributes) — diagnostic, **disabled by default** |

### Per proxy rule (host) device

| Entity | Type | Description |
|---|---|---|
| Proxy rule | Switch | Enables/disables this proxy rule (same as the toggle in the Zoraxy UI) |
| Upstream online | Binary sensor | Whether at least one upstream of this rule is reachable (per-upstream details in the attributes) |
| Upstream latency | Sensor | Average latency of the online upstreams in ms |
| Requests today | Sensor | Requests handled by this host today. Refreshed on its own, longer cadence than the rest (default every 5 minutes) — see the note below |

> [!NOTE]
> The *Upstream online* and *Upstream latency* entities come from Zoraxy's built-in uptime monitor. They are only created for rules where the uptime monitor is active (it is enabled by default in Zoraxy). Right after a Zoraxy restart it can take a minute until the uptime monitor has produced its first results.

> [!NOTE]
> *Requests today* comes from Zoraxy's full daily-statistics breakdown, a much heavier call than everything else this integration polls. To keep the load on Zoraxy down, it is fetched on its own fixed 5-minute cadence, independent of the configured polling interval — so it can lag a few minutes behind the rest of the entities, and reads `unavailable` for a host until the first fetch after setup completes.

> [!NOTE]
> The certificate renewal button requires the ACME e-mail address to be configured in Zoraxy (*TLS/SSL certificates → ACME settings*), same as renewing from the Zoraxy UI. Renewal can take a while — the button press blocks until Zoraxy finishes the ACME challenge (up to 3 minutes). The *ACME auto-renew* switch has the same e-mail requirement — enabling it without one fails with an error instead of silently doing nothing.

> [!NOTE]
> *Expired certificates* is a different signal than the per-certificate *expiring soon* binary sensor above: it comes from Zoraxy's own renewal check and only goes above zero when a certificate is already expired and hasn't been renewed — for example because auto-renew is off or a renewal attempt failed.

> [!NOTE]
> Despite the name, *Quick ban candidates* is a live ranking derived from today's request statistics — not a list of addresses that are actually banned. Use the `zoraxy.ban_ip` action (see [Actions](#actions)) or Zoraxy's own UI to actually block an address.

> [!NOTE]
> The access-control and static-web-server entities can independently become unavailable if Zoraxy fails to report data for that module, without affecting the rest of the integration.

> [!NOTE]
> The host CPU/RAM/disk usage sensors report `unknown` instead of `0%` right after a Zoraxy restart, until Zoraxy's background sampler has produced its first measurement.

### Per stream proxy rule device

| Entity | Type | Description |
|---|---|---|
| Stream proxy rule | Switch | Starts/stops this TCP/UDP stream-proxy rule (same as the toggle in the Zoraxy UI) |

## Actions

| Action | Description |
|---|---|
| `zoraxy.ban_ip` | Adds an IP address to a Zoraxy instance's access-control blacklist (`config_entry_id`, `ip_address`, optional `comment`). |
| `zoraxy.unban_ip` | Removes an IP address from a Zoraxy instance's access-control blacklist (`config_entry_id`, `ip_address`). |

Both act on the built-in `default` access rule, the same one the *Blacklist* switch and the *Blacklisted IPs* sensor use. They work independently of that switch being on — Zoraxy still keeps the address on the list either way, it just isn't enforced until the blacklist is enabled.

## Supported devices

This integration connects to a **Zoraxy reverse-proxy instance** — not physical hardware, but any host running the Zoraxy server software with its web management interface reachable from Home Assistant (bare metal, VM, Docker container, NAS, etc.).

- Zoraxy **v3.x**, developed and tested against **v3.3.3**; older 3.x versions may work but are untested. See [Known limitations](#known-limitations).
- **Multiple Zoraxy instances** are supported — add each one as a separate integration entry; they are told apart by Zoraxy's own instance UUID, so accidentally adding the same instance twice is blocked.
- The instance can run anywhere reachable over the network from Home Assistant; nothing about this integration requires it to run on the same host.

## Requirements

- Zoraxy **v3.x** with the web management interface reachable from Home Assistant. Developed and tested against Zoraxy **v3.3.3**; older 3.x versions may work but are untested.
- The Zoraxy management account credentials (Zoraxy does not offer API tokens for external clients, so the integration logs in the same way the web UI does).

## Known limitations

- Only Zoraxy **v3.x** is supported; the API of older/newer major versions may differ and has not been tested against.
- Zoraxy has no scoped/read-only API tokens, so the integration always uses full management credentials — there is no way to grant it reduced permissions on the Zoraxy side.
- No automatic discovery: Zoraxy does not broadcast itself on the network (no mDNS/SSDP/DHCP hints), so every instance has to be added manually via host/port.
- *Upstream online* and *Upstream latency* entities only exist for proxy rules where Zoraxy's built-in uptime monitor is active; rules with it disabled won't get these entities.
- The certificate renewal button blocks until Zoraxy finishes the ACME challenge (up to ~3 minutes) — it is not fire-and-forget, and pressing it again while one is already running has no defined behavior.

## Installation

### Installation via HACS (recommended)

Have [HACS](https://hacs.xyz/) installed, this will allow you to update easily.

1. In HACS, open the menu (⋮) → **Custom repositories**.
2. Add `https://github.com/duczz/ha-zoraxy` as a repository of type **Integration**.
3. Search for `Zoraxy` in HACS and click **Download**.
4. Restart Home Assistant.

<details><summary>Manual installation</summary>

1. Copy the `custom_components/zoraxy` folder from the [latest release](https://github.com/duczz/ha-zoraxy/releases/latest) into the `custom_components` folder of your Home Assistant config directory.
2. Restart Home Assistant.

</details>

## Configuration

Add the integration via the UI: **Settings → Devices & Services → Add Integration → Zoraxy**.

| Field | Description | Default |
|---|---|---|
| Host | Hostname or IP of the Zoraxy instance (without `http://`) | — |
| Port | Port of the Zoraxy **management interface** | `8000` |
| Username | Zoraxy management username | — |
| Password | Zoraxy management password | — |
| Uses an SSL certificate | Enable if the management interface is served via HTTPS | off |
| Verify SSL certificate | Disable for self-signed certificates | on |

> [!IMPORTANT]
> Use the port of the Zoraxy **web management interface** (default `8000`), not the port your proxied sites listen on (80/443).

### Options

After setup, the polling interval can be changed via **Settings → Devices & Services → Zoraxy → Configure** (10–3600 seconds, default 30).

## Disabled entities

The **Reverse proxy server** switch (start/stop the whole proxy service) is created disabled, because turning it off takes down *all* services behind Zoraxy at once. To use it:

1. Go to the Zoraxy instance device, section *Switches*.
2. Select the entity, open the settings (gear icon).
3. Enable *Enabled* and wait up to 30 seconds.

> [!WARNING]
> If you access Home Assistant itself through Zoraxy, turning this switch off will also cut your own connection. Zoraxy refuses the shutdown when it detects loopback routing, but don't rely on it — think before you automate this switch.

## How it works

Zoraxy has no API tokens for external clients (its API keys are reserved for the plugin system), so this integration authenticates like a browser: it fetches the CSRF token from the login page, logs in with your credentials and keeps the session cookie. When the session expires, it transparently logs in again. Your credentials are stored in Home Assistant's config entry storage, like with other integrations that use password authentication.

Data is polled from the local management API (`/api/proxy/list`, `/api/proxy/status`, `/api/utm/list`, `/api/stats/summary`, `/api/cert/list`, `/api/info/x`, `/api/access/list`, `/api/quickban/list`, `/api/webserv/status`, `/api/streamprox/config/list`, `/api/stats/system`, `/api/acme/autoRenew/enable`, `/api/acme/listExpiredDomains`); nothing leaves your network. `/api/stats/summary` is called twice with different parameters: a cheap `fast=true` variant every cycle for the instance-wide counters, and the full variant for the per-host breakdown, fetched at most every 5 minutes regardless of the configured polling interval.

## Use cases

- **Certificate expiry alerts.** Get notified in Home Assistant before a TLS certificate managed by Zoraxy expires, instead of finding out from a browser warning — and get alerted if one actually expires despite that, via the *Expired certificates* sensor.
- **Upstream health monitoring.** Surface Zoraxy's own uptime-monitor data as Home Assistant entities, so a self-hosted service going down shows up in your existing alerting/dashboards instead of a separate tool.
- **Scheduled or presence-based access control.** Toggle individual proxy rules, or the access-control blacklist/whitelist, from automations — for example disabling a rule outside working hours, or tightening the whitelist when nobody is home.
- **Emergency lockdown.** Flip the *Reverse proxy server* switch from an automation or script to take every service behind Zoraxy offline at once (see [Disabled entities](#disabled-entities) for the safety note on this one).
- **Ad-hoc IP banning.** Call `zoraxy.ban_ip` from an automation or a dashboard button to add a suspicious address to the blacklist without opening the Zoraxy UI — for example after spotting it in the *Quick ban candidates* attributes.
- **Host resource monitoring.** Alert when the machine running Zoraxy is running low on disk space or under sustained CPU/RAM load, using the same alerting you already have for the rest of your home network.
- **Unified dashboard.** Pull proxy-rule status, certificate expiry and request statistics into a single Lovelace dashboard alongside the rest of your home network monitoring, instead of switching to the separate Zoraxy web UI.

## Automation examples

Notify when a certificate is about to expire:

```yaml
automation:
  - alias: "Notify when a Zoraxy certificate is expiring soon"
    trigger:
      - trigger: state
        entity_id: binary_sensor.example_com_certificate_expiring_soon
        to: "on"
    action:
      - action: notify.notify
        data:
          message: >
            The TLS certificate for {{ state_attr(trigger.entity_id, 'domain') }}
            expires in {{ state_attr(trigger.entity_id, 'remaining_days') }} days.
```

Alert when an upstream goes offline:

```yaml
automation:
  - alias: "Notify when a Zoraxy upstream goes offline"
    trigger:
      - trigger: state
        entity_id: binary_sensor.example_com_upstream_online
        to: "off"
        for:
          minutes: 2
    action:
      - action: notify.notify
        data:
          message: "The upstream behind proxy rule example.com has been offline for 2 minutes."
```

(Replace the entity IDs above with your own — they are derived from your proxy rule domains and certificate filenames.)

Ban an IP address from a script. `config_entry_id` picks the Zoraxy instance from a dropdown when you build this in the UI (**Settings → Automations & Scenes → Scripts**, or **Developer tools → Actions**) — easiest to assemble it there and switch to YAML mode afterwards to see/copy the resolved ID:

```yaml
script:
  ban_suspicious_ip:
    sequence:
      - action: zoraxy.ban_ip
        data:
          config_entry_id: "01234567890abcdef0123456789abcd"
          ip_address: "203.0.113.42"
          comment: "Banned from Home Assistant"
```

Ban today's top *Quick ban candidates* entry with one script call, instead of typing an IP in by hand. There's no per-IP button for this on purpose — the candidates change daily, so a button per IP would mean constantly-churning entities:

```yaml
script:
  ban_top_offender_today:
    sequence:
      - condition: template
        value_template: >
          {{ state_attr('sensor.zoraxy_quick_ban_kandidaten', 'top_ips') | count > 0 }}
      - action: zoraxy.ban_ip
        data:
          config_entry_id: "01234567890abcdef0123456789abcd"
          ip_address: >
            {{ state_attr('sensor.zoraxy_quick_ban_kandidaten', 'top_ips')[0].ip }}
          comment: "Top request count today, banned via script"
```

(Replace the sensor's entity ID with your own — it's derived from your Zoraxy instance's host/IP. `top_ips` is already sorted by request count, so index `[0]` is today's top offender.)

## Dashboard example

An entities card giving an overview of the proxy server and one host, without switching to the Zoraxy web UI:

```yaml
type: entities
title: Zoraxy
entities:
  - entity: binary_sensor.zoraxy_running
  - entity: sensor.zoraxy_active_proxy_hosts
  - entity: sensor.zoraxy_requests_today
  - entity: switch.zoraxy_force_https_redirect
  - type: divider
  - entity: switch.example_com_proxy_rule
  - entity: binary_sensor.example_com_upstream_online
  - entity: sensor.example_com_upstream_latency
  - entity: sensor.example_com_certificate_expiry
```

(Again, replace the entity IDs with your own.)

## Debugging

To enable debug logging, add this to your `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.zoraxy: debug
```

Diagnostics can be downloaded from the integration page (credentials, host and instance UUID are redacted; the proxy rule domains are included, so review before sharing publicly).

## Uninstalling

The integration keeps no state of its own outside the config entry (no separate storage file, no Lovelace resources, no repair/issue registry entries) — removing the config entry cleans up all of its devices and entities automatically.

1. Remove the integration first: **Settings → Devices & Services → Zoraxy → ⋮ → Delete**.
2. Only then remove it via HACS (or delete the `custom_components/zoraxy` folder manually).

Doing it in the other order leaves an orphaned config entry pointing at code that no longer exists, until you remove it manually.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).