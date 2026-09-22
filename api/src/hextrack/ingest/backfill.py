"""One-off deep backfill of the tracked roster's ranked history (``hextrack backfill``).

The poller already knows how to fill a player's history: with no ``synced_through``
watermark it lists the whole season and ingests it oldest first, moving the watermark up
over what is stored. This module reuses that machinery for a deliberate catch-up run:

1. clear ``synced_through`` / ``backfilled_at`` for the selected tracked players, so their
   next discovery lists everything from the anchor date instead of from the watermark;
2. run :func:`~hextrack.ingest.poller.poll_once` ticks until every selected player is
   marked backfilled and a tick brings in nothing new (or a limit is reached);
3. report what each player gained.

``since`` overrides the season anchor for this run only (the settings copy is local), so a
scrape can reach back further than ``HEXTRACK_SEASON_START`` -- Riot keeps roughly the last
two years of match ids. The run is resumable: interrupt it and start it again, or just let
the normal worker carry on, because the watermark only ever advances over stored history.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import Text, any_, bindparam, func, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.config import Settings
from hextrack.db.engine import make_async_engine, make_session_factory, session_scope
from hextrack.db.models import Match, MatchParticipant, Summoner
from hextrack.db.repo import summoners as summoners_repo
from hextrack.ingest.context import IngestContext
from hextrack.ingest.poller import poll_once
from hextrack.queues import RANKED_QUEUES
from hextrack.riotid import parse_riot_id, riot_id_key

if TYPE_CHECKING:
    from hextrack.hextrack_ai.inference import Scorer

logger = logging.getLogger(__name__)

ARRAY_TEXT: Final = ARRAY(Text)

#: Stop after this many ticks even if players still look incomplete (a safety net against
#: a roster that never settles, e.g. Riot listing ids it then 404s on).
MAX_TICKS: int = 40


@dataclass(slots=True)
class PlayerBackfill:
    riot_id: str
    puuid: str
    before: int
    after: int
    complete: bool

    @property
    def gained(self) -> int:
        return self.after - self.before


@dataclass(slots=True)
class BackfillReport:
    since: datetime
    players: list[PlayerBackfill] = field(default_factory=list)
    ticks: int = 0
    matches_ingested: int = 0
    errors: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)

    @property
    def matches_gained(self) -> int:
        return sum(p.gained for p in self.players)


async def _ranked_counts(session: AsyncSession, puuids: Collection[str]) -> dict[str, int]:
    """Stored ranked games per puuid."""
    if not puuids:
        return {}
    stmt = (
        select(MatchParticipant.puuid, func.count())
        .join(Match, Match.match_id == MatchParticipant.match_id)
        .where(
            MatchParticipant.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY_TEXT)),
            Match.queue_id.in_(sorted(RANKED_QUEUES)),
        )
        .group_by(MatchParticipant.puuid)
    )
    return {row[0]: int(row[1]) for row in (await session.execute(stmt)).all()}


async def _reset_sync_state(session: AsyncSession, puuids: Collection[str]) -> int:
    """Clear the discovery watermark so the next listing covers the whole anchor range."""
    if not puuids:
        return 0
    stmt = (
        update(Summoner)
        .where(Summoner.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY_TEXT)))
        .values(synced_through=None, backfilled_at=None)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(stmt)
    return int(getattr(result, "rowcount", 0) or 0)


async def _select_players(session: AsyncSession, riot_ids: Sequence[str] | None) -> list[Summoner]:
    tracked = await summoners_repo.list_tracked(session)
    if riot_ids is None:
        return tracked
    wanted = set()
    for value in riot_ids:
        parsed = parse_riot_id(value)
        wanted.add(riot_id_key(parsed.game_name, parsed.tag_line))
    chosen = [s for s in tracked if riot_id_key(s.game_name, s.tag_line) in wanted]
    missing = wanted - {riot_id_key(s.game_name, s.tag_line) for s in chosen}
    if missing:
        names = ", ".join(sorted(f"{game}#{tag}" for game, tag in missing))
        raise ValueError(f"not on the tracked roster: {names} (see 'hextrack roster list')")
    return chosen


async def run_backfill(
    settings: Settings,
    *,
    since: datetime | None = None,
    riot_ids: Sequence[str] | None = None,
    max_ticks: int = MAX_TICKS,
) -> BackfillReport:
    """Catch the tracked roster's ranked history up to Riot, from ``since`` (default: the
    configured season start). Blocks until nothing new arrives or ``max_ticks`` is spent."""
    from hextrack.riot.client import RiotClient

    if not settings.riot_key_configured:
        raise ValueError("RIOT_API_KEY is not configured; a backfill needs the Riot API")
    anchor = since or settings.season_start
    run_settings = settings.model_copy(update={"season_start": anchor})
    report = BackfillReport(since=anchor)

    engine = make_async_engine(settings, pool_size=3, max_overflow=2)
    try:
        factory = make_session_factory(engine)
        async with session_scope(factory) as session:
            players = await _select_players(session, riot_ids)
            if not players:
                return report
            puuids = [s.puuid for s in players]
            names = {s.puuid: f"{s.game_name}#{s.tag_line}" for s in players}
            before = await _ranked_counts(session, puuids)
            await _reset_sync_state(session, puuids)
        logger.info(
            "backfill: %d players from %s (%s)",
            len(players),
            anchor.date().isoformat(),
            ", ".join(sorted(names.values())),
        )

        scorer = await asyncio.to_thread(_load_scorer, settings)
        async with RiotClient(run_settings, app_limits=run_settings.worker_app_rate_limits) as riot:
            ctx = IngestContext(
                settings=run_settings, session_factory=factory, riot=riot, scorer=scorer
            )
            await run_ticks(ctx, puuids, report, max_ticks=max_ticks)

        async with session_scope(factory) as session:
            after = await _ranked_counts(session, puuids)
            pending = await _pending(session, puuids)
        report.players = sorted(
            (
                PlayerBackfill(
                    riot_id=names[puuid],
                    puuid=puuid,
                    before=before.get(puuid, 0),
                    after=after.get(puuid, 0),
                    complete=puuid not in pending,
                )
                for puuid in puuids
            ),
            key=lambda p: (-p.gained, p.riot_id.lower()),
        )
        report.incomplete = sorted(names[p] for p in pending)
    finally:
        await engine.dispose()
    return report


async def run_ticks(
    ctx: IngestContext,
    puuids: Collection[str],
    report: BackfillReport,
    *,
    max_ticks: int = MAX_TICKS,
) -> BackfillReport:
    """Poll until every player in ``puuids`` is backfilled and a tick adds nothing new.

    Each tick is a full :func:`poll_once`, so the roster's ordinary new games are picked up
    at the same time and the watermarks advance the usual way.
    """
    for tick in range(1, max_ticks + 1):
        result = await poll_once(ctx)
        report.ticks = tick
        report.matches_ingested += result.new_matches
        for message in result.errors:
            if message not in report.errors:
                report.errors.append(message)
        if result.auth_failed:
            report.errors.append("Riot rejected the API key; backfill stopped")
            break
        if result.skipped:
            raise RuntimeError("another poller holds the lock; stop 'hextrack worker' and retry")
        async with session_scope(ctx.session_factory) as session:
            pending = await _pending(session, puuids)
        logger.info(
            "backfill tick %d: +%d matches (%d players still catching up)",
            tick,
            result.new_matches,
            len(pending),
        )
        if not pending and result.new_matches == 0:
            break
    return report


async def _pending(session: AsyncSession, puuids: Collection[str]) -> set[str]:
    """Selected players whose season backfill has not finished yet."""
    stmt = select(Summoner.puuid).where(
        Summoner.puuid == any_(bindparam("puuids", list(puuids), type_=ARRAY_TEXT)),
        Summoner.backfilled_at.is_(None),
    )
    return set(await session.scalars(stmt))


def _load_scorer(settings: Settings) -> Scorer | None:
    from hextrack.hextrack_ai.inference import Scorer

    try:
        return Scorer.load(settings.model_dir)
    except Exception:
        logger.exception("could not load the AI model; backfilled games are stored unscored")
        return None
