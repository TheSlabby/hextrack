"""Duo synergy grid and "who carries whom" (``GET /api/v1/squad/pairs``).

Both features read the same participant set: the tracked roster's ranked Summoner's Rift
lines (``queue`` filter), remakes excluded, games started at or after the ``since`` cutoff
(:mod:`hextrack.stats.filters`). Three queries in total, whatever the roster size:

1. the roster (:func:`hextrack.stats.queries.tracked_summoners`);
2. every player's own totals (games, wins, average active-model AI Score);
3. every pair: a self-join of the roster's lines on ``(match_id, team_id)`` with
   ``a.puuid < b.puuid``, so two friends count only when they were on the SAME team, and
   each pair appears once. Players on opposite teams never form a pair.

"Who carries whom" only uses shared games where BOTH players have a score from the active
model (``scored_games``); ``avg_ai_a``, ``avg_ai_b`` and ``avg_score_diff`` are averaged
over exactly those games, so ``avg_ai_a - avg_ai_b == avg_score_diff``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, Select, and_, false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hextrack.api.schemas import (
    LeaderboardQueue,
    SquadPair,
    SquadPairs,
    SquadPlayer,
    StatsSince,
)
from hextrack.config import Settings
from hextrack.db.models import Summoner
from hextrack.stats import queries
from hextrack.stats.aggregate import stat_rows
from hextrack.stats.filters import SQUAD_MIN_GAMES, queue_ids, since_cutoff
from hextrack.stats.metrics import (
    clamp_rate,
    rounded,
    safe_div,
    to_int,
    to_optional_float,
    winrate,
)


@dataclass(slots=True, frozen=True)
class _PlayerTotals:
    games: int = 0
    wins: int = 0
    avg_ai_score: float | None = None

    @property
    def raw_winrate(self) -> float:
        return safe_div(self.wins, self.games)


def _scored_by(
    model_version_column: ColumnElement[str | None],
    ai_score_column: ColumnElement[float | None],
    version: str | None,
) -> ColumnElement[bool]:
    """The line has a score from ``version`` (never true when no model is active)."""
    if version is None:
        return false()
    return and_(model_version_column == version, ai_score_column.is_not(None))


async def _player_totals(
    session: AsyncSession, rows: Select, *, model_version: str | None
) -> dict[str, _PlayerTotals]:
    sq = rows.subquery("rows")
    scored = _scored_by(sq.c.model_version, sq.c.ai_score, model_version)
    stmt = select(
        sq.c.puuid,
        func.count().label("games"),
        func.count().filter(sq.c.win.is_(True)).label("wins"),
        func.avg(sq.c.ai_score).filter(scored).label("ai_score"),
    ).group_by(sq.c.puuid)
    return {
        row["puuid"]: _PlayerTotals(
            games=to_int(row["games"]),
            wins=to_int(row["wins"]),
            avg_ai_score=clamp_rate(to_optional_float(row["ai_score"])),
        )
        for row in (await session.execute(stmt)).mappings()
    }


def _pairs_statement(rows: Select, *, model_version: str | None) -> Select:
    """One row per (a, b) roster pair that shared a team at least once, a < b."""
    cte = rows.cte("rows")
    a, b = cte.alias("a"), cte.alias("b")
    both_scored = and_(
        _scored_by(a.c.model_version, a.c.ai_score, model_version),
        _scored_by(b.c.model_version, b.c.ai_score, model_version),
    )
    games = func.count()
    wins = func.count().filter(a.c.win.is_(True))
    return (
        select(
            a.c.puuid.label("a_puuid"),
            b.c.puuid.label("b_puuid"),
            games.label("games"),
            wins.label("wins"),
            func.avg(a.c.ai_score).filter(both_scored).label("avg_ai_a"),
            func.avg(b.c.ai_score).filter(both_scored).label("avg_ai_b"),
            func.count().filter(both_scored).label("scored_games"),
            func.count().filter(both_scored, a.c.ai_score > b.c.ai_score).label("a_higher"),
            func.count().filter(both_scored, a.c.ai_score < b.c.ai_score).label("b_higher"),
            func.count().filter(both_scored, a.c.ai_score == b.c.ai_score).label("ties"),
            func.avg(a.c.ai_score - b.c.ai_score).filter(both_scored).label("avg_score_diff"),
        )
        .select_from(
            a.join(
                b,
                and_(
                    b.c.match_id == a.c.match_id,
                    b.c.team_id == a.c.team_id,
                    # Byte order ("C"), not the database collation: it matches Python and
                    # JS string comparison and is the same on every server.
                    a.c.puuid.collate("C") < b.c.puuid.collate("C"),
                ),
            )
        )
        .group_by(a.c.puuid, b.c.puuid)
        .order_by(games.desc(), wins.desc(), a.c.puuid.collate("C"), b.c.puuid.collate("C"))
    )


def _clamp_diff(value: float | None) -> float | None:
    """Clamp a signed score/rate difference into [-1, 1] (None stays None)."""
    if value is None:
        return None
    return min(1.0, max(-1.0, float(value)))


def _player_sort_key(player: SquadPlayer) -> tuple[int, int, str, str, str]:
    """Most games first, then more wins, then Riot ID (case-insensitive)."""
    return (
        -player.games,
        -player.wins,
        player.game_name.casefold(),
        player.tag_line.casefold(),
        player.puuid,
    )


async def squad_pairs(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    model_version: str | None,
) -> SquadPairs:
    """Duo synergy and who carries whom for every pair of tracked players."""
    roster: list[Summoner] = await queries.tracked_summoners(session)
    players: list[SquadPlayer] = []
    pairs: list[SquadPair] = []
    if roster:
        rows = stat_rows(
            queues=queue_ids(queue),
            since=since_cutoff(settings, since),
            puuids=[s.puuid for s in roster],
        )
        totals = await _player_totals(session, rows, model_version=model_version)
        for summoner in roster:
            t = totals.get(summoner.puuid) or _PlayerTotals()
            players.append(
                SquadPlayer(
                    puuid=summoner.puuid,
                    game_name=summoner.game_name,
                    tag_line=summoner.tag_line,
                    profile_icon_id=summoner.profile_icon_id,
                    games=t.games,
                    wins=t.wins,
                    winrate=winrate(t.wins, t.games),
                    avg_ai_score=t.avg_ai_score,
                )
            )
        players.sort(key=_player_sort_key)

        result = await session.execute(_pairs_statement(rows, model_version=model_version))
        for row in result.mappings():
            games, wins = to_int(row["games"]), to_int(row["wins"])
            a_totals = totals.get(row["a_puuid"]) or _PlayerTotals()
            b_totals = totals.get(row["b_puuid"]) or _PlayerTotals()
            raw_winrate = safe_div(wins, games)
            raw_expected = (a_totals.raw_winrate + b_totals.raw_winrate) / 2
            scored_games = to_int(row["scored_games"])
            pairs.append(
                SquadPair(
                    a_puuid=row["a_puuid"],
                    b_puuid=row["b_puuid"],
                    games=games,
                    wins=wins,
                    winrate=winrate(wins, games),
                    expected_winrate=rounded(clamp_rate(raw_expected) or 0.0),
                    winrate_delta=rounded(_clamp_diff(raw_winrate - raw_expected) or 0.0),
                    avg_ai_a=clamp_rate(to_optional_float(row["avg_ai_a"])),
                    avg_ai_b=clamp_rate(to_optional_float(row["avg_ai_b"])),
                    scored_games=scored_games,
                    a_higher=to_int(row["a_higher"]),
                    b_higher=to_int(row["b_higher"]),
                    ties=to_int(row["ties"]),
                    avg_score_diff=(
                        _clamp_diff(to_optional_float(row["avg_score_diff"]))
                        if scored_games
                        else None
                    ),
                )
            )
    return SquadPairs(
        since=since,
        season_start=settings.season_start,
        queue=queue,
        model_version=model_version,
        min_games=SQUAD_MIN_GAMES,
        players=players,
        pairs=pairs,
    )
