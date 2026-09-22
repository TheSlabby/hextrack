"""Exceptions raised by :mod:`hextrack.riot`. The API maps them to HTTP responses."""

from __future__ import annotations


class RiotError(Exception):
    """Base class for every Riot API failure."""

    def __init__(self, message: str = "", *, status: int | None = None, url: str | None = None):
        super().__init__(message or self.__class__.__name__)
        self.message = message or self.__class__.__name__
        self.status = status
        self.url = url

    def __str__(self) -> str:
        return self.message


class RiotKeyMissing(RiotError):
    """``RIOT_API_KEY`` is not configured; no request was made."""

    def __init__(self, message: str = "Riot API key is not configured") -> None:
        super().__init__(message)


class RiotForbidden(RiotError):
    """401/403: the key is invalid or expired (dev keys expire every 24h)."""


class RiotNotFound(RiotError):
    """404: account, summoner or match does not exist."""


class RiotRateLimited(RiotError):
    """429 that survived the client's own retry. ``retry_after`` is in seconds."""

    def __init__(
        self,
        message: str = "Riot API rate limit exceeded",
        *,
        retry_after: float = 1.0,
        status: int | None = 429,
        url: str | None = None,
    ) -> None:
        super().__init__(message, status=status, url=url)
        self.retry_after = max(float(retry_after), 0.0)


class RiotUnavailable(RiotError):
    """5xx or a network/timeout error after retries."""


class RiotBadResponse(RiotError):
    """A 2xx response whose body failed validation (wrong shape, not JSON, ...)."""
