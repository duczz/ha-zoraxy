"""Asynchronous API client for the Zoraxy reverse proxy.

Zoraxy (https://github.com/tobychui/zoraxy) does not offer API keys for
external clients (its API-key infrastructure is reserved for plugins), so
this client authenticates the same way the web UI does:

1. ``GET /login.html`` and extract the CSRF token from the
   ``<meta name="zoraxy.csrf.Token">`` tag (this also sets the CSRF cookie).
2. ``POST /api/auth/login`` with the credentials and the ``X-CSRF-Token``
   header, which yields the session cookie.
3. All subsequent POST requests reuse the CSRF token; when the session
   expires Zoraxy redirects to ``login.html`` and the client logs in again.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import aiohttp
from babel import Locale

CSRF_META_RE = re.compile(r'<meta\s+name="zoraxy\.csrf\.Token"\s+content="([^"]+)"')
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Obtaining a certificate via ACME involves a challenge round trip
ACME_TIMEOUT = aiohttp.ClientTimeout(total=180)

_COUNTRY_NAMES_DE = Locale("de").territories


def _country_name(code: str) -> str:
    """German display name for an ISO 3166-1 alpha-2 country code."""
    return _COUNTRY_NAMES_DE.get(code.upper(), code.upper())


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce a raw JSON number to a plain, finite int.

    Zoraxy has been observed to emit bare ``Infinity``/``NaN`` numeric
    literals for some metrics (e.g. an average computed from zero
    samples). Python's ``json`` module happily parses those into
    ``float("inf")``/``float("nan")``, but Home Assistant cannot store
    either as an entity state, so anything non-finite falls back to
    ``default`` instead of propagating into a sensor.
    """
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return int(number)


def _safe_float(value: Any, default: float | None = None) -> float | None:
    """Coerce a raw JSON number to a plain, finite float.

    Same rationale as ``_safe_int``: Zoraxy has been observed to emit bare
    ``Infinity``/``NaN`` numeric literals, which Home Assistant cannot store
    as an entity state.
    """
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


class ZoraxyError(Exception):
    """Base exception for Zoraxy API errors."""


class ZoraxyConnectionError(ZoraxyError):
    """Raised when the Zoraxy instance cannot be reached."""


class ZoraxyAuthError(ZoraxyError):
    """Raised when authentication with Zoraxy fails."""


@dataclass(slots=True)
class ZoraxyInfo:
    """System information reported by /api/info/x."""

    version: str
    node_uuid: str
    development: bool
    boot_time: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyInfo:
        """Build from the raw API payload."""
        return cls(
            version=data.get("Version", ""),
            node_uuid=data.get("NodeUUID", ""),
            development=bool(data.get("Development", False)),
            boot_time=_safe_int(data.get("BootTime")),
        )


@dataclass(slots=True)
class ZoraxyStatus:
    """Runtime state of the reverse proxy server (/api/proxy/status)."""

    running: bool
    port: int | None
    use_tls: bool
    listen_on_port_80: bool
    force_https_redirect: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyStatus:
        """Build from the raw API payload."""
        option = data.get("Option") or {}
        raw_port = option.get("Port")
        return cls(
            running=bool(data.get("Running", False)),
            port=_safe_int(raw_port, default=0) if raw_port is not None else None,
            use_tls=bool(option.get("UseTls", False)),
            listen_on_port_80=bool(option.get("ListenOnPort80", False)),
            force_https_redirect=bool(option.get("ForceHttpsRedirect", False)),
        )


@dataclass(slots=True)
class ZoraxyProxyHost:
    """A single proxy rule from /api/proxy/list?type=host."""

    key: str
    enabled: bool
    aliases: list[str]
    upstreams: list[str]
    inactive_upstreams: list[str]
    tags: list[str]
    uptime_monitor_disabled: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyProxyHost:
        """Build from the raw API payload."""
        return cls(
            key=data.get("RootOrMatchingDomain", ""),
            enabled=not data.get("Disabled", False),
            aliases=data.get("MatchingDomainAlias") or [],
            upstreams=[
                upstream.get("OriginIpOrDomain", "")
                for upstream in data.get("ActiveOrigins") or []
            ],
            inactive_upstreams=[
                upstream.get("OriginIpOrDomain", "")
                for upstream in data.get("InactiveOrigins") or []
            ],
            tags=data.get("Tags") or [],
            uptime_monitor_disabled=bool(data.get("DisableUptimeMonitor", False)),
        )


@dataclass(slots=True)
class ZoraxyUptimeTarget:
    """Latest uptime-monitor record of a target (/api/utm/list)."""

    target_id: str
    name: str
    url: str
    protocol: str
    online: bool
    status_code: int
    latency_ms: int
    timestamp: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyUptimeTarget:
        """Build from the raw API payload."""
        return cls(
            target_id=data.get("ID", ""),
            name=data.get("Name", ""),
            url=data.get("URL", ""),
            protocol=data.get("Protocol", ""),
            online=bool(data.get("Online", False)),
            status_code=_safe_int(data.get("StatusCode")),
            latency_ms=_safe_int(data.get("Latency")),
            timestamp=_safe_int(data.get("Timestamp")),
        )


@dataclass(slots=True)
class ZoraxyCertificate:
    """A TLS certificate from /api/cert/list?date=true."""

    domain: str
    filename: str
    expires_at: datetime | None
    remaining_days: int
    use_dns: bool
    is_fallback: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyCertificate:
        """Build from the raw API payload."""
        expires_at: datetime | None = None
        # x509 NotAfter formatted by Zoraxy as "2006-01-02 15:04:05" in UTC
        raw_expiry = data.get("ExpireDate", "")
        try:
            expires_at = datetime.strptime(raw_expiry, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
        except ValueError:
            pass
        return cls(
            domain=data.get("Domain", ""),
            filename=data.get("Filename", ""),
            expires_at=expires_at,
            remaining_days=_safe_int(data.get("RemainingDays")),
            use_dns=bool(data.get("UseDNS", False)),
            is_fallback=bool(data.get("IsFallback", False)),
        )


@dataclass(slots=True)
class ZoraxyStats:
    """Request counters for the current day (/api/stats/summary)."""

    total_requests: int
    valid_requests: int
    error_requests: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyStats:
        """Build from the raw API payload."""
        return cls(
            total_requests=_safe_int(data.get("TotalRequest")),
            valid_requests=_safe_int(data.get("ValidRequest")),
            error_requests=_safe_int(data.get("ErrorRequest")),
        )


@dataclass(slots=True)
class ZoraxyAccessRule:
    """The global "default" access-control rule (/api/access/list).

    Zoraxy supports multiple named access rules that can be attached to
    individual hosts, but every instance also has a built-in "default"
    rule that gates the instance as a whole; this integration only
    surfaces that one.
    """

    rule_id: str
    name: str
    blacklist_enabled: bool
    whitelist_enabled: bool
    whitelist_allow_local: bool
    trust_proxy_headers_only: bool
    blacklisted_ip_count: int
    blacklisted_countries: list[str]
    whitelisted_ip_count: int
    whitelisted_countries: list[str]

    @property
    def blacklisted_country_count(self) -> int:
        """Number of blacklisted countries (kept for API-shape compatibility)."""
        return len(self.blacklisted_countries)

    @property
    def whitelisted_country_count(self) -> int:
        """Number of whitelisted countries (kept for API-shape compatibility)."""
        return len(self.whitelisted_countries)

    @property
    def blacklisted_country_names(self) -> list[str]:
        """German display names for the blacklisted country codes."""
        return [_country_name(code) for code in self.blacklisted_countries]

    @property
    def whitelisted_country_names(self) -> list[str]:
        """German display names for the whitelisted country codes."""
        return [_country_name(code) for code in self.whitelisted_countries]

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyAccessRule:
        """Build from one entry of the raw API payload."""
        return cls(
            rule_id=data.get("ID", ""),
            name=data.get("Name", ""),
            blacklist_enabled=bool(data.get("BlacklistEnabled", False)),
            whitelist_enabled=bool(data.get("WhitelistEnabled", False)),
            whitelist_allow_local=bool(
                data.get("WhitelistAllowLocalAndLoopback", False)
            ),
            trust_proxy_headers_only=bool(data.get("TrustProxyHeadersOnly", False)),
            blacklisted_ip_count=len(data.get("BlackListIP") or {}),
            # Note: "BlackListContryCode" (missing "u") is a real typo in the
            # Zoraxy API itself, not a typo in this integration.
            blacklisted_countries=sorted(data.get("BlackListContryCode") or {}),
            whitelisted_ip_count=len(data.get("WhiteListIP") or {}),
            whitelisted_countries=sorted(data.get("WhiteListCountryCode") or {}),
        )


@dataclass(slots=True)
class ZoraxyQuickBanEntry:
    """A client IP seen today, ranked by request count (/api/quickban/list).

    Despite the name, this is a live view derived from today's request
    statistics, not a persisted list of actually-banned addresses.
    """

    ip_addr: str
    count: int
    country_code: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyQuickBanEntry:
        """Build from one entry of the raw API payload."""
        return cls(
            ip_addr=data.get("IpAddr", ""),
            count=_safe_int(data.get("Count")),
            country_code=data.get("CountryCode", ""),
        )


@dataclass(slots=True)
class ZoraxySystemResource:
    """CPU/RAM/disk usage of the host running Zoraxy (/api/stats/system)."""

    cpu_usage: float | None
    ram_usage: float | None
    disk_usage: float | None
    used_ram: str
    total_ram: str
    disk_used: int
    disk_total: int
    disk_path: str
    host_os: str
    host_arch: str
    host_name: str
    ready: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxySystemResource:
        """Build from the raw API payload."""
        return cls(
            cpu_usage=_safe_float(data.get("CPUUsage")),
            ram_usage=_safe_float(data.get("RAMUsage")),
            disk_usage=_safe_float(data.get("DiskUsage")),
            used_ram=data.get("UsedRAM", ""),
            total_ram=data.get("TotalRAM", ""),
            disk_used=_safe_int(data.get("DiskUsed")),
            disk_total=_safe_int(data.get("DiskTotal")),
            disk_path=data.get("DiskPath", ""),
            host_os=data.get("HostOS", ""),
            host_arch=data.get("HostArch", ""),
            host_name=data.get("HostName", ""),
            ready=bool(data.get("Ready", False)),
        )


@dataclass(slots=True)
class ZoraxyWebServerStatus:
    """Status of the built-in static web server (/api/webserv/status)."""

    running: bool
    port: int
    directory_listing: bool
    web_root: str
    listen_all_interfaces: bool

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyWebServerStatus:
        """Build from the raw API payload."""
        return cls(
            running=bool(data.get("Running", False)),
            port=_safe_int(data.get("ListeningPort")),
            directory_listing=bool(data.get("EnableDirectoryListing", False)),
            web_root=data.get("WebRoot", ""),
            listen_all_interfaces=not bool(
                data.get("DisableListenToAllInterface", False)
            ),
        )


@dataclass(slots=True)
class ZoraxyStreamProxy:
    """A single TCP/UDP forwarding rule (/api/streamprox/config/list)."""

    uuid: str
    name: str
    running: bool
    listening_address: str
    target_address: str
    use_tcp: bool
    use_udp: bool
    proxy_protocol_version: int
    enable_logging: bool
    timeout: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ZoraxyStreamProxy:
        """Build from the raw API payload."""
        return cls(
            uuid=data.get("UUID", ""),
            name=data.get("Name", ""),
            running=bool(data.get("Running", False)),
            listening_address=data.get("ListeningAddress", ""),
            target_address=data.get("ProxyTargetAddr", ""),
            use_tcp=bool(data.get("UseTCP", False)),
            use_udp=bool(data.get("UseUDP", False)),
            proxy_protocol_version=_safe_int(data.get("ProxyProtocolVersion")),
            enable_logging=bool(data.get("EnableLogging", False)),
            timeout=_safe_int(data.get("Timeout")),
        )


class ZoraxyClient:
    """Minimal async client for the Zoraxy management API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        use_ssl: bool,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client.

        The session must use a cookie jar that accepts cookies for IP
        hosts (``aiohttp.CookieJar(unsafe=True)``), otherwise the Zoraxy
        session cookie is silently dropped for IP-based installations.
        """
        self._session = session
        self._username = username
        self._password = password
        scheme = "https" if use_ssl else "http"
        self.base_url = f"{scheme}://{host}:{port}"
        self._csrf_token: str | None = None
        self._login_lock = asyncio.Lock()

    async def _async_fetch_csrf_token(self) -> str:
        """Fetch a CSRF token from the login page."""
        try:
            resp = await self._session.get(
                f"{self.base_url}/login.html",
                allow_redirects=True,
                timeout=REQUEST_TIMEOUT,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ZoraxyConnectionError(
                f"Error connecting to Zoraxy at {self.base_url}: {err}"
            ) from err
        if resp.status != 200:
            raise ZoraxyConnectionError(
                f"HTTP {resp.status} while loading the Zoraxy login page"
            )
        match = CSRF_META_RE.search(await resp.text())
        if not match:
            raise ZoraxyConnectionError(
                "No CSRF token found in login page; "
                f"is {self.base_url} really a Zoraxy instance?"
            )
        return match.group(1)

    async def async_login(self) -> None:
        """Authenticate and store the CSRF token for later requests."""
        async with self._login_lock:
            token = await self._async_fetch_csrf_token()
            try:
                resp = await self._session.post(
                    f"{self.base_url}/api/auth/login",
                    data={"username": self._username, "password": self._password},
                    headers={"X-CSRF-Token": token},
                    timeout=REQUEST_TIMEOUT,
                )
            except (aiohttp.ClientError, TimeoutError) as err:
                raise ZoraxyConnectionError(
                    f"Error connecting to Zoraxy at {self.base_url}: {err}"
                ) from err
            if resp.status in (401, 403):
                raise ZoraxyAuthError(f"Login rejected with HTTP {resp.status}")
            if resp.status != 200:
                raise ZoraxyConnectionError(
                    f"Unexpected HTTP {resp.status} during login"
                )
            try:
                # Force the lenient stdlib decoder: it accepts the bare
                # Infinity/NaN literals Zoraxy sometimes emits, unlike a
                # strict JSON parser Home Assistant may install as the
                # process-wide default for aiohttp responses.
                payload = await resp.json(content_type=None, loads=json.loads)
            except (aiohttp.ContentTypeError, ValueError) as err:
                raise ZoraxyConnectionError(
                    f"Invalid response from {self.base_url} during login: {err}"
                ) from err
            if payload != "OK":
                # Zoraxy returns HTTP 200 with {"error": "..."} on bad credentials
                message = (
                    payload.get("error", "unknown error")
                    if isinstance(payload, dict)
                    else str(payload)
                )
                raise ZoraxyAuthError(f"Login failed: {message}")
            self._csrf_token = token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = REQUEST_TIMEOUT,
        retry_on_auth: bool = True,
    ) -> Any:
        """Perform an API request, re-logging in once if the session expired."""
        if self._csrf_token is None:
            await self.async_login()
        try:
            resp = await self._session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                data=data,
                headers={"X-CSRF-Token": self._csrf_token or ""},
                allow_redirects=True,
                timeout=timeout,
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise ZoraxyConnectionError(
                f"Error communicating with Zoraxy: {err}"
            ) from err

        # Expired sessions surface as 401/403 or as a redirect to login.html
        if (
            resp.status in (401, 403)
            or "login" in resp.url.path
            or "text/html" in resp.headers.get("Content-Type", "")
        ):
            if not retry_on_auth:
                raise ZoraxyAuthError(
                    f"Not authenticated (HTTP {resp.status} on {path})"
                )
            await self.async_login()
            return await self._request(
                method,
                path,
                params=params,
                data=data,
                timeout=timeout,
                retry_on_auth=False,
            )

        if resp.status != 200:
            raise ZoraxyConnectionError(f"HTTP {resp.status} from {path}")

        try:
            # See the comment in async_login: pin the lenient stdlib
            # decoder so bare Infinity/NaN literals in Zoraxy's response
            # don't raise, regardless of what Home Assistant configures
            # as aiohttp's process-wide default JSON decoder.
            payload = await resp.json(content_type=None, loads=json.loads)
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise ZoraxyConnectionError(f"Invalid response from {path}: {err}") from err
        if isinstance(payload, dict) and set(payload) == {"error"}:
            raise ZoraxyError(str(payload["error"]))
        return payload

    async def async_get_info(self) -> ZoraxyInfo:
        """Return system information."""
        return ZoraxyInfo.from_api(await self._request("GET", "/api/info/x"))

    async def async_get_status(self) -> ZoraxyStatus:
        """Return the reverse proxy server status."""
        return ZoraxyStatus.from_api(await self._request("GET", "/api/proxy/status"))

    async def async_list_proxy_hosts(self) -> dict[str, ZoraxyProxyHost]:
        """Return all proxy rules keyed by their matching domain."""
        payload = await self._request(
            "GET", "/api/proxy/list", params={"type": "host"}
        )
        hosts = [ZoraxyProxyHost.from_api(item) for item in payload or []]
        return {host.key: host for host in hosts if host.key}

    async def async_get_uptime(self) -> dict[str, ZoraxyUptimeTarget]:
        """Return the latest uptime record per monitored target."""
        payload = await self._request("GET", "/api/utm/list")
        result: dict[str, ZoraxyUptimeTarget] = {}
        for target_id, records in (payload or {}).items():
            if records:
                result[target_id] = ZoraxyUptimeTarget.from_api(records[-1])
        return result

    async def async_get_stats(self) -> ZoraxyStats:
        """Return today's request counters."""
        return ZoraxyStats.from_api(
            await self._request("GET", "/api/stats/summary", params={"fast": "true"})
        )

    async def async_get_host_request_counts(self) -> dict[str, int]:
        """Return today's request count per proxy host (downstream hostname).

        Unlike ``async_get_stats``, this fetches the full daily summary
        instead of the ``fast=true`` shortcut, since only the full response
        includes the per-host breakdown. It is a much heavier payload
        (Zoraxy also tallies user agents, referrers, URLs, ...), so callers
        should poll it far less often than the rest of the data.
        """
        payload = await self._request("GET", "/api/stats/summary")
        counts = payload.get("Downstreams") if isinstance(payload, dict) else None
        if not isinstance(counts, dict):
            return {}
        return {str(key): _safe_int(value) for key, value in counts.items()}

    async def async_set_rule_enabled(self, key: str, enabled: bool) -> None:
        """Enable or disable a single proxy rule."""
        await self._request(
            "POST",
            "/api/proxy/toggle",
            data={"ep": key, "enable": "true" if enabled else "false"},
        )

    async def async_set_proxy_running(self, running: bool) -> None:
        """Start or stop the reverse proxy server itself."""
        await self._request(
            "POST",
            "/api/proxy/enable",
            data={"enable": "true" if running else "false"},
        )

    async def async_set_https_redirect(self, enabled: bool) -> None:
        """Enable or disable the forced HTTP-to-HTTPS redirect."""
        await self._request(
            "POST",
            "/api/proxy/useHttpsRedirect",
            data={"set": "true" if enabled else "false"},
        )

    async def async_set_port80_listener(self, enabled: bool) -> None:
        """Enable or disable the port 80 listener."""
        await self._request(
            "POST",
            "/api/proxy/listenPort80",
            data={"enable": "true" if enabled else "false"},
        )

    async def async_list_certificates(self) -> dict[str, ZoraxyCertificate]:
        """Return all TLS certificates keyed by their store filename."""
        payload = await self._request(
            "GET", "/api/cert/list", params={"date": "true"}
        )
        certs = [ZoraxyCertificate.from_api(item) for item in payload or []]
        return {cert.filename: cert for cert in certs if cert.filename}

    async def async_get_acme_email(self) -> str:
        """Return the ACME account e-mail configured in Zoraxy."""
        payload = await self._request("GET", "/api/acme/autoRenew/email")
        return payload if isinstance(payload, str) else ""

    async def async_get_acme_ca(self) -> str:
        """Return the preferred ACME CA configured in Zoraxy."""
        try:
            payload = await self._request("GET", "/api/acme/autoRenew/ca")
        except ZoraxyError:
            return "Let's Encrypt"
        if isinstance(payload, str) and payload:
            return payload
        return "Let's Encrypt"

    async def async_renew_certificate(self, cert: ZoraxyCertificate) -> None:
        """Request a new certificate via ACME (same flow as the Zoraxy UI)."""
        email = await self.async_get_acme_email()
        if not email:
            raise ZoraxyError("ACME e-mail is not configured in Zoraxy")
        ca = await self.async_get_acme_ca()
        await self._request(
            "GET",
            "/api/acme/obtainCert",
            params={
                "domains": cert.domain,
                "filename": cert.filename,
                "email": email,
                "ca": ca,
                "dns": "true" if cert.use_dns else "false",
            },
            timeout=ACME_TIMEOUT,
        )

    async def async_get_auto_renew_enabled(self) -> bool:
        """Return whether Zoraxy's ACME auto-renewal is enabled."""
        payload = await self._request("GET", "/api/acme/autoRenew/enable")
        return bool(payload)

    async def async_set_auto_renew_enabled(self, enabled: bool) -> None:
        """Enable or disable ACME auto-renewal.

        Zoraxy rejects enabling this while no ACME e-mail is configured
        (TLS/SSL certificates -> ACME settings in the Zoraxy UI).
        """
        await self._request(
            "POST",
            "/api/acme/autoRenew/enable",
            data={"enable": "true" if enabled else "false"},
        )

    async def async_list_expired_domains(self) -> list[str]:
        """Return domains whose certificate Zoraxy currently considers expired."""
        payload = await self._request("GET", "/api/acme/listExpiredDomains")
        domains = payload.get("domain") if isinstance(payload, dict) else None
        return [str(domain) for domain in domains if domain] if domains else []

    async def async_get_access_rule(
        self, rule_id: str = "default"
    ) -> ZoraxyAccessRule | None:
        """Return one access-control rule (the built-in "default" rule)."""
        payload = await self._request("GET", "/api/access/list")
        for item in payload or []:
            if isinstance(item, dict) and item.get("ID") == rule_id:
                return ZoraxyAccessRule.from_api(item)
        return None

    async def async_set_blacklist_enabled(
        self, enabled: bool, rule_id: str = "default"
    ) -> None:
        """Enable or disable the blacklist of an access rule."""
        await self._request(
            "POST",
            "/api/blacklist/enable",
            data={"id": rule_id, "enable": "true" if enabled else "false"},
        )

    async def async_set_whitelist_enabled(
        self, enabled: bool, rule_id: str = "default"
    ) -> None:
        """Enable or disable the whitelist of an access rule."""
        await self._request(
            "POST",
            "/api/whitelist/enable",
            data={"id": rule_id, "enable": "true" if enabled else "false"},
        )

    async def async_set_whitelist_allow_local(
        self, enabled: bool, rule_id: str = "default"
    ) -> None:
        """Allow or disallow local/loopback addresses to bypass the whitelist."""
        await self._request(
            "POST",
            "/api/whitelist/allowLocal",
            data={"id": rule_id, "enable": "true" if enabled else "false"},
        )

    async def async_set_trust_proxy_headers_only(
        self, enabled: bool, rule_id: str = "default"
    ) -> None:
        """Restrict client-IP resolution to trusted reverse-proxy headers."""
        await self._request(
            "POST",
            "/api/whitelist/trustProxy",
            data={"id": rule_id, "enable": "true" if enabled else "false"},
        )

    async def async_add_ip_to_blacklist(
        self, ip_address: str, comment: str = "", rule_id: str = "default"
    ) -> None:
        """Add a single IP address to an access rule's blacklist."""
        data = {"id": rule_id, "ip": ip_address}
        if comment:
            data["comment"] = comment
        await self._request("POST", "/api/blacklist/ip/add", data=data)

    async def async_remove_ip_from_blacklist(
        self, ip_address: str, rule_id: str = "default"
    ) -> None:
        """Remove a single IP address from an access rule's blacklist."""
        await self._request(
            "POST",
            "/api/blacklist/ip/remove",
            data={"id": rule_id, "ip": ip_address},
        )

    async def async_list_quickban(self) -> list[ZoraxyQuickBanEntry]:
        """Return today's client IPs ranked by request count."""
        payload = await self._request("GET", "/api/quickban/list")
        return [
            ZoraxyQuickBanEntry.from_api(item)
            for item in payload or []
            if isinstance(item, dict)
        ]

    async def async_get_system_resources(self) -> ZoraxySystemResource:
        """Return CPU/RAM/disk usage of the host running Zoraxy."""
        payload = await self._request("GET", "/api/stats/system")
        return ZoraxySystemResource.from_api(
            payload if isinstance(payload, dict) else {}
        )

    async def async_get_webserver_status(self) -> ZoraxyWebServerStatus:
        """Return the status of the built-in static web server."""
        payload = await self._request("GET", "/api/webserv/status")
        return ZoraxyWebServerStatus.from_api(
            payload if isinstance(payload, dict) else {}
        )

    async def async_set_webserver_running(self, running: bool) -> None:
        """Start or stop the built-in static web server."""
        path = "/api/webserv/start" if running else "/api/webserv/stop"
        await self._request("POST", path)

    async def async_set_webserver_dir_listing(self, enabled: bool) -> None:
        """Enable or disable directory listing on the static web server."""
        await self._request(
            "POST",
            "/api/webserv/setDirList",
            data={"enable": "true" if enabled else "false"},
        )

    async def async_list_stream_proxies(self) -> dict[str, ZoraxyStreamProxy]:
        """Return all TCP/UDP stream-proxy rules keyed by their UUID."""
        payload = await self._request("GET", "/api/streamprox/config/list")
        proxies = [
            ZoraxyStreamProxy.from_api(item)
            for item in payload or []
            if isinstance(item, dict)
        ]
        return {proxy.uuid: proxy for proxy in proxies if proxy.uuid}

    async def async_set_stream_proxy_running(self, uuid: str, running: bool) -> None:
        """Start or stop a single TCP/UDP stream-proxy rule."""
        path = (
            "/api/streamprox/config/start"
            if running
            else "/api/streamprox/config/stop"
        )
        await self._request("POST", path, data={"uuid": uuid})
