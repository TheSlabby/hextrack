"""Async Riot API client.

Contract (other modules depend on exactly this surface):

* ``RiotClient(settings, transport=None)``: ``transport`` lets tests inject
  ``httpx.MockTransport`` / respx. Requests carry ``X-Riot-Token`` (the key never appears in
  a URL); path segments are URL-quoted (spaces, unicode, "#" and "/" in names).
* Account and match calls use the regional host (``settings.riot_region``); summoner and
  league calls use the platform host (``settings.riot_platform``).
* Every request waits on the rate limiter of its routing value: application limits from
  ``settings.app_rate_limits`` (overridable with ``app_limits``) plus per-method limits, both
  updated from the ``X-App-Rate-Limit`` / ``X-Method-Rate-Limit`` response headers
  (:mod:`hextrack.riot.ratelimit`).
* ``max_wait`` bounds how long a request may sit in the limiter: when the estimated wait is
  longer, :class:`RiotRateLimited` is raised straight away (and 429s are not retried inside
  the call). The API process sets it so a request never parks for minutes behind the worker;
  the worker leaves it unset and queues. ``budget`` adds a second, smaller allowance per
  routing value that never waits: it caps what one process (the public on-demand endpoints)
  may take out of the shared key.
* A 429 blocks the limiter for ``Retry-After`` (+ jitter) and is retried up to
  :data:`MAX_RATE_LIMIT_RETRIES` times, then raises :class:`RiotRateLimited` (immediately
  when the requested pause exceeds :data:`MAX_RETRY_AFTER_WAIT_SECONDS`). 5xx and
  network errors are retried with exponential backoff (tenacity, :data:`MAX_ATTEMPTS`
  attempts), then raise :class:`RiotUnavailable`. 401/403 raise :class:`RiotForbidden` and
  set ``status.key_ok = False``. 404 raises :class:`RiotNotFound`. A 2xx body that is not
  JSON or fails DTO validation raises :class:`RiotBadResponse`. With no key configured every
  call raises :class:`RiotKeyMissing` without touching the network.
* Error bodies are never returned as data.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Final, Literal, Self
from urllib.parse import quote

import httpx
import orjson
from pydantic import BaseModel, TypeAdapter, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)

from hextrack import __version__
from hextrack.config import Settings
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)
from hextrack.riot.ratelimit import DEFAULT_MARGIN_SECONDS, Clock, RateLimiter, Sleep
from hextrack.riot.routing import platform_host, region_for_platform, regional_host
from hextrack.riot.schemas import AccountDto, LeagueEntryDto, MatchDto, SummonerDto

logger = logging.getLogger(__name__)

#: 429 retries after the first attempt (so at most 3 requests per call).
MAX_RATE_LIMIT_RETRIES: Final = 2
#: Total attempts for 5xx / network errors.
MAX_ATTEMPTS: Final = 3
#: Exponential backoff for 5xx / network errors: 0.5 s, 1 s, ... capped at 8 s, plus jitter.
BACKOFF_MULTIPLIER: Final = 0.5
BACKOFF_MAX_SECONDS: Final = 8.0
BACKOFF_JITTER_SECONDS: Final = 0.25
#: Jitter added to ``Retry-After`` so concurrent clients do not retry in lockstep.
RETRY_AFTER_JITTER: Final = (0.05, 0.5)
#: Used when a 429 has no usable ``Retry-After`` (Riot omits it for service limits);
#: doubled on each further 429 of the same call.
DEFAULT_RETRY_AFTER_SECONDS: Final = 1.0
#: A 429 asking for a longer pause than this is raised at once (the limiter stays blocked)
#: instead of parking the caller, e.g. an API request, for minutes.
MAX_RETRY_AFTER_WAIT_SECONDS: Final = 60.0
DEFAULT_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)
DEFAULT_LIMITS: Final = httpx.Limits(
    max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0
)
USER_AGENT: Final = f"HexTrack/{__version__}"
#: Riot's match-v5 ``count`` bounds.
MATCH_IDS_MAX_COUNT: Final = 100
MATCH_ID_TYPES: Final = frozenset({"ranked", "normal", "tourney", "tutorial"})

Routing = Literal["platform", "regional"]

#: Client method name (the rate limiter's method key) -> routing kind.
METHOD_ROUTING: Final[Mapping[str, Routing]] = {
    "account_by_riot_id": "regional",
    "account_by_puuid": "regional",
    "summoner_by_puuid": "platform",
    "league_entries_by_puuid": "platform",
    "match_ids_by_puuid": "regional",
    "match": "regional",
}

_LEAGUE_ENTRIES: Final = TypeAdapter(list[LeagueEntryDto])
_MATCH_IDS: Final = TypeAdapter(list[str])


@dataclass(slots=True)
class RiotStatus:
    """Health snapshot surfaced by ``GET /api/v1/health``."""

    key_configured: bool
    #: None until the first authenticated response; False after a 401/403.
    key_ok: bool | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    #: When Riot last accepted the key in this process (None until the first response).
    last_ok_at: datetime | None = None


class _ServerError(Exception):
    """Internal: a 5xx response, raised so tenacity retries it."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"HTTP {response.status_code}")
        self.status = response.status_code
        self.detail = _riot_message(response)


def _segment(value: str) -> str:
    """Quote one path segment; an empty segment would silently hit a different endpoint."""
    if not value:
        raise ValueError("Riot API path segments must not be empty")
    return quote(value, safe="")


def _riot_message(response: httpx.Response) -> str:
    """Riot error bodies look like ``{"status": {"message": ..., "status_code": ...}}``."""
    try:
        body = orjson.loads(response.content)
    except ValueError:
        body = None
    if isinstance(body, dict):
        status = body.get("status")
        message = status.get("message") if isinstance(status, dict) else None
        if isinstance(message, str) and message:
            return message
    return response.reason_phrase or f"HTTP {response.status_code}"


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        return None
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _epoch_seconds(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp())


class RiotClient:
    """Rate-limited async client for account-v1, summoner-v4, league-v4 and match-v5.

    ``app_limits`` overrides ``settings.app_rate_limits`` (the worker reserves the on-demand
    share that way), ``max_wait`` makes requests fail fast instead of queuing and ``budget``
    caps this client's own share of the key (see the module docstring).

    Optional keyword arguments exist for tests and tuning: ``clock``/``sleep`` drive the rate
    limiter and every retry delay, ``rng`` supplies jitter, ``timeout`` overrides
    :data:`DEFAULT_TIMEOUT` and ``rate_limit_margin`` the limiter's safety margin.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        timeout: httpx.Timeout | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        rng: random.Random | None = None,
        rate_limit_margin: float = DEFAULT_MARGIN_SECONDS,
        app_limits: Sequence[tuple[int, float]] | None = None,
        max_wait: float | None = None,
        budget: Sequence[tuple[int, float]] | None = None,
    ) -> None:
        self.settings = settings
        self._transport = transport
        self._status = RiotStatus(key_configured=settings.riot_key_configured)
        self._timeout = timeout or DEFAULT_TIMEOUT
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._http: httpx.AsyncClient | None = None
        self._closed = False
        self._max_wait = float(max_wait) if max_wait is not None else None

        self.platform = settings.riot_platform
        self.region = settings.riot_region
        self._hosts: dict[Routing, str] = {
            "platform": platform_host(self.platform),
            "regional": regional_host(self.region),
        }
        expected_region = region_for_platform(self.platform)
        if expected_region != self.region:
            logger.warning(
                "RIOT_REGION=%s does not match RIOT_PLATFORM=%s (expected %s); match-v5 "
                "lookups for %s games will fail",
                self.region,
                self.platform,
                expected_region,
                self.platform,
            )
        limits = list(app_limits) if app_limits is not None else settings.app_rate_limits
        self._limiters: dict[Routing, RateLimiter] = {
            routing: RateLimiter(
                limits,
                name=self._routing_value(routing),
                clock=clock,
                sleep=sleep,
                margin=rate_limit_margin,
            )
            for routing in ("platform", "regional")
        }
        self._budgets: dict[Routing, RateLimiter] = {}
        if budget:
            self._budgets = {
                routing: RateLimiter(
                    budget,
                    name=f"{self._routing_value(routing)} budget",
                    clock=clock,
                    sleep=sleep,
                    margin=rate_limit_margin,
                )
                for routing in ("platform", "regional")
            }

    # --- lifecycle ------------------------------------------------------------------------
    async def aclose(self) -> None:
        """Close the underlying HTTP client. Safe to call more than once."""
        self._closed = True
        http, self._http = self._http, None
        if http is not None:
            await http.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    @property
    def status(self) -> RiotStatus:
        return self._status

    @property
    def closed(self) -> bool:
        return self._closed

    def rate_limiter(self, routing: Routing) -> RateLimiter:
        """The limiter for the platform or regional routing value (for diagnostics)."""
        return self._limiters[routing]

    def limiter_wait_estimate(self, method: str | None = None) -> float:
        """Seconds until the next request could be sent without waiting (0.0 if now).

        Counts requests already queued in the limiter. With ``method`` (a client method name
        such as ``"match"``) the estimate covers that method's routing value and method
        limits; without it, the worst of both routing values' application limits.
        """
        if method is not None:
            try:
                routing = METHOD_ROUTING[method]
            except KeyError:
                raise ValueError(f"unknown Riot client method {method!r}") from None
            return self._limiters[routing].wait_estimate(method)
        return max(limiter.wait_estimate() for limiter in self._limiters.values())

    # --- account-v1 (regional) ------------------------------------------------------------
    async def account_by_riot_id(self, game_name: str, tag_line: str) -> AccountDto:
        """GET /riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}."""
        path = f"/riot/account/v1/accounts/by-riot-id/{_segment(game_name)}/{_segment(tag_line)}"
        data = await self._get("account_by_riot_id", path)
        return self._validate(AccountDto, data, "account_by_riot_id")

    async def account_by_puuid(self, puuid: str) -> AccountDto:
        """GET /riot/account/v1/accounts/by-puuid/{puuid}."""
        data = await self._get(
            "account_by_puuid", f"/riot/account/v1/accounts/by-puuid/{_segment(puuid)}"
        )
        return self._validate(AccountDto, data, "account_by_puuid")

    # --- summoner-v4 / league-v4 (platform) -----------------------------------------------
    async def summoner_by_puuid(self, puuid: str) -> SummonerDto:
        """GET /lol/summoner/v4/summoners/by-puuid/{puuid}."""
        data = await self._get(
            "summoner_by_puuid", f"/lol/summoner/v4/summoners/by-puuid/{_segment(puuid)}"
        )
        return self._validate(SummonerDto, data, "summoner_by_puuid")

    async def league_entries_by_puuid(self, puuid: str) -> list[LeagueEntryDto]:
        """GET /lol/league/v4/entries/by-puuid/{puuid} (empty list when unranked)."""
        data = await self._get(
            "league_entries_by_puuid", f"/lol/league/v4/entries/by-puuid/{_segment(puuid)}"
        )
        return self._validate_adapter(_LEAGUE_ENTRIES, data, "league_entries_by_puuid")

    # --- match-v5 (regional) --------------------------------------------------------------
    async def match_ids_by_puuid(
        self,
        puuid: str,
        *,
        start: int = 0,
        count: int = 20,
        queue: int | None = None,
        type_: str | None = "ranked",
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[str]:
        """GET /lol/match/v5/matches/by-puuid/{puuid}/ids, newest first.

        ``start_time`` / ``end_time`` are sent as epoch seconds (``startTime`` / ``endTime``;
        naive datetimes are taken as UTC); ``type_`` as ``type`` (None sends no filter).
        ``count`` is clamped to 1..100 and ``start`` to >= 0.
        """
        if type_ is not None and type_ not in MATCH_ID_TYPES:
            raise ValueError(f"type_ must be one of {sorted(MATCH_ID_TYPES)} or None")
        params: dict[str, str | int] = {
            "start": max(int(start), 0),
            "count": min(max(int(count), 1), MATCH_IDS_MAX_COUNT),
        }
        if queue is not None:
            params["queue"] = int(queue)
        if type_ is not None:
            params["type"] = type_
        if start_time is not None:
            params["startTime"] = _epoch_seconds(start_time)
        if end_time is not None:
            params["endTime"] = _epoch_seconds(end_time)
        data = await self._get(
            "match_ids_by_puuid",
            f"/lol/match/v5/matches/by-puuid/{_segment(puuid)}/ids",
            params=params,
        )
        return self._validate_adapter(_MATCH_IDS, data, "match_ids_by_puuid")

    async def match(self, match_id: str) -> dict[str, Any]:
        """GET /lol/match/v5/matches/{matchId} as raw JSON.

        The body is validated against :class:`hextrack.riot.schemas.MatchDto` (and its
        ``metadata.matchId`` must be the requested id) before being returned; otherwise
        :class:`RiotBadResponse` is raised. The original dict is returned unmodified so it
        can be stored in ``matches.raw``.
        """
        data = await self._get("match", f"/lol/match/v5/matches/{_segment(match_id)}")
        if not isinstance(data, dict):
            raise self._bad_response("match", "match body is not a JSON object")
        dto = self._validate(MatchDto, data, "match")
        if dto.metadata.match_id.casefold() != match_id.casefold():
            raise self._bad_response(
                "match", f"asked for match {match_id} but Riot returned {dto.metadata.match_id}"
            )
        return data

    # --- request pipeline -----------------------------------------------------------------
    def _routing_value(self, routing: Routing) -> str:
        return self.platform if routing == "platform" else self.region

    def _client(self) -> httpx.AsyncClient:
        if self._closed:
            raise RuntimeError("RiotClient is closed")
        if self._http is None:
            assert self.settings.riot_api_key is not None
            self._http = httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                limits=DEFAULT_LIMITS,
                follow_redirects=False,
                headers={
                    "X-Riot-Token": self.settings.riot_api_key,
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
            )
        return self._http

    async def _get(
        self, method: str, path: str, *, params: Mapping[str, str | int] | None = None
    ) -> Any:
        """Send a GET through limiter + retries and return the decoded 2xx JSON body."""
        if self._closed:
            raise RuntimeError("RiotClient is closed")
        if self.settings.riot_api_key is None:
            raise RiotKeyMissing()
        routing = METHOD_ROUTING[method]
        limiter = self._limiters[routing]
        url = self._hosts[routing] + path
        rate_limited = 0
        while True:
            response = await self._send_with_retries(limiter, routing, method, url, params)
            if response.status_code != 429:
                return self._decode(response, method, url)

            header_delay = _parse_retry_after(response.headers.get("Retry-After"))
            base = (
                header_delay
                if header_delay is not None
                else DEFAULT_RETRY_AFTER_SECONDS * (2**rate_limited)
            )
            delay = base + self._rng.uniform(*RETRY_AFTER_JITTER)
            limit_type = response.headers.get("X-Rate-Limit-Type")
            limiter.penalize(method, delay, limit_type)
            # With max_wait set (the API process) the caller is a waiting HTTP request:
            # report the 429 instead of retrying it behind the same block.
            if (
                self._max_wait is not None
                or rate_limited >= MAX_RATE_LIMIT_RETRIES
                or delay > MAX_RETRY_AFTER_WAIT_SECONDS
            ):
                logger.warning(
                    "Riot 429 on %s (X-Rate-Limit-Type=%s, Retry-After=%s); giving up after "
                    "%d retries",
                    method,
                    limit_type or "none",
                    response.headers.get("Retry-After", "none"),
                    rate_limited,
                )
                error = RiotRateLimited(
                    f"Riot API rate limit exceeded ({limit_type or 'service'} limit on {method})",
                    retry_after=delay,
                    url=url,
                )
                self._record_error(error)
                raise error
            rate_limited += 1
            logger.warning(
                "Riot 429 on %s (X-Rate-Limit-Type=%s, Retry-After=%s); retrying in %.2fs (%d/%d)",
                method,
                limit_type or "none",
                response.headers.get("Retry-After", "none"),
                delay,
                rate_limited,
                MAX_RATE_LIMIT_RETRIES,
            )

    async def _send_with_retries(
        self,
        limiter: RateLimiter,
        routing: Routing,
        method: str,
        url: str,
        params: Mapping[str, str | int] | None,
    ) -> httpx.Response:
        """One logical request: up to :data:`MAX_ATTEMPTS` sends on 5xx / network errors."""
        retrying = AsyncRetrying(
            stop=stop_after_attempt(MAX_ATTEMPTS),
            wait=wait_exponential(multiplier=BACKOFF_MULTIPLIER, max=BACKOFF_MAX_SECONDS)
            + wait_random(0, BACKOFF_JITTER_SECONDS),
            retry=retry_if_exception_type((httpx.RequestError, _ServerError)),
            sleep=self._sleep,
            before_sleep=self._log_retry(method),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._send_once(limiter, routing, method, url, params)
        except _ServerError as exc:
            error: RiotError = RiotUnavailable(
                f"Riot API unavailable: HTTP {exc.status} {exc.detail} on {method} "
                f"after {MAX_ATTEMPTS} attempts",
                status=exc.status,
                url=url,
            )
            self._record_error(error)
            raise error from exc
        except httpx.RequestError as exc:
            error = RiotUnavailable(
                f"Riot API unreachable: {type(exc).__name__}: {exc} on {method} "
                f"after {MAX_ATTEMPTS} attempts",
                url=url,
            )
            self._record_error(error)
            raise error from exc
        raise AssertionError("unreachable: tenacity either returns or raises")

    async def _send_once(
        self,
        limiter: RateLimiter,
        routing: Routing,
        method: str,
        url: str,
        params: Mapping[str, str | int] | None,
    ) -> httpx.Response:
        self._check_budget(routing, method, url)
        if self._max_wait is not None:
            estimate = limiter.wait_estimate(method)
            if estimate > self._max_wait:
                raise self._too_busy(
                    f"Riot API rate limit reached ({limiter.name}); retry in {estimate:.0f}s",
                    estimate,
                    url,
                )
        budget = self._budgets.get(routing)
        if budget is not None:
            await budget.acquire(method)
        _sent_at, granted = await limiter.reserve(method)
        response = await self._client().get(url, params=params)
        limiter.update_from_headers(
            method,
            response.headers,
            sent_at=granted,
            # A 429 reports a full window; penalize() models the block from Retry-After.
            sync_counts=response.status_code != 429,
        )
        if response.status_code >= 500:
            raise _ServerError(response)
        return response

    def _check_budget(self, routing: Routing, method: str, url: str) -> None:
        """Fail fast when this client's own share of the key is used up."""
        budget = self._budgets.get(routing)
        if budget is None:
            return
        estimate = budget.wait_estimate()
        if estimate > 0.0:
            raise self._too_busy(
                f"HexTrack's Riot request budget for {budget.name.removesuffix(' budget')} "
                f"is used up; retry in {estimate:.0f}s",
                estimate,
                url,
            )

    def _too_busy(self, message: str, retry_after: float, url: str) -> RiotRateLimited:
        """Local throttling: the request was never sent, so it is not a Riot-side error."""
        logger.info("%s", message)
        return RiotRateLimited(message, retry_after=max(retry_after, 1.0), url=url)

    @staticmethod
    def _log_retry(method: str) -> Callable[[RetryCallState], None]:
        def before_sleep(state: RetryCallState) -> None:
            exc = state.outcome.exception() if state.outcome is not None else None
            delay = state.next_action.sleep if state.next_action is not None else 0.0
            logger.warning(
                "Riot request %s failed (%s); attempt %d/%d, retrying in %.2fs",
                method,
                exc,
                state.attempt_number,
                MAX_ATTEMPTS,
                delay,
            )

        return before_sleep

    def _decode(self, response: httpx.Response, method: str, url: str) -> Any:
        status = response.status_code
        if 200 <= status < 300:
            self._accepted()
            try:
                return orjson.loads(response.content)
            except ValueError as exc:
                raise self._bad_response(method, f"body is not valid JSON ({exc})") from exc
        message = _riot_message(response)
        if status in (401, 403):
            error: RiotError = RiotForbidden(
                f"Riot API key rejected: HTTP {status} {message}", status=status, url=url
            )
            self._status.key_ok = False
            self._record_error(error)
            logger.error("Riot API key rejected (HTTP %d %s) on %s", status, message, method)
            raise error
        if status == 404:
            # An authenticated "no such resource": the key itself is fine.
            self._accepted()
            raise RiotNotFound(f"not found: {message}", status=status, url=url)
        raise RiotError(f"Riot API returned HTTP {status}: {message}", status=status, url=url)

    def _validate[M: BaseModel](self, model: type[M], data: Any, method: str) -> M:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise self._bad_response(method, _summarize(exc)) from exc

    def _validate_adapter[T](self, adapter: TypeAdapter[T], data: Any, method: str) -> T:
        try:
            return adapter.validate_python(data)
        except ValidationError as exc:
            raise self._bad_response(method, _summarize(exc)) from exc

    def _bad_response(self, method: str, detail: str) -> RiotBadResponse:
        error = RiotBadResponse(f"invalid Riot response for {method}: {detail}")
        self._record_error(error)
        logger.warning("%s", error)
        return error

    def _accepted(self) -> None:
        """Riot answered an authenticated request: the key works right now."""
        self._status.key_ok = True
        self._status.last_ok_at = datetime.now(UTC)

    def _record_error(self, error: RiotError) -> None:
        self._status.last_error = str(error)
        self._status.last_error_at = datetime.now(UTC)


def _summarize(exc: ValidationError) -> str:
    """Short, value-free description of a validation failure."""
    errors = exc.errors(include_input=False, include_url=False)
    first = errors[0] if errors else None
    if first is None:
        return "validation failed"
    loc = ".".join(str(part) for part in first["loc"]) or "<root>"
    more = f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""
    return f"{loc}: {first['msg']}{more}"
