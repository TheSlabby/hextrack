"""Data Dragon (static game data) helper.

``latest_version`` fetches versions.json lazily, caches it for 6 hours and falls back to the
last known version (or :data:`FALLBACK_VERSION`) when Data Dragon is unreachable. After a
failure the network is not retried for :data:`FAILURE_RETRY_SECONDS`, so an offline machine
does not pay a timeout on every request. ``champion_map`` maps numeric champion id -> Data
Dragon key ("MonkeyKing") for the current version, cached per version.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, Final

import httpx
import orjson

from hextrack import __version__

logger = logging.getLogger(__name__)

CDN: Final = "https://ddragon.leagueoflegends.com/cdn"
VERSIONS_URL: Final = "https://ddragon.leagueoflegends.com/api/versions.json"
#: Used only when versions.json has never been fetched successfully.
FALLBACK_VERSION: Final = "16.18.1"
VERSION_TTL_SECONDS: Final = 6 * 60 * 60
#: After a failed fetch, serve cached/fallback data for this long before trying again.
FAILURE_RETRY_SECONDS: Final = 5 * 60
#: How many versions' champion maps to keep in memory.
CHAMPION_CACHE_VERSIONS: Final = 3
DEFAULT_LOCALE: Final = "en_US"
DEFAULT_TIMEOUT: Final = httpx.Timeout(5.0)

_VERSION_RE: Final = re.compile(r"^\d+\.\d+\.\d+$")


def champion_icon_url(version: str, key: str) -> str:
    """Square champion icon; ``key`` is the Data Dragon key, e.g. "MonkeyKing"."""
    return f"{CDN}/{version}/img/champion/{key}.png"


def champion_splash_url(key: str, skin: int = 0) -> str:
    return f"{CDN}/img/champion/splash/{key}_{skin}.jpg"


def profile_icon_url(version: str, icon_id: int) -> str:
    return f"{CDN}/{version}/img/profileicon/{icon_id}.png"


def item_icon_url(version: str, item_id: int) -> str:
    return f"{CDN}/{version}/img/item/{item_id}.png"


def champion_data_url(version: str, locale: str = DEFAULT_LOCALE) -> str:
    """champion.json (summary data for every champion) for ``version``."""
    return f"{CDN}/{version}/data/{locale}/champion.json"


def pick_latest_version(payload: Any) -> str:
    """First release-style ("16.18.1") entry of a versions.json payload (newest first).

    versions.json ends with legacy entries such as "lolpatch_3.7"; those are skipped.
    Raises ValueError when the payload has no usable version.
    """
    if not isinstance(payload, list):
        raise ValueError("versions.json is not a JSON array")
    for entry in payload:
        if isinstance(entry, str) and _VERSION_RE.match(entry):
            return entry
    raise ValueError("versions.json contains no release version")


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def parse_champion_map(payload: Any) -> dict[int, str]:
    """champion.json -> {numeric id: Data Dragon key}; ValueError on an unexpected shape."""
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data:
        raise ValueError("champion.json has no 'data' object")
    mapping: dict[int, str] = {}
    try:
        for name, entry in data.items():
            key = entry.get("id", name)
            if not isinstance(key, str) or not key:
                raise ValueError(f"champion {name!r} has no id")
            mapping[int(entry["key"])] = key
    except (AttributeError, KeyError, TypeError) as exc:
        raise ValueError(f"malformed champion.json entry: {exc}") from exc
    return mapping


class DDragon:
    """Cached Data Dragon lookups.

    Pass ``http`` to share an existing AsyncClient (it is not closed by :meth:`aclose`);
    otherwise one is created on first use (with ``transport`` if given, for tests) and owned.
    ``clock`` must be monotonic.
    """

    CDN: Final = CDN

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        version_ttl_seconds: float = VERSION_TTL_SECONDS,
        failure_retry_seconds: float = FAILURE_RETRY_SECONDS,
        locale: str = DEFAULT_LOCALE,
    ) -> None:
        self._http = http
        self._owns_http = http is None
        self._transport = transport
        self._clock = clock
        self._version_ttl = float(version_ttl_seconds)
        self._failure_retry = float(failure_retry_seconds)
        self._locale = locale

        self._version: str | None = None
        self._version_fetched_at: float | None = None
        self._version_failed_at: float | None = None
        self._version_lock = asyncio.Lock()

        self._champions: OrderedDict[str, dict[int, str]] = OrderedDict()
        self._champions_failed_at: dict[str, float] = {}
        self._champions_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Close the HTTP client if this instance created it."""
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def current_version(self) -> str:
        """Last fetched version (or :data:`FALLBACK_VERSION`) without touching the network."""
        return self._version or FALLBACK_VERSION

    async def latest_version(self) -> str:
        """Newest patch version (e.g. "16.18.1"); cached, offline-safe."""
        if self._version_fresh():
            return self.current_version
        async with self._version_lock:
            # Another coroutine may have refreshed (or failed) while we waited.
            if self._version_fresh() or self._recently_failed(self._version_failed_at):
                return self.current_version
            try:
                version = pick_latest_version(await self._fetch_json(VERSIONS_URL))
            except (httpx.HTTPError, ValueError) as exc:
                self._version_failed_at = self._clock()
                logger.warning(
                    "Data Dragon versions.json unavailable (%s: %s); using %s",
                    type(exc).__name__,
                    exc,
                    self.current_version,
                )
                return self.current_version
            if version != self._version:
                logger.info("Data Dragon version %s", version)
            self._version = version
            self._version_fetched_at = self._clock()
            self._version_failed_at = None
            return version

    async def champion_map(self) -> dict[int, str]:
        """champion id -> Data Dragon key for the latest version (cached per version).

        When champion.json cannot be fetched, the newest cached map is returned, or ``{}``
        if none was ever loaded.
        """
        version = await self.latest_version()
        cached = self._cached_champions(version)
        if cached is not None:
            return cached
        async with self._champions_lock:
            cached = self._cached_champions(version)
            if cached is not None:
                return cached
            if self._recently_failed(self._champions_failed_at.get(version)):
                return self._fallback_champions()
            try:
                mapping = parse_champion_map(
                    await self._fetch_json(champion_data_url(version, self._locale))
                )
            except (httpx.HTTPError, ValueError) as exc:
                self._champions_failed_at[version] = self._clock()
                logger.warning(
                    "Data Dragon champion.json %s unavailable (%s: %s)",
                    version,
                    type(exc).__name__,
                    exc,
                )
                return self._fallback_champions()
            self._champions_failed_at.pop(version, None)
            self._champions[version] = mapping
            self._champions.move_to_end(version)
            while len(self._champions) > CHAMPION_CACHE_VERSIONS:
                self._champions.popitem(last=False)
            return dict(mapping)

    async def champion_key(self, champion_id: int) -> str | None:
        """Data Dragon key for one champion id, or None if unknown."""
        return (await self.champion_map()).get(champion_id)

    # URL helpers (instance forms of the module functions)
    champion_icon_url = staticmethod(champion_icon_url)
    champion_splash_url = staticmethod(champion_splash_url)
    profile_icon_url = staticmethod(profile_icon_url)
    item_icon_url = staticmethod(item_icon_url)
    champion_data_url = staticmethod(champion_data_url)

    # --- internals ------------------------------------------------------------------------
    def _version_fresh(self) -> bool:
        return (
            self._version is not None
            and self._version_fetched_at is not None
            and self._clock() - self._version_fetched_at < self._version_ttl
        )

    def _recently_failed(self, failed_at: float | None) -> bool:
        return failed_at is not None and self._clock() - failed_at < self._failure_retry

    def _cached_champions(self, version: str) -> dict[int, str] | None:
        mapping = self._champions.get(version)
        if mapping is None:
            return None
        self._champions.move_to_end(version)
        return dict(mapping)

    def _fallback_champions(self) -> dict[int, str]:
        if not self._champions:
            return {}
        newest = max(self._champions, key=_version_key)
        return dict(self._champions[newest])

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                transport=self._transport,
                timeout=DEFAULT_TIMEOUT,
                follow_redirects=True,
                headers={"User-Agent": f"HexTrack/{__version__}"},
            )
            self._owns_http = True
        return self._http

    async def _fetch_json(self, url: str) -> Any:
        response = await self._client().get(url)
        response.raise_for_status()
        return orjson.loads(response.content)
