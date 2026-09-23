"""Personal insights: tilt detector (sessions), best time to play (schedule), nemesis
champions (matchups) and unlucky losses / lucky wins (luck).

Entry points, called by :mod:`hextrack.api.v1.insights`::

    async def session_insights(session, settings, puuid, *, since, queue, gap_minutes,
                               model_version) -> SessionInsights
    async def schedule_insights(session, settings, puuid, *, since, queue, tz: ZoneInfo,
                                model_version) -> ScheduleInsights
    async def matchup_insights(session, settings, puuid, *, since, queue, min_games,
                               model_version) -> MatchupInsights
    async def luck_insights(session, settings, puuid, *, since, queue, limit,
                            model_version) -> LuckInsights

Every function reads the player's lines from :func:`hextrack.stats.aggregate.stat_rows`, so
"which games count" is the same as everywhere else: ranked queues (narrowed by ``queue``),
``game_start >= season_start`` for ``since="season"``, remakes excluded. AI Scores only
count when scored by ``model_version`` (the active model); other rows are "not scored".
Scores stay on the stored 0..1 scale (the UI shows them x100).

Rules chosen here (the UI copy depends on them):

* Sessions: the ``queue`` filter applies first, so with ``queue=solo`` a session is a run
  of solo games (flex games in between are ignored, not treated as breaks). A session
  continues while ``next.game_start - (prev.game_start + prev.duration) <= gap`` (equal to
  the gap still counts). Streak states only look back inside the same session.
* Schedule: ``game_start`` (UTC) is converted to ``tz`` with zoneinfo, so DST shifts the
  local hour correctly. Windows are three consecutive local hours on one day of week and
  never cross midnight (``start_hour`` 0..21); a window needs ``min_games`` games.
  ``worst_window`` is None unless some window has a lower winrate than ``best_window``.
* Matchups: the lane opponent is the one enemy with the player's ``team_position``; games
  where the position is UNKNOWN, or either team has zero or several players in it, are
  skipped. Nemeses are champions the player has a losing record against (winrate < 50%),
  favorites a winning one (> 50%), so no champion is in both lists; even records are in
  neither.
* Luck: unlucky loss = a loss scored >= ``LUCK_HIGH``; lucky win = a win scored
  <= ``LUCK_LOW``. Ties in score are broken newest game first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from fractions import Fraction
from typing import Final, get_args
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, and_, false, func, select
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hextrack.api.schemas import (
    ChampionMatchup,
    LeaderboardQueue,
    LuckGame,
    LuckInsights,
    MatchupInsights,
    ScheduleCell,
    ScheduleDay,
    ScheduleHour,
    ScheduleInsights,
    ScheduleWindow,
    SessionGameBucket,
    SessionInsights,
    SessionState,
    SessionStateBucket,
    StatsSince,
)
from hextrack.config import Settings
from hextrack.db.models import MatchParticipant
from hextrack.stats import present, role_percentile
from hextrack.stats.aggregate import stat_rows
from hextrack.stats.filters import (
    LUCK_HIGH,
    LUCK_LOW,
    SCHEDULE_MIN_GAMES,
    SESSION_MIN_GAMES,
    queue_ids,
    since_cutoff,
)
from hextrack.stats.metrics import clamp_rate, rounded, safe_div, to_float, to_int, winrate

#: Game-number buckets: 1..5, and 6 = "6th game of the session or later".
SESSION_BUCKETS: Final = 6
SESSION_STATES: Final[tuple[SessionState, ...]] = get_args(SessionState)
DAYS: Final = 7
HOURS: Final = 24
#: Width of a best / worst time window, in hours.
WINDOW_HOURS: Final = 3
#: Most champions per matchup list (mirrors the response schema).
MATCHUP_LIST_MAX: Final = 8
#: Real lane positions; UNKNOWN (Riot's "" / "Invalid") never identifies an opponent.
LANE_POSITIONS: Final[tuple[str, ...]] = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")


# --- shared helpers --------------------------------------------------------------------------


@dataclass(slots=True)
class _Tally:
    """Games, wins and the active-model scores of one bucket."""

    games: int = 0
    wins: int = 0
    scored: int = 0
    score_sum: float = 0.0

    def add(self, win: bool, score: float | None) -> None:
        self.games += 1
        self.wins += int(win)
        if score is not None:
            self.scored += 1
            self.score_sum += score

    @property
    def winrate(self) -> float:
        return winrate(self.wins, self.games)

    @property
    def avg_ai_score(self) -> float | None:
        return clamp_rate(rounded(self.score_sum / self.scored)) if self.scored else None


def _active_score(row: RowMapping, model_version: str | None) -> float | None:
    """The row's AI Score if the active model produced it, else None ("not scored")."""
    if model_version is None or row["model_version"] != model_version:
        return None
    score = row["ai_score"]
    return float(score) if score is not None else None


def _scored_by(
    model_version_column: ColumnElement[str | None], version: str | None
) -> ColumnElement[bool]:
    """SQL condition "scored by ``version``" (never true when there is no version)."""
    return model_version_column == version if version is not None else false()


async def _timeline(
    session: AsyncSession,
    settings: Settings,
    puuid: str,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
) -> list[RowMapping]:
    """The player's counted games, oldest first: game_start, game_duration, win, ai_score,
    model_version."""
    rows = stat_rows(
        queues=queue_ids(queue), since=since_cutoff(settings, since), puuids=[puuid]
    ).subquery("mine")
    stmt = select(
        rows.c.match_id,
        rows.c.game_start,
        rows.c.game_duration,
        rows.c.win,
        rows.c.ai_score,
        rows.c.model_version,
    ).order_by(rows.c.game_start, rows.c.match_id)
    return list((await session.execute(stmt)).mappings())


# --- tilt detector ---------------------------------------------------------------------------


def _next_state(win_before: bool, losses_in_row: int) -> SessionState:
    """State of a game that is not the first of its session, from the game before it."""
    if win_before:
        return "after_win"
    return "after_one_loss" if losses_in_row == 1 else "after_two_plus_losses"


async def session_insights(
    session: AsyncSession,
    settings: Settings,
    puuid: str,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    gap_minutes: int,
    model_version: str | None,
) -> SessionInsights:
    """Win rate and AI Score by game number within a play session and by what happened in
    the previous game of the session (one query, then a single pass in Python)."""
    games = await _timeline(session, settings, puuid, since=since, queue=queue)
    gap = timedelta(minutes=gap_minutes)
    by_number = [_Tally() for _ in range(SESSION_BUCKETS)]
    by_state = {state: _Tally() for state in SESSION_STATES}
    lengths: list[int] = []
    prev: RowMapping | None = None
    losses_in_row = 0
    for game in games:
        if prev is None or (
            game["game_start"] - (prev["game_start"] + timedelta(seconds=prev["game_duration"]))
            > gap
        ):
            lengths.append(0)
            losses_in_row = 0
            state: SessionState = "first_game"
        else:
            state = _next_state(bool(prev["win"]), losses_in_row)
        lengths[-1] += 1
        win, score = bool(game["win"]), _active_score(game, model_version)
        by_number[min(lengths[-1], SESSION_BUCKETS) - 1].add(win, score)
        by_state[state].add(win, score)
        losses_in_row = 0 if win else losses_in_row + 1
        prev = game
    return SessionInsights(
        puuid=puuid,
        since=since,
        queue=queue,
        model_version=model_version,
        gap_minutes=gap_minutes,
        min_games=SESSION_MIN_GAMES,
        sessions=len(lengths),
        games=len(games),
        avg_session_games=rounded(safe_div(len(games), len(lengths))),
        longest_session_games=max(lengths, default=0),
        by_game_number=[
            SessionGameBucket(
                n=n,
                games=t.games,
                wins=t.wins,
                winrate=t.winrate,
                avg_ai_score=t.avg_ai_score,
            )
            for n, t in enumerate(by_number, start=1)
        ],
        by_state=[
            SessionStateBucket(
                state=state,
                games=t.games,
                wins=t.wins,
                winrate=t.winrate,
                avg_ai_score=t.avg_ai_score,
            )
            for state, t in by_state.items()
        ],
    )


# --- best time to play -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Window:
    dow: int
    start: int
    games: int
    wins: int
    #: The window's first hour has games (preferred on ties, so five games at 20:00 give
    #: 20-23 rather than 18-21).
    starts_with_games: bool

    @property
    def rate(self) -> Fraction:
        return Fraction(self.wins, self.games)

    def model(self) -> ScheduleWindow:
        return ScheduleWindow(
            dow=self.dow,
            start_hour=self.start,
            end_hour=self.start + WINDOW_HOURS,
            games=self.games,
            winrate=winrate(self.wins, self.games),
        )


def _windows(
    cells: dict[tuple[int, int], _Tally], min_games: int
) -> tuple[ScheduleWindow | None, ScheduleWindow | None]:
    """Best and worst 3-hour window (same day, never across midnight) with at least
    ``min_games`` games (and at least one). Ties: more games, then a window whose first hour
    has games, then the earlier window. The worst window is None unless its winrate is
    lower than the best one's (otherwise it would repeat the same record)."""
    candidates: list[_Window] = []
    for dow in range(DAYS):
        for start in range(HOURS - WINDOW_HOURS + 1):
            tallies = [cells.get((dow, hour)) for hour in range(start, start + WINDOW_HOURS)]
            games = sum(t.games for t in tallies if t is not None)
            if games >= max(min_games, 1):
                wins = sum(t.wins for t in tallies if t is not None)
                candidates.append(_Window(dow, start, games, wins, tallies[0] is not None))
    if not candidates:
        return None, None

    def tie_break(w: _Window) -> tuple[int, bool, int, int]:
        return (-w.games, not w.starts_with_games, w.dow, w.start)

    best = min(candidates, key=lambda w: (-w.rate, *tie_break(w)))
    worst = min(candidates, key=lambda w: (w.rate, *tie_break(w)))
    return best.model(), (worst.model() if worst.rate < best.rate else None)


async def schedule_insights(
    session: AsyncSession,
    settings: Settings,
    puuid: str,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    tz: ZoneInfo,
    model_version: str | None,
) -> ScheduleInsights:
    """Win rate by local day of week and hour of the game's start in ``tz``."""
    games = await _timeline(session, settings, puuid, since=since, queue=queue)
    cells: dict[tuple[int, int], _Tally] = {}
    days = [_Tally() for _ in range(DAYS)]
    hours = [_Tally() for _ in range(HOURS)]
    for game in games:
        local = game["game_start"].astimezone(tz)
        dow, hour = local.weekday(), local.hour
        win, score = bool(game["win"]), _active_score(game, model_version)
        cells.setdefault((dow, hour), _Tally()).add(win, score)
        days[dow].add(win, score)
        hours[hour].add(win, score)
    best, worst = _windows(cells, SCHEDULE_MIN_GAMES)
    return ScheduleInsights(
        puuid=puuid,
        since=since,
        queue=queue,
        model_version=model_version,
        tz=tz.key,
        min_games=SCHEDULE_MIN_GAMES,
        cells=[
            ScheduleCell(
                dow=dow, hour=hour, games=t.games, wins=t.wins, avg_ai_score=t.avg_ai_score
            )
            for (dow, hour), t in sorted(cells.items())
        ],
        by_dow=[
            ScheduleDay(
                dow=dow,
                games=t.games,
                wins=t.wins,
                winrate=t.winrate,
                avg_ai_score=t.avg_ai_score,
            )
            for dow, t in enumerate(days)
        ],
        by_hour=[
            ScheduleHour(
                hour=hour,
                games=t.games,
                wins=t.wins,
                winrate=t.winrate,
                avg_ai_score=t.avg_ai_score,
            )
            for hour, t in enumerate(hours)
        ],
        best_window=best,
        worst_window=worst,
    )


# --- nemesis champions -----------------------------------------------------------------------


async def matchup_insights(
    session: AsyncSession,
    settings: Settings,
    puuid: str,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    min_games: int,
    model_version: str | None,
) -> MatchupInsights:
    """The player's record against each lane opponent's champion (one query).

    Each of the player's games is joined to everyone in the match with the same position
    and grouped per game: exactly one such player on each team (the player and one enemy)
    identifies the opponent, whose champion and gold the FILTERed aggregates then pick.
    """
    mine = (
        stat_rows(queues=queue_ids(queue), since=since_cutoff(settings, since), puuids=[puuid])
        .add_columns(MatchParticipant.gold_earned.label("gold"))
        .where(MatchParticipant.team_position.in_(LANE_POSITIONS))
        .subquery("mine")
    )
    p = aliased(MatchParticipant, name="p")
    ally, enemy = p.team_id == mine.c.team_id, p.team_id != mine.c.team_id
    lanes = (
        select(
            mine.c.win,
            mine.c.ai_score,
            mine.c.model_version,
            func.max(p.champion_id).filter(enemy).label("champion_id"),
            func.max(p.champion_name).filter(enemy).label("champion_name"),
            (mine.c.gold - func.max(p.gold_earned).filter(enemy)).label("gold_diff"),
        )
        .select_from(mine)
        .join(
            p,
            and_(p.match_id == mine.c.match_id, p.team_position == mine.c.team_position),
        )
        .group_by(
            mine.c.match_id,
            mine.c.win,
            mine.c.ai_score,
            mine.c.model_version,
            mine.c.gold,
        )
        .having(and_(func.count().filter(ally) == 1, func.count().filter(enemy) == 1))
        .subquery("lanes")
    )
    stmt = select(
        lanes.c.champion_id,
        func.max(lanes.c.champion_name).label("champion_name"),
        func.count().label("games"),
        func.count().filter(lanes.c.win.is_(True)).label("wins"),
        func.avg(lanes.c.ai_score)
        .filter(_scored_by(lanes.c.model_version, model_version))
        .label("ai_score"),
        func.avg(lanes.c.gold_diff).label("gold_diff"),
    ).group_by(lanes.c.champion_id)
    rows = list((await session.execute(stmt)).mappings())
    matchups: list[ChampionMatchup] = []
    for row in rows:
        games, wins = to_int(row["games"]), to_int(row["wins"])
        if games < min_games:
            continue
        score = row["ai_score"]
        matchups.append(
            ChampionMatchup(
                champion_id=int(row["champion_id"]),
                champion_name=row["champion_name"],
                games=games,
                wins=wins,
                losses=games - wins,
                winrate=winrate(wins, games),
                avg_ai_score=clamp_rate(rounded(float(score))) if score is not None else None,
                avg_gold_diff=round(to_float(row["gold_diff"]), 1),
            )
        )
    # Exact comparisons (2 * wins vs games) so 50% records are never split by rounding.
    nemeses = sorted(
        (m for m in matchups if 2 * m.wins < m.games),
        key=lambda m: (Fraction(m.wins, m.games), -m.games, m.champion_name),
    )
    favorites = sorted(
        (m for m in matchups if 2 * m.wins > m.games),
        key=lambda m: (-Fraction(m.wins, m.games), -m.games, m.champion_name),
    )
    return MatchupInsights(
        puuid=puuid,
        since=since,
        queue=queue,
        model_version=model_version,
        min_games=min_games,
        total_matchups=sum(to_int(row["games"]) for row in rows),
        nemeses=nemeses[:MATCHUP_LIST_MAX],
        favorites=favorites[:MATCHUP_LIST_MAX],
    )


# --- unlucky losses / lucky wins -------------------------------------------------------------


async def _role_percentiles(
    session: AsyncSession, model_version: str | None, rows: Sequence[RowMapping]
) -> list[float | None]:
    """Score-within-role percentile of each row (None for UNKNOWN positions / no model),
    from the process-wide cache in :mod:`hextrack.stats.role_percentile` (no query when
    there are no rows or the cached population is fresh)."""
    if not rows or model_version is None:
        return [None] * len(rows)
    table = await role_percentile.ROLE_PERCENTILES.ensure_loaded(
        session, model_version=model_version
    )
    return [table.for_row(r["team_position"], r["ai_score"], model_version) for r in rows]


async def luck_insights(
    session: AsyncSession,
    settings: Settings,
    puuid: str,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    limit: int,
    model_version: str | None,
) -> LuckInsights:
    """Losses the player scored high in and wins they scored low in (three small queries)."""
    mine = (
        stat_rows(queues=queue_ids(queue), since=since_cutoff(settings, since), puuids=[puuid])
        .add_columns(MatchParticipant.queue_id)
        .subquery("mine")
    )
    scored = and_(mine.c.ai_score.is_not(None), _scored_by(mine.c.model_version, model_version))
    lost, won = mine.c.win.is_(False), mine.c.win.is_(True)
    unlucky = and_(scored, lost, mine.c.ai_score >= LUCK_HIGH)
    lucky = and_(scored, won, mine.c.ai_score <= LUCK_LOW)
    counts = (
        (
            await session.execute(
                select(
                    func.count().filter(and_(scored, lost)).label("losses_scored"),
                    func.count().filter(unlucky).label("unlucky"),
                    func.count().filter(and_(scored, won)).label("wins_scored"),
                    func.count().filter(lucky).label("lucky"),
                )
            )
        )
        .mappings()
        .one()
    )
    columns = (
        mine.c.match_id,
        mine.c.game_start,
        mine.c.queue_id,
        mine.c.champion_name,
        mine.c.team_position,
        mine.c.kills,
        mine.c.deaths,
        mine.c.assists,
        mine.c.game_duration,
        mine.c.ai_score,
    )
    newest = (mine.c.game_start.desc(), mine.c.match_id.desc())
    unlucky_rows = list(
        (
            await session.execute(
                select(*columns)
                .where(unlucky)
                .order_by(mine.c.ai_score.desc(), *newest)
                .limit(limit)
            )
        ).mappings()
    )
    lucky_rows = list(
        (
            await session.execute(
                select(*columns).where(lucky).order_by(mine.c.ai_score.asc(), *newest).limit(limit)
            )
        ).mappings()
    )
    picked = unlucky_rows + lucky_rows
    percentiles = await _role_percentiles(session, model_version, picked)

    def luck_game(row: RowMapping, percentile: float | None) -> LuckGame:
        return LuckGame(
            match_id=row["match_id"],
            game_start=row["game_start"],
            queue_id=int(row["queue_id"]),
            champion_name=row["champion_name"],
            team_position=present.normalize_position(row["team_position"]),
            kills=int(row["kills"]),
            deaths=int(row["deaths"]),
            assists=int(row["assists"]),
            duration=int(row["game_duration"]),
            ai_score=clamp_rate(float(row["ai_score"])) or 0.0,
            ai_role_percentile=percentile,
        )

    games = [luck_game(r, pct) for r, pct in zip(picked, percentiles, strict=True)]
    return LuckInsights(
        puuid=puuid,
        since=since,
        queue=queue,
        model_version=model_version,
        high_threshold=LUCK_HIGH,
        low_threshold=LUCK_LOW,
        losses_scored=to_int(counts["losses_scored"]),
        unlucky_count=to_int(counts["unlucky"]),
        wins_scored=to_int(counts["wins_scored"]),
        lucky_count=to_int(counts["lucky"]),
        unlucky_losses=games[: len(unlucky_rows)],
        lucky_wins=games[len(unlucky_rows) :],
    )
