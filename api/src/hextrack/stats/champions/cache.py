"""A small process-wide TTL cache for the champion pages' read side.

The rollups change only when the worker counts a batch, and the same few pages (the list,
popular champions on the recent patches) are requested over and over, so the patch window,
champion list and champion details are kept for :data:`TTL_SECONDS`. Squad rows are live
queries and are not cached.

Entries are tied to the database engine that produced them (each app instance, e.g. each
API test, owns its engine), like :mod:`hextrack.stats.role_percentile`: a request through a
different engine starts from an empty cache. The cache holds at most :data:`MAX_ENTRIES`
values; the oldest is evicted first. Cached values are shared between requests and must not
be mutated.
"""

from __future__ import annotations

import time
import weakref
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Any, Final, TypeVar

T = TypeVar("T")

TTL_SECONDS: Final = 120.0
#: About 170 champions x a few windows / roles in active use, plus the lists.
MAX_ENTRIES: Final = 512


class TTLCache:
    def __init__(
        self,
        *,
        ttl_seconds: float = TTL_SECONDS,
        max_entries: int = MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._engine: weakref.ref[Any] | None = None
        #: Values computed (cache misses), for tests and logs.
        self.misses = 0

    def clear(self) -> None:
        self._entries.clear()
        self._engine = None

    def __len__(self) -> int:
        return len(self._entries)

    async def get_or_load(self, engine: Any, key: Hashable, load: Callable[[], Awaitable[T]]) -> T:
        """The cached value for ``key``, or ``await load()`` stored for the TTL. Exceptions
        from ``load`` are not cached."""
        self._bind(engine)
        now = self._clock()
        hit = self._entries.get(key)
        if hit is not None and hit[0] > now:
            self._entries.move_to_end(key)
            return hit[1]
        value = await load()
        self.misses += 1
        self._entries[key] = (self._clock() + self.ttl_seconds, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        return value

    def _bind(self, engine: Any) -> None:
        current = self._engine() if self._engine is not None else None
        if current is engine and engine is not None:
            return
        self._entries.clear()
        try:
            self._engine = weakref.ref(engine) if engine is not None else None
        except TypeError:
            self._engine = None


#: The cache every champion route uses.
CHAMPION_CACHE: Final = TTLCache()
