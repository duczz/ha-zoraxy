"""Unit tests for the Zoraxy API client's parsing helpers.

Pure logic, no aiohttp/HA involved — covers the dataclass parsing that the
higher-level platform tests exercise only indirectly.
"""

from __future__ import annotations

import math

import pytest

from custom_components.zoraxy.api import (
    CSRF_META_RE,
    ZoraxyAccessRule,
    ZoraxyStatus,
    _safe_int,
)


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        (None, 0, 0),
        (None, 42, 42),
        (5, 0, 5),
        (5.9, 0, 5),
        ("7", 0, 7),
        (math.inf, 0, 0),
        (-math.inf, 0, 0),
        (math.nan, 0, 0),
        ("not-a-number", 0, 0),
        ("not-a-number", -1, -1),
    ],
)
def test_safe_int(value: object, default: int, expected: int) -> None:
    """Bare Infinity/NaN/None/invalid values fall back to the default."""
    assert _safe_int(value, default) == expected


def test_access_rule_handles_zoraxy_country_code_typo() -> None:
    """BlackListContryCode (Zoraxy's own typo) is read correctly, not ignored."""
    rule = ZoraxyAccessRule.from_api(
        {
            "ID": "default",
            "BlackListIP": {"1.2.3.4": True},
            "BlackListContryCode": {"RU": True, "CN": True},
            "WhiteListIP": {},
            "WhiteListCountryCode": {},
        }
    )
    assert rule.blacklisted_ip_count == 1
    assert rule.blacklisted_country_count == 2
    assert rule.blacklisted_countries == ["CN", "RU"]


def test_access_rule_exposes_country_code_lists_not_just_counts() -> None:
    """The actual country codes are kept, not just discarded after counting."""
    rule = ZoraxyAccessRule.from_api(
        {
            "ID": "default",
            "BlackListContryCode": {"RU": True, "CN": True},
            "WhiteListCountryCode": {"DE": True, "AT": True, "CH": True},
        }
    )
    assert rule.blacklisted_countries == ["CN", "RU"]
    assert rule.whitelisted_countries == ["AT", "CH", "DE"]
    assert rule.blacklisted_country_count == 2
    assert rule.whitelisted_country_count == 3


def test_status_port_is_none_when_not_reported() -> None:
    """A missing Option.Port stays None instead of becoming a misleading 0."""
    status = ZoraxyStatus.from_api({"Running": True, "Option": {}})
    assert status.port is None


def test_status_port_parsed_when_present() -> None:
    """A reported port is parsed as an int."""
    status = ZoraxyStatus.from_api({"Running": True, "Option": {"Port": 443}})
    assert status.port == 443


def test_csrf_meta_regex_matches_zoraxy_login_page() -> None:
    """The CSRF token regex matches Zoraxy's actual login.html meta tag."""
    html = (
        "<html><head>"
        '<meta name="zoraxy.csrf.Token" content="abc123-token">'
        "</head></html>"
    )
    match = CSRF_META_RE.search(html)
    assert match is not None
    assert match.group(1) == "abc123-token"


def test_csrf_meta_regex_does_not_match_missing_tag() -> None:
    """A login page without the expected meta tag yields no match."""
    assert CSRF_META_RE.search("<html><head></head></html>") is None
