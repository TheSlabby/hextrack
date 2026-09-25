"""Stacks: games where several roster players were on the same team (a full squad is 5).

A stack is a ``(match_id, team_id)`` with at least ``size`` tracked players, in any stored
queue except Arena and customs (``queue="flex"``: Ranked Flex only), remakes excluded.
Two opposing stacks in one match are two stacks.

The stack set is one SQL statement (:func:`_stack_rows`): the roster's lines from
:func:`hextrack.stats.aggregate.stat_rows` on a real team (100 / 200), with a window count
of roster players per ``(match_id, team_id)`` kept when it reaches ``size``.

* :func:`stack_summary` fetches every stack line (with both teams' kill totals) in one
  query and aggregates in Python: the squad plays hundreds of stacks, not millions.
* :func:`stack_games` pages over distinct matches with a keyset on
  ``(game_start desc, match_id desc)`` (like :func:`hextrack.stats.queries.match_page`), then
  loads every participant of the page's matches for the member lines (kill participation
  and AI rank need all ten). A page is four queries, plus the role-percentile population
  when the process-wide cache is stale.

Verdicts come from :func:`hextrack.stats.verdict.team_verdict`; a member score only counts
when the active model produced it, so a stack with any other member gets no verdict.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from hextrack.api.schemas import (
    StackAward,
    StackAwardKey,
    StackGame,
    StackGamePage,
    StackHighlight,
    StackHighlightKey,
    StackLineup,
    StackPlayer,
    StackQueue,
    StackSummary,
    StackVerdict,
    StatsSince,
)
from hextrack.config import Settings
from hextrack.db.models import Match, MatchParticipant, Summoner
from hextrack.queues import ARENA_QUEUES, CUSTOM_QUEUES, RANKED_FLEX, queue_label
from hextrack.stats import present, queries
from hextrack.stats.aggregate import stat_rows
from hextrack.stats.filters import since_cutoff
from hextrack.stats.metrics import clamp_rate, rounded, safe_div, total_kda, winrate
from hextrack.stats.queries import MatchCursor
from hextrack.stats.role_percentile import ROLE_PERCENTILES, RolePercentileTable
from hextrack.stats.verdict import CARRY_TIERS, RAN_DOWN_TIERS, Verdict, team_verdict

#: A lineup needs this many games together to be "best lineup".
STACK_LINEUP_MIN_GAMES = 5
#: Response limits (mirrored by the schema constraints).
STACK_RECENT_FORM: Final = 20
STACK_TOP_LINEUPS: Final = 10
#: Never a stack: Arena's teams are two-player subteams, customs aren't real games.
EXCLUDED_QUEUES: Final[frozenset[int]] = ARENA_QUEUES | CUSTOM_QUEUES

Row = Mapping[str, Any]


# --- the stack set -----------------------------------------------------------------------------


def _queue_filter(queue: StackQueue) -> tuple[tuple[int, ...] | None, frozenset[int]]:
    """``(queues, exclude_queues)`` arguments of :func:`stat_rows` for a queue filter."""
    if queue == "flex":
        return (RANKED_FLEX,), frozenset()
    return None, EXCLUDED_QUEUES


def _stack_rows(
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    roster: Collection[str],
    cursor: MatchCursor | None = None,
) -> Select:
    """Roster lines that belong to a stack: the :func:`stat_rows` columns plus
    ``participant_id`` and ``stack_size`` (roster players on that team). ``cursor`` keeps
    only matches strictly after it in ``(game_start desc, match_id desc)`` order."""
    queues, excluded = _queue_filter(queue)
    mp = MatchParticipant
    base = (
        stat_rows(
            queues=queues,
            exclude_queues=excluded,
            since=since_cutoff(settings, since),
            puuids=roster,
        )
        .add_columns(mp.participant_id, Match.game_mode)
        .where(mp.team_id.in_(present.TEAM_IDS))
    )
    if cursor is not None:
        # Whole matches drop out, so the per-team counts below are unaffected.
        base = base.where(
            mp.game_start <= cursor.game_start,
            tuple_(mp.game_start, mp.match_id) < tuple_(cursor.game_start, cursor.match_id),
        )
    lines = base.subquery("roster_lines")
    counted = select(
        lines,
        func.count().over(partition_by=(lines.c.match_id, lines.c.team_id)).label("stack_size"),
    ).subquery("counted")
    return select(counted).where(counted.c.stack_size >= size)


def _active_score(row: Row, model_version: str | None) -> float | None:
    """The line's AI Score when the active model produced it, else None."""
    score = row["ai_score"]
    if model_version is None or score is None or row["model_version"] != model_version:
        return None
    return float(score)


def _verdict(members: Sequence[Row], *, win: bool, model_version: str | None) -> Verdict | None:
    """Verdict over the members (lane order); None unless all are scored by the active
    model."""
    return team_verdict(
        [(row["puuid"], _active_score(row, model_version)) for row in members], win=win
    )


def _verdict_model(verdict: Verdict | None) -> StackVerdict | None:
    if verdict is None:
        return None
    return StackVerdict(tier=verdict.tier, target_puuid=verdict.target_puuid, gap=verdict.gap)


@dataclass(slots=True)
class _Stack:
    match_id: str
    team_id: int
    queue_id: int
    game_mode: str
    game_start: datetime
    game_duration: int
    win: bool
    team_kills: int
    enemy_kills: int
    members: list[Row] = field(default_factory=list)
    verdict: Verdict | None = None

    @property
    def member_puuids(self) -> list[str]:
        return [row["puuid"] for row in self.members]


def _newest_first(stacks: Iterable[_Stack]) -> list[_Stack]:
    """``(game_start desc, match_id desc)``, then blue before red."""
    ordered = sorted(stacks, key=lambda s: s.team_id)
    ordered.sort(key=lambda s: (s.game_start, s.match_id), reverse=True)
    return ordered


async def _load_stacks(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    roster: Collection[str],
    model_version: str | None,
) -> list[_Stack]:
    """Every stack in scope with its members and verdict, newest first (one query)."""
    lines = _stack_rows(settings, since=since, queue=queue, size=size, roster=roster).cte(
        "stack_lines"
    )
    mp = aliased(MatchParticipant)
    kills = (
        select(
            mp.match_id,
            func.coalesce(func.sum(mp.kills).filter(mp.team_id == 100), 0).label("blue_kills"),
            func.coalesce(func.sum(mp.kills).filter(mp.team_id == 200), 0).label("red_kills"),
        )
        .where(mp.match_id.in_(select(lines.c.match_id)))
        .group_by(mp.match_id)
        .cte("match_kills")
    )
    stmt = select(lines, kills.c.blue_kills, kills.c.red_kills).join(
        kills, kills.c.match_id == lines.c.match_id
    )
    stacks: dict[tuple[str, int], _Stack] = {}
    for row in (await session.execute(stmt)).mappings():
        team_id = int(row["team_id"])
        key = (row["match_id"], team_id)
        stack = stacks.get(key)
        if stack is None:
            blue, red = int(row["blue_kills"]), int(row["red_kills"])
            stack = stacks[key] = _Stack(
                match_id=row["match_id"],
                team_id=team_id,
                queue_id=int(row["queue_id"]),
                game_mode=row["game_mode"],
                game_start=row["game_start"],
                game_duration=int(row["game_duration"]),
                win=bool(row["win"]),
                team_kills=blue if team_id == 100 else red,
                enemy_kills=red if team_id == 100 else blue,
            )
        stack.members.append(row)
    for stack in stacks.values():
        stack.members.sort(key=lambda r: int(r["participant_id"]))
        stack.verdict = _verdict(stack.members, win=stack.win, model_version=model_version)
    return _newest_first(stacks.values())


# --- summary -----------------------------------------------------------------------------------


@dataclass(slots=True)
class _PlayerAcc:
    games: int = 0
    wins: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    score_sum: float = 0.0
    scored_games: int = 0
    tiers: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    #: champion_id -> [games, newest game_start, name at that game]
    champions: dict[int, list[Any]] = field(default_factory=dict)


@dataclass(slots=True)
class _LineupAcc:
    puuids: tuple[str, ...]
    games: int = 0
    wins: int = 0
    last_played: datetime | None = None

    def model(self) -> StackLineup:
        assert self.last_played is not None
        return StackLineup(
            puuids=list(self.puuids),
            games=self.games,
            wins=self.wins,
            winrate=winrate(self.wins, self.games),
            last_played=self.last_played,
        )


def _accumulate_players(
    stacks: Sequence[_Stack], model_version: str | None
) -> dict[str, _PlayerAcc]:
    players: dict[str, _PlayerAcc] = defaultdict(_PlayerAcc)
    for stack in stacks:
        for row in stack.members:
            acc = players[row["puuid"]]
            acc.games += 1
            acc.wins += int(stack.win)
            acc.kills += int(row["kills"])
            acc.deaths += int(row["deaths"])
            acc.assists += int(row["assists"])
            score = _active_score(row, model_version)
            if score is not None:
                acc.score_sum += score
                acc.scored_games += 1
            champion_id = int(row["champion_id"])
            entry = acc.champions.get(champion_id)
            if entry is None:
                acc.champions[champion_id] = [1, stack.game_start, row["champion_name"]]
            else:
                entry[0] += 1
                if stack.game_start > entry[1]:
                    entry[1], entry[2] = stack.game_start, row["champion_name"]
        verdict = stack.verdict
        if verdict is not None and verdict.target_puuid is not None:
            players[verdict.target_puuid].tiers[verdict.tier] += 1
    return players


def _player(summoner: Summoner, acc: _PlayerAcc) -> StackPlayer:
    tiers = acc.tiers
    top: tuple[int, list[Any]] | None = max(
        acc.champions.items(), key=lambda item: (item[1][0], item[1][1]), default=None
    )
    return StackPlayer(
        puuid=summoner.puuid,
        game_name=summoner.game_name,
        tag_line=summoner.tag_line,
        profile_icon_id=summoner.profile_icon_id,
        games=acc.games,
        wins=acc.wins,
        winrate=winrate(acc.wins, acc.games),
        avg_ai_score=(clamp_rate(acc.score_sum / acc.scored_games) if acc.scored_games else None),
        scored_games=acc.scored_games,
        kills=acc.kills,
        deaths=acc.deaths,
        assists=acc.assists,
        kda=total_kda(acc.kills, acc.deaths, acc.assists),
        hard_carries=tiers["hardCarry"],
        carries=sum(tiers[t] for t in CARRY_TIERS),
        ran_downs=sum(tiers[t] for t in RAN_DOWN_TIERS),
        off_days=tiers["offDay"],
        tried=tiers["tried"],
        top_champion_id=top[0] if top else None,
        top_champion_name=top[1][2] if top else None,
        top_champion_games=top[1][0] if top else 0,
    )


def _riot_id_key(player: StackPlayer) -> tuple[str, str, str]:
    return (player.game_name.casefold(), player.tag_line.casefold(), player.puuid)


def _lineups(stacks: Sequence[_Stack]) -> list[_LineupAcc]:
    by_key: dict[tuple[str, ...], _LineupAcc] = {}
    for stack in stacks:
        key = tuple(sorted(stack.member_puuids))
        acc = by_key.get(key)
        if acc is None:
            acc = by_key[key] = _LineupAcc(key)
        acc.games += 1
        acc.wins += int(stack.win)
        if acc.last_played is None or stack.game_start > acc.last_played:
            acc.last_played = stack.game_start
    return list(by_key.values())


def _played_ts(acc: _LineupAcc) -> float:
    return acc.last_played.timestamp() if acc.last_played else 0.0


def _most_played(lineups: Iterable[_LineupAcc]) -> list[_LineupAcc]:
    """Most games, then more wins, then most recently played."""
    return sorted(lineups, key=lambda a: (-a.games, -a.wins, -_played_ts(a), a.puuids))


def _best(lineups: Iterable[_LineupAcc]) -> _LineupAcc | None:
    """Highest winrate among lineups with enough games; then more games, then newer."""
    eligible = [a for a in lineups if a.games >= STACK_LINEUP_MIN_GAMES]
    eligible.sort(key=lambda a: (-safe_div(a.wins, a.games), -a.games, -_played_ts(a), a.puuids))
    return eligible[0] if eligible else None


AWARDS: Final[tuple[tuple[StackAwardKey, Callable[[StackPlayer], int]], ...]] = (
    ("carry_king", lambda p: p.carries),
    ("ran_it_down", lambda p: p.ran_downs),
    ("tried_their_best", lambda p: p.tried),
)


def _awards(players: Sequence[StackPlayer]) -> list[StackAward]:
    """Most of each count; ties go to fewer games, then Riot ID."""
    awards = []
    for key, count in AWARDS:
        candidates = [p for p in players if count(p) > 0]
        if not candidates:
            continue
        winner = min(candidates, key=lambda p: (-count(p), p.games, *_riot_id_key(p)))
        awards.append(StackAward(key=key, puuid=winner.puuid, count=count(winner)))
    return awards


#: key -> (qualifies, "better" value: lower wins). Ties: earlier game, then match id.
HIGHLIGHTS: Final[
    tuple[tuple[StackHighlightKey, Callable[[_Stack], bool], Callable[[_Stack], int]], ...]
] = (
    ("biggest_stomp", lambda s: s.win, lambda s: -(s.team_kills - s.enemy_kills)),
    ("worst_loss", lambda s: not s.win, lambda s: -(s.enemy_kills - s.team_kills)),
    ("longest_game", lambda s: True, lambda s: -s.game_duration),
    ("fastest_win", lambda s: s.win, lambda s: s.game_duration),
    ("most_team_kills", lambda s: True, lambda s: -s.team_kills),
)


def _highlights(stacks: Sequence[_Stack]) -> list[StackHighlight]:
    """One stack per highlight key; a match appears at most once in the list."""
    used: set[str] = set()
    highlights = []
    for key, qualifies, value in HIGHLIGHTS:
        candidates = [s for s in stacks if s.match_id not in used and qualifies(s)]
        if not candidates:
            continue
        best = min(candidates, key=lambda s: (value(s), s.game_start, s.match_id, s.team_id))
        used.add(best.match_id)
        highlights.append(
            StackHighlight(
                key=key,
                match_id=best.match_id,
                game_start=best.game_start,
                queue_id=best.queue_id,
                queue_label=queue_label(best.queue_id),
                game_mode=best.game_mode,
                win=best.win,
                game_duration=best.game_duration,
                team_kills=best.team_kills,
                enemy_kills=best.enemy_kills,
                member_puuids=best.member_puuids,
            )
        )
    return highlights


def _mean(values: Sequence[float]) -> float | None:
    return rounded(sum(values) / len(values)) if values else None


async def stack_summary(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    model_version: str | None,
) -> StackSummary:
    """Record, averages, per-player numbers, lineups, awards and highlight games."""
    roster = await queries.tracked_summoners(session)
    stacks: list[_Stack] = []
    if roster:
        stacks = await _load_stacks(
            session,
            settings,
            since=since,
            queue=queue,
            size=size,
            roster=[s.puuid for s in roster],
            model_version=model_version,
        )

    accs = _accumulate_players(stacks, model_version)
    players = [_player(s, accs[s.puuid]) for s in roster if s.puuid in accs]
    players.sort(key=lambda p: (-p.games, *_riot_id_key(p)))

    lineups = _most_played(_lineups(stacks))
    best = _best(lineups)
    wins = sum(1 for s in stacks if s.win)
    return StackSummary(
        since=since,
        season_start=settings.season_start,
        queue=queue,
        size=size,
        model_version=model_version,
        min_lineup_games=STACK_LINEUP_MIN_GAMES,
        games=len(stacks),
        wins=wins,
        winrate=winrate(wins, len(stacks)),
        recent_form=[s.win for s in stacks[:STACK_RECENT_FORM]],
        avg_duration=_mean([s.game_duration for s in stacks]),
        avg_team_kills=_mean([s.team_kills for s in stacks]),
        avg_enemy_kills=_mean([s.enemy_kills for s in stacks]),
        verdict_games=sum(1 for s in stacks if s.verdict is not None),
        players=players,
        lineups=[a.model() for a in lineups[:STACK_TOP_LINEUPS]],
        best_lineup=best.model() if best else None,
        most_played_lineup=lineups[0].model() if lineups else None,
        awards=_awards(players),
        highlights=_highlights(stacks),
    )


# --- games -------------------------------------------------------------------------------------


async def stack_games(
    session: AsyncSession,
    settings: Settings,
    *,
    since: StatsSince,
    queue: StackQueue,
    size: int,
    model_version: str | None,
    cursor: MatchCursor | None,
    limit: int,
) -> StackGamePage:
    """Stacks newest first, paged by match (both teams of a match stay on one page)."""
    roster = {s.puuid for s in await queries.tracked_summoners(session)}
    if not roster:
        return StackGamePage(items=[], next_cursor=None)

    lines = _stack_rows(
        settings, since=since, queue=queue, size=size, roster=roster, cursor=cursor
    ).subquery("stack_lines")
    matches = select(lines.c.match_id, lines.c.game_start).distinct().subquery("stack_matches")
    stmt = (
        select(*queries.MATCH_HEADER_COLUMNS, matches.c.game_start.label("sort_start"))
        .join(matches, matches.c.match_id == Match.match_id)
        .order_by(matches.c.game_start.desc(), matches.c.match_id.desc())
        .limit(limit + 1)
    )
    headers = list((await session.execute(stmt)).mappings())
    has_more = len(headers) > limit
    headers = headers[:limit]
    if not headers:
        return StackGamePage(items=[], next_cursor=None)

    participants = await queries.participants_for_matches(session, [h["match_id"] for h in headers])
    table = await ROLE_PERCENTILES.ensure_loaded(session, settings, model_version=model_version)
    items: list[StackGame] = []
    for header in headers:
        items.extend(
            _match_stacks(
                header,
                participants.get(header["match_id"], []),
                roster=roster,
                size=size,
                model_version=model_version,
                table=table,
            )
        )
    next_cursor = (
        queries.encode_cursor(MatchCursor(headers[-1]["sort_start"], headers[-1]["match_id"]))
        if has_more
        else None
    )
    return StackGamePage(items=items, next_cursor=next_cursor)


def _match_stacks(
    header: Row,
    rows: Sequence[Row],
    *,
    roster: Collection[str],
    size: int,
    model_version: str | None,
    table: RolePercentileTable,
) -> list[StackGame]:
    """The qualifying stacks of one match, blue first."""
    duration = int(header["game_duration"])
    rows = [row for row in rows if row["team_id"] in present.TEAM_IDS]
    summaries = {p.puuid: p for p in present.participant_summaries(rows, duration, table)}
    games = []
    for team_id in present.TEAM_IDS:
        team = sorted(
            (row for row in rows if row["team_id"] == team_id),
            key=lambda row: int(row["participant_id"]),
        )
        members = [row for row in team if row["puuid"] in roster]
        if len(members) < size:
            continue
        win = bool(members[0]["win"])
        team_kills = sum(int(row["kills"]) for row in team)
        enemy_kills = sum(int(row["kills"]) for row in rows if row["team_id"] != team_id)
        games.append(
            StackGame(
                match_id=header["match_id"],
                queue_id=int(header["queue_id"]),
                queue_label=queue_label(int(header["queue_id"])),
                game_mode=header["game_mode"],
                game_start=header["game_start"],
                game_duration=duration,
                patch=header["patch"],
                team_id=team_id,  # type: ignore[arg-type]
                win=win,
                team_kills=team_kills,
                enemy_kills=enemy_kills,
                members=[summaries[row["puuid"]] for row in members],
                verdict=_verdict_model(_verdict(members, win=win, model_version=model_version)),
            )
        )
    return games
