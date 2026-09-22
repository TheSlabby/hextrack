"""Platform (na1) and regional (americas) routing values and hosts."""

from __future__ import annotations

from typing import Final

#: Platform routing value -> regional routing value (account-v1, match-v5).
PLATFORM_TO_REGION: Final[dict[str, str]] = {
    "na1": "americas",
    "br1": "americas",
    "la1": "americas",
    "la2": "americas",
    "euw1": "europe",
    "eun1": "europe",
    "tr1": "europe",
    "ru": "europe",
    "me1": "europe",
    "kr": "asia",
    "jp1": "asia",
    "oc1": "sea",
    "sg2": "sea",
    "tw2": "sea",
    "vn2": "sea",
}
REGIONS: Final[frozenset[str]] = frozenset(PLATFORM_TO_REGION.values())

#: Short URL names used by the web app (/summoner/na/...) -> platform.
SHORT_TO_PLATFORM: Final[dict[str, str]] = {
    "na": "na1",
    "br": "br1",
    "lan": "la1",
    "las": "la2",
    "euw": "euw1",
    "eune": "eun1",
    "tr": "tr1",
    "ru": "ru",
    "me": "me1",
    "kr": "kr",
    "jp": "jp1",
    "oce": "oc1",
    "sg": "sg2",
    "tw": "tw2",
    "vn": "vn2",
}
PLATFORM_TO_SHORT: Final[dict[str, str]] = {v: k for k, v in SHORT_TO_PLATFORM.items()}


def _check_platform(platform: str) -> str:
    value = platform.strip().lower()
    if value not in PLATFORM_TO_REGION:
        raise ValueError(f"unknown platform {platform!r}")
    return value


def region_for_platform(platform: str) -> str:
    return PLATFORM_TO_REGION[_check_platform(platform)]


def platform_host(platform: str) -> str:
    """``"na1"`` -> ``"https://na1.api.riotgames.com"``."""
    return f"https://{_check_platform(platform)}.api.riotgames.com"


def regional_host(region: str) -> str:
    """``"americas"`` -> ``"https://americas.api.riotgames.com"``."""
    value = region.strip().lower()
    if value not in REGIONS:
        raise ValueError(f"unknown region {region!r}")
    return f"https://{value}.api.riotgames.com"
