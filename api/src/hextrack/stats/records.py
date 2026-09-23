"""Single-game records and the pentakill hall of fame (``GET /api/v1/records``).

Which games count: ranked Summoner's Rift lines (``queue`` filter: 420 / 440), remakes
excluded, games started at or after the ``since`` cutoff (:mod:`hextrack.stats.filters`).
Scope "roster" = every tracked player's lines; scope "player" = one puuid's lines (tracked
or not). Names are the players' current Riot IDs (``summoners``).

Rules per category (all in :data:`CATEGORIES`, in :data:`RecordKey` order):

* A record must be greater than zero (a 0-kill game is nobody's "most kills").
* ``best_kda``: (kills + assists) / max(deaths, 1), only games with at least
  :data:`KDA_MIN_TAKEDOWNS` takedowns (kills + assists).
* ``highest_kill_participation``: (kills + assists) / team kills, capped at 1, only games
  where the player's team got at least :data:`KP_MIN_TEAM_KILLS` kills.
* ``fastest_win``: wins only; lower is better (the only such category).
* ``highest_ai_score``: only scores from the active model (``model_version``); none when
  no model is active.
* ``longest_game`` and ``fastest_win`` describe the match, so a match is listed once even
  when several tracked players were in it (the lowest participant id is shown).
* Ties: the earlier game ranks first (then match id, then puuid, so the order is stable).
  ``rank`` is the 1-based position in that order.

Pentakills: every game with at least one, newest first (``value`` = pentakills in that game).
Quadrakills: players with at least one quadra kill that did not become a pentakill (Riot's
``quadraKills`` minus ``pentaKills``, since Riot counts every penta as a quadra too), most
first.

Three small queries: the players in scope (with their current Riot IDs), one ``UNION ALL``
of a top-``limit`` branch per category plus the pentakill branch over a shared CTE, and the
quadrakill totals.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, get_args

from sqlalchemy import (
    CTE,
    ColumnElement,
    Float,
    Select,
    and_,
    bindparam,
    cast,
    false,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hextrack.api.schemas import (
    LeaderboardQueue,
    QuadrakillCount,
    RecordCategory,
    RecordEntry,
    RecordKey,
    Records,
    RecordScope,
    RecordUnit,
    StatsSince,
)
from hextrack.config import Settings
from hextrack.db.models import Match, MatchParticipant, Summoner
from hextrack.stats import queries
from hextrack.stats.filters import queue_ids, since_cutoff
from hextrack.stats.metrics import rounded, to_int

#: best_kda only counts games with at least this many kills + assists.
KDA_MIN_TAKEDOWNS: Final = 5
#: highest_kill_participation only counts games where the team got at least this many kills.
KP_MIN_TEAM_KILLS: Final = 10
#: Most participants of one match: a per-match category over-fetches by this factor.
MAX_PARTICIPANTS: Final = 10
#: Branch key of the pentakill list inside the UNION ALL (not a RecordKey).
_PENTAKILLS: Final = "_pentakills"

Condition = Callable[[CTE, str | None], ColumnElement[bool]]
Value = Callable[[CTE], ColumnElement[float]]


@dataclass(frozen=True, slots=True)
class Category:
    key: RecordKey
    label: str
    unit: RecordUnit
    value: Value
    #: Extra qualification besides "value > 0"; gets the base CTE and the model version.
    where: Condition | None = None
    higher_is_better: bool = True
    #: One entry per match (a property of the game, not of a player's line).
    per_match: bool = False
    #: Round the value to 4 decimals (ratios and per-minute rates; AI Scores are returned as
    #: stored, like everywhere else).
    fractional: bool = False


def _per_minute(value: ColumnElement[int], duration: ColumnElement[int]) -> ColumnElement[float]:
    return cast(value, Float) * 60.0 / func.nullif(duration, 0)


def _kda(b: CTE) -> ColumnElement[float]:
    return cast(b.c.kills + b.c.assists, Float) / func.greatest(b.c.deaths, 1)


def _kill_participation(b: CTE) -> ColumnElement[float]:
    return func.least(cast(b.c.kills + b.c.assists, Float) / func.nullif(b.c.team_kills, 0), 1.0)


def _scored_by_active(b: CTE, version: str | None) -> ColumnElement[bool]:
    if version is None:
        return false()
    return and_(b.c.model_version == version, b.c.ai_score.is_not(None))


CATEGORIES: Final[tuple[Category, ...]] = (
    Category("most_kills", "Most kills", "count", lambda b: b.c.kills),
    Category("most_assists", "Most assists", "count", lambda b: b.c.assists),
    Category("most_deaths", "Most deaths", "count", lambda b: b.c.deaths),
    Category(
        "best_kda",
        "Best KDA",
        "number",
        _kda,
        where=lambda b, _v: b.c.kills + b.c.assists >= KDA_MIN_TAKEDOWNS,
        fractional=True,
    ),
    Category("most_damage", "Most damage to champions", "count", lambda b: b.c.damage),
    Category(
        "highest_damage_per_min",
        "Highest damage per minute",
        "per_min",
        lambda b: _per_minute(b.c.damage, b.c.duration),
        fractional=True,
    ),
    Category("most_cs", "Most CS", "count", lambda b: b.c.cs),
    Category(
        "highest_cs_per_min",
        "Highest CS per minute",
        "per_min",
        lambda b: _per_minute(b.c.cs, b.c.duration),
        fractional=True,
    ),
    Category("most_gold", "Most gold", "count", lambda b: b.c.gold),
    Category("highest_vision", "Highest vision score", "count", lambda b: b.c.vision_score),
    Category(
        "highest_kill_participation",
        "Highest kill participation",
        "percent",
        _kill_participation,
        where=lambda b, _v: b.c.team_kills >= KP_MIN_TEAM_KILLS,
        fractional=True,
    ),
    Category("longest_game", "Longest game", "duration", lambda b: b.c.duration, per_match=True),
    Category(
        "fastest_win",
        "Fastest win",
        "duration",
        lambda b: b.c.duration,
        where=lambda b, _v: b.c.win.is_(True),
        higher_is_better=False,
        per_match=True,
    ),
    Category(
        "highest_ai_score",
        "Highest AI Score",
        "score",
        lambda b: b.c.ai_score,
        where=_scored_by_active,
    ),
    Category(
        "largest_killing_spree", "Largest killing spree", "count", lambda b: b.c.killing_spree
    ),
    Category("most_damage_taken", "Most damage taken", "count", lambda b: b.c.damage_taken),
    Category("most_healing", "Most healing", "count", lambda b: b.c.healing),
)
_BY_KEY: Final[dict[str, Category]] = {c.key: c for c in CATEGORIES}
assert tuple(_BY_KEY) == get_args(RecordKey), "CATEGORIES must follow the RecordKey order"


# --- SQL -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scope:
    """Whose lines count and which games: resolved before any statement is built."""

    #: puuid -> (current game name, tag line); the roster, or the one player.
    players: dict[str, tuple[str, str]]
    queues: tuple[int, ...]
    since: datetime | None
    #: True for scope "player": the team aggregate is limited to that player's matches.
    single_player: bool = False


async def load_scope(
    session: AsyncSession,
    *,
    queues: Sequence[int],
    since: datetime | None,
    puuid: str | None,
) -> Scope:
    """The tracked roster (``puuid`` None) or one known player, with current Riot IDs."""
    stmt = select(Summoner.puuid, Summoner.game_name, Summoner.tag_line)
    if puuid is None:
        stmt = stmt.where(Summoner.is_tracked.is_(True))
    else:
        stmt = stmt.where(Summoner.puuid == puuid)
    players = {row[0]: (row[1], row[2]) for row in (await session.execute(stmt)).all()}
    return Scope(
        players=players,
        queues=tuple(sorted(queues)),
        since=since,
        single_player=puuid is not None,
    )


def _in_scope(puuid_column: ColumnElement[str], scope: Scope) -> ColumnElement[bool]:
    """``puuid IN (...)`` with the puuids rendered into the SQL text. As bind parameters,
    asyncpg's cached statement switches to a generic plan after five runs, which cannot
    tell a friend with a thousand games from a stranger with one and runs 5-10x slower.
    (The puuids come from ``summoners``; SQLAlchemy quotes them.)"""
    return puuid_column.in_(
        bindparam(
            "scope_puuids",
            sorted(scope.players),
            expanding=True,
            literal_execute=True,
            unique=True,
        )
    )


def _in_queues(queue_column: ColumnElement[int], scope: Scope) -> ColumnElement[bool]:
    """``queue_id IN (...)`` rendered into the SQL text, for the same reason as
    :func:`_in_scope`: under the generic plan the planner badly misjudges how many rows the
    queue filter keeps and falls back to a seq scan with one index probe per row."""
    return queue_column.in_(
        bindparam(
            "scope_queues", list(scope.queues), expanding=True, literal_execute=True, unique=True
        )
    )


def _since_literal(scope: Scope) -> ColumnElement[datetime]:
    """The season cutoff rendered into the SQL text (see :func:`_in_queues`)."""
    return bindparam(
        "scope_since",
        scope.since,
        type_=MatchParticipant.game_start.type,
        literal_execute=True,
        unique=True,
    )


def team_totals(scope: Scope) -> Select:
    """One row per (match, team) of the counted games: the team's total kills (all five
    players) and the game's duration. Doubles as the queue / period / remake filter, and is
    one hash aggregate however the planner misjudges the roster's share of the table."""
    team = aliased(MatchParticipant, name="team")
    stmt = (
        select(
            team.match_id,
            team.team_id,
            func.sum(team.kills).label("team_kills"),
            Match.game_duration.label("duration"),
        )
        .join(Match, Match.match_id == team.match_id)
        .where(_in_queues(team.queue_id, scope), queries.not_remake())
        .group_by(team.match_id, team.team_id, Match.game_duration)
    )
    if scope.since is not None:
        stmt = stmt.where(team.game_start >= _since_literal(scope))
    if scope.single_player:
        mine = aliased(MatchParticipant, name="mine")
        stmt = stmt.where(
            team.match_id.in_(select(mine.match_id).where(_in_scope(mine.puuid, scope)))
        )
    return stmt


def scoped_rows(scope: Scope) -> Select:
    """The lines in scope with every column a category reads (plus ``team_kills`` and
    ``duration`` from :func:`team_totals`)."""
    mp = MatchParticipant
    team = team_totals(scope).subquery("team_totals")
    stmt = (
        select(
            mp.match_id,
            mp.puuid,
            mp.participant_id,
            mp.team_id,
            mp.game_start,
            mp.win,
            mp.champion_name,
            mp.kills,
            mp.deaths,
            mp.assists,
            mp.total_damage_dealt_to_champions.label("damage"),
            (mp.total_minions_killed + mp.neutral_minions_killed).label("cs"),
            mp.gold_earned.label("gold"),
            mp.vision_score,
            mp.largest_killing_spree.label("killing_spree"),
            mp.total_damage_taken.label("damage_taken"),
            mp.total_heal.label("healing"),
            mp.penta_kills,
            mp.ai_score,
            mp.model_version,
            team.c.team_kills,
            team.c.duration,
        )
        .join(team, and_(team.c.match_id == mp.match_id, team.c.team_id == mp.team_id))
        .where(_in_scope(mp.puuid, scope), _in_queues(mp.queue_id, scope))
    )
    if scope.since is not None:
        stmt = stmt.where(mp.game_start >= _since_literal(scope))
    return stmt


def _entry_columns(source: CTE, key: str, value: ColumnElement[float]) -> list[ColumnElement]:
    c = source.c
    return [
        literal(key).label("key"),
        cast(value, Float).label("value"),
        c.puuid,
        c.participant_id,
        c.champion_name,
        c.match_id,
        c.game_start,
        c.win,
    ]


def category_branch(
    base: CTE, category: Category, *, limit: int, model_version: str | None
) -> Select:
    """Top lines of one category, best first (ties: earlier game first). A per-match
    category fetches ``limit * 10`` lines (at most ten per match) so that
    :func:`records` can keep one line per match."""
    value = category.value(base)
    condition = value > 0
    if category.where is not None:
        condition = and_(condition, category.where(base, model_version))
    direction = value.desc() if category.higher_is_better else value.asc()
    tie_break = base.c.participant_id if category.per_match else base.c.puuid
    return (
        select(*_entry_columns(base, category.key, value))
        .where(condition)
        .order_by(direction, base.c.game_start, base.c.match_id, tie_break)
        .limit(limit * MAX_PARTICIPANTS if category.per_match else limit)
    )


def pentakill_branch(base: CTE) -> Select:
    return select(*_entry_columns(base, _PENTAKILLS, base.c.penta_kills)).where(
        base.c.penta_kills > 0
    )


def records_statement(scope: Scope, *, limit: int, model_version: str | None) -> Select:
    """The single UNION ALL behind every category and the pentakill list."""
    base = scoped_rows(scope).cte("base")
    branches = [
        category_branch(base, category, limit=limit, model_version=model_version)
        for category in CATEGORIES
    ]
    branches.append(pentakill_branch(base))
    # Each branch keeps its own ORDER BY / LIMIT inside a subquery.
    return union_all(*(select(branch.subquery()) for branch in branches))  # type: ignore[return-value]


def quadrakill_statement(scope: Scope) -> Select:
    """puuid -> quadra kills that did not become pentakills, over the counted games (players
    with none left out). Riot's multikill counters nest (a pentakill also adds one to
    ``quadraKills``), so the pentakills are subtracted per line."""
    mp = MatchParticipant
    total = func.sum(mp.quadra_kills - mp.penta_kills)
    stmt = (
        select(mp.puuid, total.label("count"))
        .join(Match, Match.match_id == mp.match_id)
        .where(
            _in_scope(mp.puuid, scope),
            _in_queues(mp.queue_id, scope),
            queries.not_remake(),
        )
        .group_by(mp.puuid)
        .having(total > 0)
    )
    if scope.since is not None:
        stmt = stmt.where(mp.game_start >= _since_literal(scope))
    return stmt


# --- assembly -------------------------------------------------------------------------------


def _sort_key(category: Category, row: RowMapping) -> tuple[float, datetime, str, str | int]:
    """Best first; ties: earlier game, then match id, then puuid (participant id for a
    per-match category), exactly as in the SQL."""
    value = float(row["value"])
    primary = -value if category.higher_is_better else value
    tie_break = row["participant_id"] if category.per_match else row["puuid"]
    return (primary, row["game_start"], row["match_id"], tie_break)


def _one_per_match(rows: Sequence[RowMapping]) -> list[RowMapping]:
    seen: set[str] = set()
    kept = []
    for row in rows:
        if row["match_id"] not in seen:
            seen.add(row["match_id"])
            kept.append(row)
    return kept


def _newest_first(row: RowMapping) -> tuple[datetime, str, str]:
    return (row["game_start"], row["match_id"], row["puuid"])


def _entry(rank: int, row: RowMapping, scope: Scope, *, fractional: bool) -> RecordEntry:
    value = float(row["value"])
    game_name, tag_line = scope.players[row["puuid"]]
    return RecordEntry(
        rank=rank,
        value=rounded(value) if fractional else value,
        puuid=row["puuid"],
        game_name=game_name,
        tag_line=tag_line,
        champion_name=row["champion_name"],
        match_id=row["match_id"],
        game_start=row["game_start"],
        win=bool(row["win"]),
    )


def _category(
    category: Category, rows: Sequence[RowMapping], scope: Scope, *, limit: int
) -> RecordCategory:
    ordered = sorted(rows, key=lambda row: _sort_key(category, row))
    if category.per_match:
        ordered = _one_per_match(ordered)
    return RecordCategory(
        key=category.key,
        label=category.label,
        unit=category.unit,
        higher_is_better=category.higher_is_better,
        entries=[
            _entry(rank, row, scope, fractional=category.fractional)
            for rank, row in enumerate(ordered[:limit], start=1)
        ],
    )


def _quadrakill_sort_key(item: QuadrakillCount) -> tuple[int, str, str, str]:
    return (-item.count, item.game_name.casefold(), item.tag_line.casefold(), item.puuid)


async def records(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: LeaderboardQueue,
    puuid: str | None,
    limit: int,
    model_version: str | None,
) -> Records:
    """Records of the roster (``puuid`` None) or of one player (three small queries)."""
    scope = await load_scope(
        session, queues=queue_ids(queue), since=since_cutoff(settings, since), puuid=puuid
    )
    grouped: dict[str, list[RowMapping]] = defaultdict(list)
    quadrakills: list[QuadrakillCount] = []
    if scope.players:
        statement = records_statement(scope, limit=limit, model_version=model_version)
        for row in (await session.execute(statement)).mappings():
            grouped[row["key"]].append(row)
        for row in (await session.execute(quadrakill_statement(scope))).mappings():
            game_name, tag_line = scope.players[row["puuid"]]
            quadrakills.append(
                QuadrakillCount(
                    puuid=row["puuid"],
                    game_name=game_name,
                    tag_line=tag_line,
                    count=to_int(row["count"]),
                )
            )
        quadrakills.sort(key=_quadrakill_sort_key)
    pentas = sorted(grouped.get(_PENTAKILLS, []), key=_newest_first, reverse=True)
    record_scope: RecordScope = "roster" if puuid is None else "player"
    return Records(
        since=since,
        queue=queue,
        scope=record_scope,
        puuid=puuid,
        model_version=model_version,
        limit=limit,
        categories=[
            _category(category, grouped.get(category.key, []), scope, limit=limit)
            for category in CATEGORIES
        ],
        pentakills=[
            _entry(rank, row, scope, fractional=False) for rank, row in enumerate(pentas, start=1)
        ],
        quadrakills=quadrakills,
    )


__all__ = [
    "CATEGORIES",
    "Category",
    "KDA_MIN_TAKEDOWNS",
    "KP_MIN_TEAM_KILLS",
    "Scope",
    "category_branch",
    "load_scope",
    "quadrakill_statement",
    "records",
    "records_statement",
    "scoped_rows",
    "team_totals",
]
