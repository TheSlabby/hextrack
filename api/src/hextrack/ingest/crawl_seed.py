"""``hextrack crawl seed``: add ladder players to the data crawler's frontier by hand.

The crawler (``ingest/crawler.py``) discovers players on its own; this is for testing and
for steering it toward a tier. Uses the Riot key (league-exp-v4, one call per page). Takes
a session and never commits (the caller owns the transaction).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.db.models import CrawlPlayer, Summoner
from hextrack.ingest.context import IngestContext
from hextrack.rank import APEX_TIERS, DIVISION_ORDER, RANKED_SOLO_5x5, normalize_tier

#: Rows per INSERT (asyncpg allows 32767 bind parameters per statement).
_INSERT_CHUNK = 2000


class SeedError(ValueError):
    """Bad tier / division (operator error, printed as one line)."""


@dataclass(slots=True)
class SeedReport:
    tier: str
    division: str
    pages: int
    listed: int = 0
    added: int = 0
    already_known: int = 0
    skipped_tracked: int = 0
    skipped_frontier_full: int = 0


def normalize_ladder(tier: str, division: str) -> tuple[str, str]:
    """``("GOLD", "II")``; apex tiers only have division ``I``."""
    try:
        t = normalize_tier(tier)
    except ValueError as exc:
        raise SeedError(str(exc)) from exc
    d = division.strip().upper()
    if d not in DIVISION_ORDER:
        raise SeedError(f"unknown division {division!r} (use I, II, III or IV)")
    if t in APEX_TIERS and d != "I":
        raise SeedError(f"{t} has no divisions; use --division I")
    return t, d


async def seed_from_ladder(
    ctx: IngestContext,
    session: AsyncSession,
    tier: str,
    division: str,
    *,
    pages: int = 1,
    first_page: int = 1,
) -> SeedReport:
    """Add the solo-queue ladder players on ``pages`` pages of TIER DIVISION to
    ``crawl_players`` (found_via "ladder"). Tracked roster players and players already in the
    frontier are skipped; the frontier never grows past ``crawl_frontier_max``."""
    t, d = normalize_ladder(tier, division)
    report = SeedReport(tier=t, division=d, pages=pages)

    puuids: list[str] = []
    for page in range(first_page, first_page + pages):
        entries = await ctx.riot.league_exp_entries(RANKED_SOLO_5x5, t, d, page=page)
        if not entries:
            break
        puuids.extend(e.puuid for e in entries if e.puuid)
    puuids = list(dict.fromkeys(puuids))
    report.listed = len(puuids)
    if not puuids:
        return report

    tracked: set[str] = set()
    known: set[str] = set()
    for start in range(0, len(puuids), _INSERT_CHUNK):
        chunk = puuids[start : start + _INSERT_CHUNK]
        tracked.update(
            await session.scalars(
                select(Summoner.puuid).where(
                    Summoner.puuid.in_(chunk), Summoner.is_tracked.is_(True)
                )
            )
        )
        known.update(
            await session.scalars(select(CrawlPlayer.puuid).where(CrawlPlayer.puuid.in_(chunk)))
        )
    report.skipped_tracked = len(tracked)
    report.already_known = len(known - tracked)
    new = [p for p in puuids if p not in tracked and p not in known]

    size = int(await session.scalar(select(func.count()).select_from(CrawlPlayer)) or 0)
    room = max(0, ctx.settings.crawl_frontier_max - size)
    report.skipped_frontier_full = max(0, len(new) - room)
    new = new[:room]
    # Apex tiers have no divisions (Riot's "I" is a placeholder there).
    stored_division = None if t in APEX_TIERS else d
    for start in range(0, len(new), _INSERT_CHUNK):
        rows = [
            {"puuid": p, "found_via": "ladder", "tier": t, "division": stored_division}
            for p in new[start : start + _INSERT_CHUNK]
        ]
        stmt = insert(CrawlPlayer).values(rows).on_conflict_do_nothing(index_elements=["puuid"])
        result = await session.execute(stmt)
        report.added += result.rowcount if result.rowcount is not None else len(rows)
    return report
