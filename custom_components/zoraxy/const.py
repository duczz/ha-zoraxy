"""Constants for the Zoraxy integration."""

from typing import Final

DOMAIN: Final = "zoraxy"

MANUFACTURER: Final = "tobychui"

DEFAULT_PORT: Final = 8000
DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 3600

# Days before expiry at which the certificate binary sensor turns on
CERT_WARNING_DAYS: Final = 30

# Minimum time between per-host request-count fetches (a much heavier
# payload than the rest of the polled data), independent of the
# user-configured scan interval for everything else.
HOST_REQUEST_STATS_INTERVAL: Final = 300

SERVICE_BAN_IP: Final = "ban_ip"
SERVICE_UNBAN_IP: Final = "unban_ip"
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
ATTR_IP_ADDRESS: Final = "ip_address"
ATTR_COMMENT: Final = "comment"
