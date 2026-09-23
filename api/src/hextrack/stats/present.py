"""Pure conversion of database rows into :mod:`hextrack.api.schemas` response models.

Nothing here touches the database. Participant rows are mappings keyed by the
``match_participants`` column names selected in :data:`hextrack.stats.queries.
PARTICIPANT_COLUMNS` plus ``is_tracked``; match headers are mappings of ``matches`` columns.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final, get_args

from hextrack.api.schemas import (
    MatchDetail,
    MatchSummary,
    ObjectiveStat,
    ParticipantSummary,
    Position,
    RankEntry,
    RankPoint,
    TeamDetail,
    TeamObjectives,
    TeamSummary,
)
from hextrack.db.models import RankSnapshot
from hextrack.queues import queue_label
from hextrack.rank import APEX_TIERS, DIVISION_ORDER, RANKED_QUEUE_TYPES, normalize_tier
from hextrack.stats.metrics import (
    clamp_rate,
    game_kda,
    is_remake,
    kill_participation,
    per_minute,
    winrate,
)

if TYPE_CHECKING:
    from hextrack.stats.role_percentile import RolePercentileTable

logger = logging.getLogger(__name__)

#: Blue then red; participants on any other team id are not shown. Arena uses these two ids
#: as well (100 = placements 1-4, 200 = 5-8), so those matches still have two "teams" here;
#: the duo a player really played with is ``ParticipantSummary.subteam_id``.
TEAM_IDS: Final[tuple[int, int]] = (100, 200)
ITEM_SLOTS: Final = 7
MAX_MULTIKILL: Final = 5
MAX_AI_RANK: Final = 10
_POSITIONS: Final[frozenset[str]] = frozenset(get_args(Position))

Row = Mapping[str, Any]


def normalize_position(value: str | None) -> Position:
    """A stored ``team_position`` as the API enum (anything unexpected -> UNKNOWN)."""
    return value if value in _POSITIONS else "UNKNOWN"  # type: ignore[return-value]


# --- ranks -----------------------------------------------------------------------------------


def _tier_and_division(snapshot: RankSnapshot) -> tuple[str, str | None] | None:
    """Validated (tier, division) or None for a row the API cannot represent."""
    try:
        tier = normalize_tier(snapshot.tier)
    except ValueError:
        logger.warning("ignoring rank snapshot %s with unknown tier %r", snapshot.id, snapshot.tier)
        return None
    if tier in APEX_TIERS:
        return tier, None
    division = (snapshot.rank or "").strip().upper()
    if division not in DIVISION_ORDER:
        logger.warning(
            "ignoring rank snapshot %s with unknown division %r", snapshot.id, snapshot.rank
        )
        return None
    return tier, division


def rank_entry(snapshot: RankSnapshot | None) -> RankEntry | None:
    """Latest standing in one queue, or None (no snapshot / unrepresentable row)."""
    if snapshot is None or snapshot.queue_type not in RANKED_QUEUE_TYPES:
        return None
    parsed = _tier_and_division(snapshot)
    if parsed is None:
        return None
    tier, division = parsed
    return RankEntry(
        queue_type=snapshot.queue_type,  # type: ignore[arg-type]
        tier=tier,  # type: ignore[arg-type]
        rank=division,  # type: ignore[arg-type]
        lp=snapshot.lp,
        wins=snapshot.wins,
        losses=snapshot.losses,
        winrate=winrate(snapshot.wins, snapshot.wins + snapshot.losses),
        rank_value=snapshot.rank_value,
        taken_at=snapshot.taken_at,
    )


def rank_point(snapshot: RankSnapshot) -> RankPoint | None:
    parsed = _tier_and_division(snapshot)
    if parsed is None:
        return None
    tier, division = parsed
    return RankPoint(
        taken_at=snapshot.taken_at,
        tier=tier,  # type: ignore[arg-type]
        rank=division,  # type: ignore[arg-type]
        lp=snapshot.lp,
        rank_value=snapshot.rank_value,
        wins=snapshot.wins,
        losses=snapshot.losses,
    )


# --- participants ----------------------------------------------------------------------------


def side_of(row: Row) -> int:
    """The group a player's kill participation is measured against.

    Arena puts eight two-player subteams into ``team_id`` 100 (placements 1-4) and 200
    (5-8), so the only real "team" there is ``player_subteam_id``. Summing kills over
    ``team_id`` would divide by four unrelated duos' kills.
    """
    subteam = row.get("player_subteam_id")
    if subteam is not None:
        return int(subteam)
    return int(row["team_id"])


def team_kill_totals(rows: Sequence[Row]) -> dict[int, int]:
    """side (team id, or Arena subteam id) -> total champion kills."""
    totals: dict[int, int] = {}
    for row in rows:
        side = side_of(row)
        totals[side] = totals.get(side, 0) + int(row["kills"])
    return totals


def ai_ranks(rows: Sequence[Row]) -> dict[str, int]:
    """puuid -> 1-based rank by AI Score within one match (1 = best); unscored players are
    left out. Ties are broken by participant id so ranks are unique."""
    scored = [row for row in rows if row["ai_score"] is not None]
    scored.sort(key=lambda row: (-float(row["ai_score"]), int(row["participant_id"])))
    return {
        row["puuid"]: index for index, row in enumerate(scored, start=1) if index <= MAX_AI_RANK
    }


def _items(value: Sequence[int] | None) -> list[int]:
    items = [int(item or 0) for item in (value or ())][:ITEM_SLOTS]
    return items + [0] * (ITEM_SLOTS - len(items))


def participant_summary(
    row: Row,
    *,
    duration_seconds: int,
    team_kills: int,
    ai_rank: int | None,
    ai_role_percentile: float | None = None,
) -> ParticipantSummary:
    kills, deaths, assists = int(row["kills"]), int(row["deaths"]), int(row["assists"])
    cs = int(row["total_minions_killed"]) + int(row["neutral_minions_killed"])
    gold = int(row["gold_earned"])
    damage = int(row["total_damage_dealt_to_champions"])
    subteam = row.get("player_subteam_id")
    placement = row.get("placement")
    return ParticipantSummary(
        puuid=row["puuid"],
        game_name=row["riot_id_game_name"],
        tag_line=row["riot_id_tagline"],
        participant_id=int(row["participant_id"]),
        team_id=int(row["team_id"]),  # type: ignore[arg-type]
        subteam_id=int(subteam) if subteam is not None else None,
        placement=int(placement) if placement is not None else None,
        team_position=normalize_position(row["team_position"]),
        champion_id=int(row["champion_id"]),
        champion_name=row["champion_name"],
        champ_level=int(row["champ_level"]),
        win=bool(row["win"]),
        kills=kills,
        deaths=deaths,
        assists=assists,
        kda=game_kda(kills, deaths, assists),
        kill_participation=kill_participation(kills, assists, team_kills),
        cs=cs,
        cs_per_min=per_minute(cs, duration_seconds),
        gold=gold,
        gold_per_min=per_minute(gold, duration_seconds),
        damage_to_champions=damage,
        damage_per_min=per_minute(damage, duration_seconds),
        damage_taken=int(row["total_damage_taken"]),
        vision_score=int(row["vision_score"]),
        wards_placed=int(row["wards_placed"]),
        wards_killed=int(row["wards_killed"]),
        control_wards=int(row["vision_wards_bought"]),
        items=_items(row["items"]),
        summoner1_id=int(row["summoner1_id"]),
        summoner2_id=int(row["summoner2_id"]),
        largest_multikill=min(MAX_MULTIKILL, max(0, int(row["largest_multi_kill"]))),
        ai_score=clamp_rate(row["ai_score"]),
        ai_rank=ai_rank,
        is_tracked=bool(row["is_tracked"]),
        ai_role_percentile=ai_role_percentile,
    )


def participant_summaries(
    rows: Sequence[Row],
    duration_seconds: int,
    role_percentiles: RolePercentileTable | None = None,
) -> list[ParticipantSummary]:
    """All participants of one match on a real team (100 / 200), by participant id.
    ``role_percentiles`` fills ``ai_role_percentile`` (rows need ``model_version``)."""
    rows = sorted(
        (row for row in rows if row["team_id"] in TEAM_IDS),
        key=lambda row: int(row["participant_id"]),
    )
    kills = team_kill_totals(rows)
    ranks = ai_ranks(rows)
    return [
        participant_summary(
            row,
            duration_seconds=duration_seconds,
            team_kills=kills.get(side_of(row), 0),
            ai_rank=ranks.get(row["puuid"]),
            ai_role_percentile=(
                role_percentiles.for_row(
                    row["team_position"], row["ai_score"], row.get("model_version")
                )
                if role_percentiles is not None
                else None
            ),
        )
        for row in rows
    ]


def _team_totals(team_id: int, members: Sequence[ParticipantSummary]) -> dict[str, Any]:
    return {
        "team_id": team_id,
        "win": any(p.win for p in members),
        "kills": sum(p.kills for p in members),
        "deaths": sum(p.deaths for p in members),
        "assists": sum(p.assists for p in members),
        "gold": sum(p.gold for p in members),
        "damage_to_champions": sum(p.damage_to_champions for p in members),
        "participants": list(members),
    }


def _by_team(summaries: Sequence[ParticipantSummary]) -> list[tuple[int, list[ParticipantSummary]]]:
    """(team_id, members) for every team with players, blue first."""
    teams: list[tuple[int, list[ParticipantSummary]]] = []
    for team_id in TEAM_IDS:
        members = [p for p in summaries if p.team_id == team_id]
        if members:
            teams.append((team_id, members))
    return teams


def team_summaries(summaries: Sequence[ParticipantSummary]) -> list[TeamSummary]:
    return [
        TeamSummary(**_team_totals(team_id, members)) for team_id, members in _by_team(summaries)
    ]


def match_summary(
    header: Row,
    rows: Sequence[Row],
    puuid: str,
    role_percentiles: RolePercentileTable | None = None,
) -> MatchSummary | None:
    """One match-history item from the ``matches`` header and all participant rows; None
    when ``puuid`` is not on a real team in this match."""
    duration = int(header["game_duration"])
    summaries = participant_summaries(rows, duration, role_percentiles)
    me = next((p for p in summaries if p.puuid == puuid), None)
    if me is None:
        return None
    return MatchSummary(
        match_id=header["match_id"],
        queue_id=int(header["queue_id"]),
        queue_label=queue_label(int(header["queue_id"])),
        game_mode=header["game_mode"],
        game_start=header["game_start"],
        game_duration=duration,
        patch=header["patch"],
        remake=is_remake(header["remake"], duration),
        me=me,
        teams=team_summaries(summaries),
    )


# --- match detail ----------------------------------------------------------------------------

#: TeamObjectives field -> match-v5 ``teams[].objectives`` key.
OBJECTIVE_KEYS: Final[dict[str, str]] = {
    "baron": "baron",
    "dragon": "dragon",
    "rift_herald": "riftHerald",
    "horde": "horde",
    "tower": "tower",
    "inhibitor": "inhibitor",
    "champion": "champion",
}


def _objective(value: Any) -> ObjectiveStat | None:
    if not isinstance(value, Mapping):
        return None
    kills = value.get("kills")
    return ObjectiveStat(
        first=value.get("first") is True,
        kills=int(kills) if isinstance(kills, int | float) and not isinstance(kills, bool) else 0,
    )


def team_objectives(raw_team: Mapping[str, Any] | None) -> TeamObjectives:
    """Objectives of one ``info.teams[]`` entry; missing objectives count as 0 / not first
    (``horde`` is absent before 2024), ``atakhan`` stays None when absent (before 2025)."""
    raw = raw_team.get("objectives") if isinstance(raw_team, Mapping) else None
    objectives: Mapping[str, Any] = raw if isinstance(raw, Mapping) else {}
    values = {
        field: _objective(objectives.get(key)) or ObjectiveStat(first=False, kills=0)
        for field, key in OBJECTIVE_KEYS.items()
    }
    return TeamObjectives(**values, atakhan=_objective(objectives.get("atakhan")))


def team_bans(raw_team: Mapping[str, Any] | None) -> list[int]:
    """Banned champion ids in pick-turn order (-1 = no ban)."""
    bans = raw_team.get("bans") if isinstance(raw_team, Mapping) else None
    if not isinstance(bans, list):
        return []
    valid = [
        ban for ban in bans if isinstance(ban, Mapping) and isinstance(ban.get("championId"), int)
    ]
    valid.sort(key=lambda ban: ban.get("pickTurn") if isinstance(ban.get("pickTurn"), int) else 0)
    return [int(ban["championId"]) for ban in valid]


def _raw_teams_by_id(raw_teams: Any) -> dict[int, Mapping[str, Any]]:
    if not isinstance(raw_teams, list):
        return {}
    return {
        team["teamId"]: team
        for team in raw_teams
        if isinstance(team, Mapping) and isinstance(team.get("teamId"), int)
    }


def match_detail(
    header: Row, rows: Sequence[Row], role_percentiles: RolePercentileTable | None = None
) -> MatchDetail:
    """Full match view. ``header`` also carries ``raw_teams`` (``matches.raw -> info ->
    teams``), the only part of the raw payload the API reads."""
    duration = int(header["game_duration"])
    summaries = participant_summaries(rows, duration, role_percentiles)
    raw_teams = _raw_teams_by_id(header.get("raw_teams"))
    teams = [
        TeamDetail(
            **_team_totals(team_id, members),
            objectives=team_objectives(raw_teams.get(team_id)),
            bans=team_bans(raw_teams.get(team_id)),
        )
        for team_id, members in _by_team(summaries)
    ]
    return MatchDetail(
        match_id=header["match_id"],
        queue_id=int(header["queue_id"]),
        queue_label=queue_label(int(header["queue_id"])),
        game_mode=header["game_mode"],
        game_version=header["game_version"],
        patch=header["patch"],
        game_start=header["game_start"],
        game_duration=duration,
        remake=is_remake(header["remake"], duration),
        model_version=header["model_version"],
        teams=teams,
    )
