"""Client-side rate limiting for the Riot API.

Riot enforces two layers of limits per API key *and per routing value* (``na1``,
``americas``, ...):

* **application limits** that every request counts against (development keys: 20 per second
  and 100 per two minutes). They are announced in ``X-App-Rate-Limit`` and the current usage
  in ``X-App-Rate-Limit-Count``;
* **method limits** per endpoint, announced in ``X-Method-Rate-Limit`` /
  ``X-Method-Rate-Limit-Count``.

:class:`RateLimiter` models one routing value. It starts from the configured application
limits (``RIOT_APP_RATE_LIMITS``), learns method limits from response headers and adopts the
application limits Riot announces, because those describe the key actually in use. The
configured limits stay a **ceiling** for every window Riot announces as well
(``min(configured, announced)``), so a deployment can reserve part of the key's budget for
another process (the on-demand API traffic, a second app) by configuring a smaller value.
:class:`hextrack.riot.client.RiotClient` keeps one limiter per routing value.

Every limit is a *sliding window log*: a request may be sent at ``t`` only if fewer than
``max_requests`` requests were sent in ``(t - window - margin, t]``. That is at least as strict
as Riot's own fixed windows, and the small ``margin`` absorbs network jitter between our send
time and Riot's receive time.

Usage reported by Riot (``X-App-Rate-Limit-Count``) is compared against the local log **at the
time the request was sent**, not when its response arrived: the round trip would otherwise make
requests Riot already counted look missing, and every padded phantom hit costs real budget.

Concurrency: :meth:`RateLimiter.acquire` checks and records every limit without awaiting in
between, so concurrent coroutines can never over-admit. Waiters for the same method queue on
a FIFO lock, so a burst of calls drains in order instead of re-racing on every wake-up.
Waiters for different methods compete only for the shared application window.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from bisect import bisect_right, insort
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]

#: Extra seconds added to every window (network jitter between send and receive time).
DEFAULT_MARGIN_SECONDS: Final = 0.1
#: Waits shorter than this are treated as "go now" (float rounding after a sleep).
_EPSILON: Final = 1e-6
#: History kept for a method whose limits are not known yet, so the requests sent before
#: its first response still count once ``X-Method-Rate-Limit`` arrives (Riot's longest
#: method window is 10 minutes).
UNKNOWN_LIMITS_HORIZON_SECONDS: Final = 600.0
#: Riot's ``X-Rate-Limit-Type`` value for application-wide 429s.
LIMIT_TYPE_APPLICATION: Final = "application"
LIMIT_TYPE_METHOD: Final = "method"
LIMIT_TYPE_SERVICE: Final = "service"

APP_LIMIT_HEADER: Final = "x-app-rate-limit"
APP_COUNT_HEADER: Final = "x-app-rate-limit-count"
METHOD_LIMIT_HEADER: Final = "x-method-rate-limit"
METHOD_COUNT_HEADER: Final = "x-method-rate-limit-count"


@dataclass(frozen=True, slots=True)
class RateLimit:
    """At most ``max_requests`` requests per ``window_seconds``."""

    max_requests: int
    window_seconds: float

    def __post_init__(self) -> None:
        if self.max_requests <= 0 or not self.window_seconds > 0:
            raise ValueError(f"invalid rate limit {self.max_requests}:{self.window_seconds}")

    def __str__(self) -> str:
        return f"{self.max_requests}:{self.window_seconds:g}"


def parse_rate_limit_header(value: str | None) -> list[tuple[int, float]]:
    """Parse a Riot rate-limit header ("20:1,100:120") into ``[(20, 1.0), (100, 120.0)]``.

    Works for both limit and count headers. Malformed or non-positive pairs are skipped, so a
    garbled header never breaks a request; ``None`` or "" yields ``[]``. Count headers may
    legitimately contain a zero count, so only the window must be positive.
    """
    pairs: list[tuple[int, float]] = []
    if not value:
        return pairs
    for part in value.split(","):
        count_str, sep, window_str = part.strip().partition(":")
        if not sep:
            continue
        try:
            count, window = int(count_str), float(window_str)
        except ValueError:
            continue
        if count < 0 or not math.isfinite(window) or window <= 0:
            continue
        pairs.append((count, window))
    return pairs


def _to_limits(pairs: Iterable[tuple[int, float] | RateLimit]) -> tuple[RateLimit, ...]:
    limits = {(p if isinstance(p, RateLimit) else RateLimit(int(p[0]), float(p[1]))) for p in pairs}
    return tuple(sorted(limits, key=lambda limit: (limit.window_seconds, limit.max_requests)))


def _wait_on(
    hits: list[float], limits: tuple[RateLimit, ...], margin: float, blocked_until: float, t: float
) -> float:
    """Seconds after ``t`` until one more request fits every limit, given sorted ``hits``."""
    wait = blocked_until - t
    n = len(hits)
    for limit in limits:
        if n < limit.max_requests:
            continue
        window = limit.window_seconds + margin
        # The request that must leave the window before another one fits.
        gate = hits[n - limit.max_requests]
        if gate > t - window:
            wait = max(wait, gate + window - t)
    return wait if wait > _EPSILON else 0.0


class _Bucket:
    """Sliding-window log for one set of limits (the application or a single method)."""

    __slots__ = ("limits", "hits", "blocked_until", "margin", "lock", "pending")

    def __init__(self, limits: tuple[RateLimit, ...], margin: float) -> None:
        self.limits = limits
        #: Send times, ascending.
        self.hits: list[float] = []
        self.blocked_until = -math.inf
        self.margin = margin
        self.lock = asyncio.Lock()
        #: Coroutines currently inside ``acquire`` for this bucket.
        self.pending = 0

    def horizon(self) -> float:
        if not self.limits:
            return UNKNOWN_LIMITS_HORIZON_SECONDS
        return max(limit.window_seconds for limit in self.limits) + self.margin

    def prune(self, now: float) -> None:
        cutoff = now - self.horizon()
        idx = bisect_right(self.hits, cutoff)
        if idx:
            del self.hits[:idx]

    def wait_time(self, now: float) -> float:
        self.prune(now)
        return _wait_on(self.hits, self.limits, self.margin, self.blocked_until, now)

    def record(self, now: float) -> None:
        if not self.hits or now >= self.hits[-1]:
            self.hits.append(now)
        else:
            insort(self.hits, now)

    def count_in_window(self, window_seconds: float, at: float) -> int:
        """Hits recorded in ``(at - window - margin, at]`` (hits after ``at`` do not count:
        ``at`` may be a past send time, see :meth:`RateLimiter.update_from_headers`)."""
        lower = bisect_right(self.hits, at - window_seconds - self.margin)
        return bisect_right(self.hits, at) - lower

    def sync_counts(self, counts: Iterable[tuple[int, float]], now: float) -> int:
        """Pad the log when Riot reports more usage than we recorded at ``now`` (another
        process shares the key, or requests from before a restart). ``now`` is the send time
        of the request whose response carried ``counts``. Returns how many hits were added."""
        added = 0
        self.prune(now)
        for remote, window in counts:
            limit = next(
                (lim for lim in self.limits if math.isclose(lim.window_seconds, window)), None
            )
            if limit is None:
                continue
            local = self.count_in_window(limit.window_seconds, now)
            missing = min(remote, limit.max_requests) - local
            for _ in range(max(missing, 0)):
                self.record(now)
                added += 1
        return added

    def earliest_after(self, now: float, extra: int) -> float:
        """Time at which a request could go if ``extra`` requests are queued ahead of it."""
        self.prune(now)
        hits = list(self.hits)
        t = now
        for i in range(extra + 1):
            while True:
                wait = _wait_on(hits, self.limits, self.margin, self.blocked_until, t)
                if wait <= 0.0:
                    break
                t += wait
            if i < extra:
                hits.append(t)
        return t


class RateLimiter:
    """Application + per-method rate limits for one Riot routing value.

    ``clock`` must be monotonic; ``sleep`` is awaited while waiting (both injectable so tests
    can run on a fake clock). Method names are free-form keys (the client uses its own method
    names, e.g. ``"match"``).
    """

    def __init__(
        self,
        app_limits: Iterable[tuple[int, float] | RateLimit],
        *,
        name: str = "riot",
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
        margin: float = DEFAULT_MARGIN_SECONDS,
    ) -> None:
        if margin < 0:
            raise ValueError("margin must be >= 0")
        self.name = name
        self._clock = clock
        self._sleep = sleep
        self._margin = float(margin)
        #: Configured application limits; a ceiling for the ones Riot announces.
        self._configured = _to_limits(app_limits)
        self._app = _Bucket(self._configured, self._margin)
        self._methods: dict[str, _Bucket] = {}
        self._pending_total = 0

    # --- introspection --------------------------------------------------------------------
    @property
    def app_limits(self) -> tuple[RateLimit, ...]:
        return self._app.limits

    def method_limits(self, method: str) -> tuple[RateLimit, ...]:
        bucket = self._methods.get(method)
        return bucket.limits if bucket is not None else ()

    @property
    def pending(self) -> int:
        """Coroutines currently waiting in (or passing through) :meth:`acquire`."""
        return self._pending_total

    # --- core -----------------------------------------------------------------------------
    async def acquire(self, method: str) -> float:
        """Wait until a request for ``method`` fits every limit, record it and return the
        seconds spent waiting. Cancellation-safe: a cancelled waiter records nothing."""
        start, granted = await self.reserve(method)
        return granted - start

    async def reserve(self, method: str) -> tuple[float, float]:
        """:meth:`acquire` that returns ``(start, granted)`` on the limiter's clock.

        ``granted`` is the send time recorded in the log; pass it to
        :meth:`update_from_headers` as ``sent_at`` so Riot's usage counts are compared
        against the window as it was when the request left.
        """
        bucket = self._bucket(method)
        start = self._clock()
        self._pending_total += 1
        bucket.pending += 1
        try:
            async with bucket.lock:
                while True:
                    now = self._clock()
                    wait = max(self._app.wait_time(now), bucket.wait_time(now))
                    if wait <= 0.0:
                        self._app.record(now)
                        bucket.record(now)
                        waited = now - start
                        if waited > 0.5:
                            logger.debug(
                                "rate limiter %s/%s waited %.2fs", self.name, method, waited
                            )
                        return start, now
                    await self._sleep(wait)
        finally:
            self._pending_total -= 1
            bucket.pending -= 1

    def wait_estimate(self, method: str | None = None) -> float:
        """Seconds a new request would wait if issued now, counting requests already queued.

        With ``method=None`` only the application limits (and an application-wide 429 block)
        are considered; otherwise the method's own limits are included too.
        """
        now = self._clock()
        ready = self._app.earliest_after(now, self._pending_total)
        if method is not None:
            bucket = self._methods.get(method)
            if bucket is not None:
                ready = max(ready, bucket.earliest_after(now, bucket.pending))
        return max(ready - now, 0.0)

    def update_from_headers(
        self,
        method: str,
        headers: Mapping[str, str],
        *,
        sent_at: float | None = None,
        sync_counts: bool = True,
    ) -> None:
        """Apply ``X-App-Rate-Limit[-Count]`` / ``X-Method-Rate-Limit[-Count]`` from a
        response. Missing or malformed headers leave the current limits untouched.

        ``sent_at`` is the send time returned by :meth:`reserve`; usage counts are compared
        against the windows as of that instant (the default, "now", would count the round
        trip as missing usage and pad phantom hits). ``sync_counts=False`` ignores the count
        headers altogether: a 429 reports a full window, which :meth:`penalize` already
        models through ``Retry-After``.
        """
        lowered = {key.lower(): value for key, value in headers.items()}
        at = sent_at if sent_at is not None else self._clock()

        self._set_app_limits(parse_rate_limit_header(lowered.get(APP_LIMIT_HEADER)))
        method_limits = parse_rate_limit_header(lowered.get(METHOD_LIMIT_HEADER))
        known_method = method_limits or method in self._methods
        if known_method:
            self._set_limits(self._bucket(method), method_limits, f"{self.name} method {method}")
        if not sync_counts:
            return

        if added := self._app.sync_counts(
            parse_rate_limit_header(lowered.get(APP_COUNT_HEADER)), at
        ):
            logger.info("rate limiter %s: synced %d application hits from Riot", self.name, added)
        if known_method:
            self._bucket(method).sync_counts(
                parse_rate_limit_header(lowered.get(METHOD_COUNT_HEADER)), at
            )

    def penalize(self, method: str, retry_after: float, limit_type: str | None) -> None:
        """Block requests for ``retry_after`` seconds after a 429.

        ``limit_type == "application"`` blocks every method on this routing value; "method",
        "service" or an unknown type blocks only ``method``.
        """
        until = self._clock() + max(float(retry_after), 0.0)
        target = self._app if limit_type == LIMIT_TYPE_APPLICATION else self._bucket(method)
        target.blocked_until = max(target.blocked_until, until)

    # --- internals ------------------------------------------------------------------------
    def _set_app_limits(self, announced: list[tuple[int, float]]) -> None:
        """Adopt Riot's application limits, capped by the configured ones per window."""
        valid = [(count, window) for count, window in announced if count > 0]
        if not valid:
            return
        configured = {limit.window_seconds: limit.max_requests for limit in self._configured}
        capped: list[tuple[int, float]] = []
        for count, window in valid:
            allowed = configured.get(window)
            if allowed is not None and allowed < count:
                logger.debug(
                    "rate limiter %s: Riot announces %d:%g, keeping the configured %d:%g",
                    self.name,
                    count,
                    window,
                    allowed,
                    window,
                )
                count = allowed
            capped.append((count, window))
        self._set_limits(self._app, capped, f"{self.name} application")

    def _bucket(self, method: str) -> _Bucket:
        bucket = self._methods.get(method)
        if bucket is None:
            bucket = self._methods[method] = _Bucket((), self._margin)
        return bucket

    @staticmethod
    def _set_limits(bucket: _Bucket, pairs: list[tuple[int, float]], label: str) -> None:
        valid = [(count, window) for count, window in pairs if count > 0]
        if not valid:
            return
        limits = _to_limits(valid)
        if limits != bucket.limits:
            logger.info(
                "rate limits for %s: %s",
                label,
                ",".join(str(limit) for limit in limits),
            )
            bucket.limits = limits
