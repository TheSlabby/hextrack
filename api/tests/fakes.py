"""In-memory stand-ins for external services (Riot). Never touch the network.

``FakeRiotClient`` implements the full :class:`hextrack.riot.client.RiotClient` interface
from dicts, records every call and can raise configured :class:`RiotError` s::

    riot = FakeRiotClient()
    me = riot.add_account("Hex Walker", "NA1", puuid="p1", level=312)
    riot.add_league_entry("p1", "RANKED_SOLO_5x5", "GOLD", "II", 45, wins=30, losses=25)
    riot.add_match(make_match_json("NA1_1", [spec("p1", "Hex Walker", "NA1")]))
    riot.fail("match", RiotRateLimited(retry_after=3))          # next call only
    riot.fail("summoner_by_puuid", RiotForbidden("expired"), times=None)  # every call

Use :func:`install_fakes` to put a fake (and/or a scorer) on a running app.
"""

from __future__ import annotations

import copy
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from fastapi import FastAPI

from hextrack.config import Settings
from hextrack.queues import RANKED_QUEUES
from hextrack.riot.client import MATCH_ID_TYPES, METHOD_ROUTING, RiotStatus
from hextrack.riot.errors import (
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
)
from hextrack.riot.schemas import AccountDto, LeagueEntryDto, SummonerDto
from hextrack.riotid import riot_id_key


@dataclass(slots=True)
class Call:
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Failure:
    error: RiotError
    #: Remaining uses; None = forever.
    times: int | None


class FakeRiotClient:
    """Duck-typed RiotClient backed by in-memory dicts."""

    def __init__(self, settings: Settings | None = None, *, key_configured: bool = True) -> None:
        self.settings = settings
        self.accounts: dict[str, AccountDto] = {}
        self.summoners: dict[str, SummonerDto] = {}
        self.league_entries: dict[str, list[LeagueEntryDto]] = defaultdict(list)
        #: puuid -> match ids, newest first.
        self.match_ids: dict[str, list[str]] = defaultdict(list)
        self.matches: dict[str, dict[str, Any]] = {}
        self.calls: list[Call] = []
        self.closed = False
        self._failures: dict[str, deque[_Failure]] = defaultdict(deque)
        self._status = RiotStatus(key_configured=key_configured)
        self.wait_estimate = 0.0

    # --- configuration ------------------------------------------------------------------------
    def add_account(
        self,
        game_name: str,
        tag_line: str,
        *,
        puuid: str | None = None,
        profile_icon_id: int = 29,
        level: int = 100,
    ) -> AccountDto:
        """Register an account and its summoner-v4 record; returns the AccountDto."""
        puuid = puuid or f"puuid-{game_name.lower().replace(' ', '-')}-{tag_line.lower()}"
        account = AccountDto(puuid=puuid, gameName=game_name, tagLine=tag_line)
        self.accounts[puuid] = account
        self.summoners[puuid] = SummonerDto(
            puuid=puuid, profileIconId=profile_icon_id, summonerLevel=level, revisionDate=0
        )
        self.league_entries.setdefault(puuid, [])
        return account

    def add_league_entry(
        self,
        puuid: str,
        queue_type: str,
        tier: str,
        rank: str | None,
        lp: int,
        *,
        wins: int = 10,
        losses: int = 10,
    ) -> LeagueEntryDto:
        """Set (replace) the league entry for ``queue_type``."""
        entry = LeagueEntryDto(
            queueType=queue_type,
            tier=tier,
            rank=rank if rank is not None else "I",
            leaguePoints=lp,
            wins=wins,
            losses=losses,
            puuid=puuid,
        )
        entries = [e for e in self.league_entries[puuid] if e.queue_type != queue_type]
        entries.append(entry)
        self.league_entries[puuid] = entries
        return entry

    def add_match(self, raw: dict[str, Any], *, index_for_participants: bool = True) -> str:
        """Store a raw match; by default also list its id for every participant's puuid."""
        match_id = raw["metadata"]["matchId"]
        self.matches[match_id] = copy.deepcopy(raw)
        if index_for_participants:
            for p in raw["info"]["participants"]:
                ids = self.match_ids[p["puuid"]]
                if match_id not in ids:
                    ids.append(match_id)
                    ids.sort(key=lambda i: self._start_ms(i) or 0, reverse=True)
        return match_id

    def fail(self, method: str, error: RiotError, *, times: int | None = 1) -> None:
        """Raise ``error`` from ``method`` for the next ``times`` calls (None = always)."""
        self._failures[method].append(_Failure(error, times))

    def clear_failures(self) -> None:
        self._failures.clear()

    def calls_to(self, method: str) -> list[Call]:
        return [c for c in self.calls if c.method == method]

    # --- RiotClient interface -----------------------------------------------------------------
    async def aclose(self) -> None:
        self.closed = True

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

    def limiter_wait_estimate(self, method: str | None = None) -> float:
        """Mirror of the real client: ``method`` must be a client method name."""
        if method is not None and method not in METHOD_ROUTING:
            raise ValueError(f"unknown Riot client method {method!r}")
        return self.wait_estimate

    async def account_by_riot_id(self, game_name: str, tag_line: str) -> AccountDto:
        self._enter("account_by_riot_id", game_name, tag_line)
        key = riot_id_key(game_name, tag_line)
        for account in self.accounts.values():
            if riot_id_key(account.game_name or "", account.tag_line or "") == key:
                return account.model_copy()
        raise RiotNotFound(f"account {game_name}#{tag_line} not found", status=404)

    async def account_by_puuid(self, puuid: str) -> AccountDto:
        self._enter("account_by_puuid", puuid)
        try:
            return self.accounts[puuid].model_copy()
        except KeyError:
            raise RiotNotFound(f"account {puuid} not found", status=404) from None

    async def summoner_by_puuid(self, puuid: str) -> SummonerDto:
        self._enter("summoner_by_puuid", puuid)
        try:
            return self.summoners[puuid].model_copy()
        except KeyError:
            raise RiotNotFound(f"summoner {puuid} not found", status=404) from None

    async def league_entries_by_puuid(self, puuid: str) -> list[LeagueEntryDto]:
        self._enter("league_entries_by_puuid", puuid)
        return [e.model_copy() for e in self.league_entries.get(puuid, [])]

    async def active_game_by_puuid(self, puuid: str) -> None:
        """spectator-v5: nobody is in a live game here (test_ingest_live.py has its own fake)."""
        self._enter("active_game_by_puuid", puuid)
        return None

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
        if type_ is not None and type_ not in MATCH_ID_TYPES:
            raise ValueError(f"type_ must be one of {sorted(MATCH_ID_TYPES)} or None")
        self._enter(
            "match_ids_by_puuid",
            puuid,
            start=start,
            count=count,
            queue=queue,
            type_=type_,
            start_time=start_time,
            # Recorded only when passed, so call assertions written before end_time existed hold.
            **({"end_time": end_time} if end_time is not None else {}),
        )
        ids = list(self.match_ids.get(puuid, []))
        if queue is not None:
            ids = [i for i in ids if self._queue(i) in (None, queue)]
        if type_ == "ranked":
            ids = [i for i in ids if self._queue(i) is None or self._queue(i) in RANKED_QUEUES]
        if start_time is not None:
            cutoff = int(start_time.astimezone(UTC).timestamp() * 1000)
            ids = [i for i in ids if (self._start_ms(i) or 0) >= cutoff]
        if end_time is not None:
            end_ms = int(end_time.astimezone(UTC).timestamp() * 1000)
            ids = [i for i in ids if (ms := self._start_ms(i)) is None or ms <= end_ms]
        start = max(start, 0)
        count = min(max(count, 1), 100)
        return ids[start : start + count]

    async def match(self, match_id: str) -> dict[str, Any]:
        self._enter("match", match_id)
        try:
            return copy.deepcopy(self.matches[match_id])
        except KeyError:
            raise RiotNotFound(f"match {match_id} not found", status=404) from None

    # --- internals ----------------------------------------------------------------------------
    def _enter(self, method: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append(Call(method, args, kwargs))
        if not self._status.key_configured:
            raise RiotKeyMissing()
        queue = self._failures.get(method)
        if queue:
            failure = queue[0]
            if failure.times is not None:
                failure.times -= 1
                if failure.times <= 0:
                    queue.popleft()
            if isinstance(failure.error, RiotForbidden):
                self._status.key_ok = False
            self._status.last_error = str(failure.error)
            self._status.last_error_at = datetime.now(UTC)
            raise failure.error
        self._status.key_ok = True
        self._status.last_ok_at = datetime.now(UTC)

    def _info_int(self, match_id: str, key: str) -> int | None:
        """``info[key]`` of a stored match as int, or None when absent or corrupt."""
        raw = self.matches.get(match_id)
        info = raw.get("info") if isinstance(raw, dict) else None
        value = info.get(key) if isinstance(info, dict) else None
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _start_ms(self, match_id: str) -> int | None:
        return self._info_int(match_id, "gameStartTimestamp")

    def _queue(self, match_id: str) -> int | None:
        return self._info_int(match_id, "queueId")


def install_fakes(
    app: FastAPI,
    *,
    riot: Any | None = None,
    scorer: Any | None = None,
    set_scorer: bool = False,
) -> None:
    """Swap ``app.state.riot`` / ``app.state.scorer`` and keep ``app.state.ingest_ctx`` in
    sync. Pass ``set_scorer=True`` to install ``scorer`` even when it is None."""
    ctx = app.state.ingest_ctx
    if riot is not None:
        app.state.riot = riot
        ctx.riot = riot
    if scorer is not None or set_scorer:
        app.state.scorer = scorer
        ctx.scorer = scorer
