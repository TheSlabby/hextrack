"""Builders for realistic match-v5 payloads (every field ``hextrack.ingest.mapping`` reads).

Typical use::

    raw = make_match_json(
        "NA1_1",
        [spec("puuid-me", "Me", "NA1", kills=12, deaths=1)],  # rest auto-filled
        start=datetime(2026, 3, 1, 20, tzinfo=UTC),
    )

Participants 0-4 are team 100 (blue), 5-9 team 200 (red). ``winning_team`` decides ``win``.
Numbers are deterministic functions of the participant index so tests are reproducible.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

POSITIONS: tuple[str, ...] = ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
#: (champion id, Data Dragon key) per slot.
CHAMPIONS: tuple[tuple[int, str], ...] = (
    (266, "Aatrox"),
    (64, "LeeSin"),
    (103, "Ahri"),
    (222, "Jinx"),
    (412, "Thresh"),
    (122, "Darius"),
    (76, "Nidalee"),
    (61, "Orianna"),
    (51, "Caitlyn"),
    (117, "Lulu"),
)
ITEM_BUILDS: tuple[tuple[int, ...], ...] = (
    (6692, 3047, 6333, 3071, 1053, 0, 3340),
    (6693, 3158, 3071, 3814, 2021, 0, 3364),
    (3152, 3020, 4645, 3089, 3135, 1082, 3340),
    (6672, 3006, 3031, 3094, 3036, 1038, 3363),
    (3877, 3117, 3190, 3109, 2065, 0, 3364),
)
DEFAULT_START = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)


@dataclass(slots=True)
class ParticipantSpec:
    """What a test cares about for one player; everything else is generated.

    ``overrides`` is merged last into the raw participant dict (camelCase Riot keys).
    """

    puuid: str
    game_name: str | None = None
    tag_line: str | None = None
    champion_id: int | None = None
    champion_name: str | None = None
    team_position: str | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    overrides: dict[str, Any] = field(default_factory=dict)


def spec(
    puuid: str,
    game_name: str | None = None,
    tag_line: str | None = None,
    *,
    champion: tuple[int, str] | None = None,
    position: str | None = None,
    kills: int | None = None,
    deaths: int | None = None,
    assists: int | None = None,
    **overrides: Any,
) -> ParticipantSpec:
    """Shorthand for :class:`ParticipantSpec`; extra kwargs become raw-field overrides."""
    return ParticipantSpec(
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        champion_id=champion[0] if champion else None,
        champion_name=champion[1] if champion else None,
        team_position=position,
        kills=kills,
        deaths=deaths,
        assists=assists,
        overrides=dict(overrides),
    )


def filler_puuid(match_id: str, index: int) -> str:
    return f"filler-{match_id}-{index}"


def filler_specs(match_id: str, count: int = 10, *, offset: int = 0) -> list[ParticipantSpec]:
    """Anonymous players for slots a test does not care about."""
    return [
        ParticipantSpec(
            puuid=filler_puuid(match_id, i),
            game_name=f"Filler{i}",
            tag_line="FILL",
        )
        for i in range(offset, offset + count)
    ]


def make_participant(
    index: int,
    ps: ParticipantSpec,
    *,
    duration_s: int,
    winning_team: int,
) -> dict[str, Any]:
    """One raw match-v5 participant for slot ``index`` (0-9)."""
    team_id = 100 if index < 5 else 200
    slot = index % 5
    champ_id, champ_name = CHAMPIONS[index % len(CHAMPIONS)]
    position = ps.team_position or POSITIONS[slot]
    minutes = duration_s / 60
    kills = ps.kills if ps.kills is not None else 2 + (index * 3) % 8
    deaths = ps.deaths if ps.deaths is not None else 1 + (index * 5) % 7
    assists = ps.assists if ps.assists is not None else 3 + (index * 7) % 11
    jungle = position == "JUNGLE"
    support = position == "UTILITY"
    cs = int((1.5 if jungle else 1.0 if support else 7.2) * minutes) + index
    neutral = int(5.4 * minutes) if jungle else index % 3
    gold = int((260 if support else 400) * minutes) + 150 * kills + 80 * assists
    damage = int((650 if support else 900 + 40 * slot) * minutes) + 300 * kills
    items = ITEM_BUILDS[slot]
    raw: dict[str, Any] = {
        "puuid": ps.puuid,
        "participantId": index + 1,
        "teamId": team_id,
        "riotIdGameName": ps.game_name if ps.game_name is not None else f"Player{index}",
        "riotIdTagline": ps.tag_line if ps.tag_line is not None else "NA1",
        "summonerName": "",
        "profileIcon": 4000 + index,
        "summonerLevel": 100 + index * 11,
        "championId": ps.champion_id if ps.champion_id is not None else champ_id,
        "championName": ps.champion_name if ps.champion_name is not None else champ_name,
        "champLevel": 12 + (index % 6),
        "teamPosition": position,
        "individualPosition": position,
        "win": team_id == winning_team,
        "gameEndedInEarlySurrender": False,
        "gameEndedInSurrender": False,
        "kills": kills,
        "deaths": deaths,
        "assists": assists,
        "firstBloodKill": index == 2,
        "firstTowerKill": index == 0,
        "doubleKills": 1 if kills >= 6 else 0,
        "tripleKills": 1 if kills >= 9 else 0,
        "quadraKills": 1 if kills >= 12 else 0,
        "pentaKills": 1 if kills >= 15 else 0,
        "largestMultiKill": min(5, 1 + kills // 3) if kills else 0,
        "largestKillingSpree": max(0, kills - 2),
        "killingSprees": kills // 3,
        "longestTimeSpentLiving": max(60, 700 - 40 * deaths),
        "totalTimeSpentDead": 30 * deaths,
        "goldEarned": gold,
        "goldSpent": int(gold * 0.93),
        "totalMinionsKilled": cs,
        "neutralMinionsKilled": neutral,
        "totalAllyJungleMinionsKilled": int(neutral * 0.8) if jungle else 0,
        "totalEnemyJungleMinionsKilled": int(neutral * 0.2) if jungle else 0,
        "totalDamageDealt": damage * 4,
        "totalDamageDealtToChampions": damage,
        "physicalDamageDealtToChampions": int(damage * 0.6),
        "magicDamageDealtToChampions": int(damage * 0.3),
        "trueDamageDealtToChampions": damage - int(damage * 0.6) - int(damage * 0.3),
        "totalDamageTaken": int(800 * minutes) + 500 * deaths,
        "damageSelfMitigated": int(500 * minutes),
        "damageDealtToObjectives": int((900 if jungle else 250) * minutes),
        "damageDealtToBuildings": int(120 * minutes),
        "damageDealtToTurrets": int(120 * minutes),
        "visionScore": int((2.5 if support else 0.8) * minutes),
        "wardsPlaced": int((1.1 if support else 0.35) * minutes),
        "wardsKilled": int((0.3 if support else 0.1) * minutes),
        "visionWardsBoughtInGame": 6 if support else 2,
        "detectorWardsPlaced": 6 if support else 2,
        "timeCCingOthers": 10 + 3 * index,
        "totalTimeCCDealt": 150 + 20 * index,
        "totalHeal": 1500 + 100 * index,
        "totalHealsOnTeammates": 2500 if support else 0,
        "totalDamageShieldedOnTeammates": 3000 if support else 0,
        "turretKills": 1 if slot in (0, 3) else 0,
        "turretTakedowns": 3 if team_id == winning_team else 1,
        "inhibitorKills": 1 if slot == 3 and team_id == winning_team else 0,
        "inhibitorTakedowns": 1 if team_id == winning_team else 0,
        "dragonKills": 2 if jungle else 0,
        "baronKills": 1 if jungle and team_id == winning_team else 0,
        "holdPings": index % 3,
        "getBackPings": index % 2,
        "onMyWayPings": 2 + index % 4,
        "needVisionPings": index % 2,
        "enemyMissingPings": 1 + index % 5,
        "enemyVisionPings": index % 3,
        "commandPings": 2,
        "allInPings": 0,
        "item0": items[0],
        "item1": items[1],
        "item2": items[2],
        "item3": items[3],
        "item4": items[4],
        "item5": items[5],
        "item6": items[6],
        "summoner1Id": 4,
        "summoner2Id": 11 if jungle else 14 if slot == 2 else 7 if slot == 3 else 12,
        "perks": {
            "statPerks": {"defense": 5011, "flex": 5008, "offense": 5005},
            "styles": [
                {
                    "description": "primaryStyle",
                    "style": 8000,
                    "selections": [{"perk": 8010, "var1": 0, "var2": 0, "var3": 0}],
                },
                {
                    "description": "subStyle",
                    "style": 8400,
                    "selections": [{"perk": 8444, "var1": 0, "var2": 0, "var3": 0}],
                },
            ],
        },
        "timePlayed": duration_s,
    }
    raw.update(ps.overrides)
    return raw


def _objective(first: bool, kills: int) -> dict[str, Any]:
    return {"first": first, "kills": kills}


def make_teams(participants: Sequence[dict[str, Any]], winning_team: int) -> list[dict[str, Any]]:
    teams = []
    for team_id, bans in ((100, (157, 238, 84, -1, 350)), (200, (67, 555, 11, 145, 360))):
        won = team_id == winning_team
        kills = sum(p["kills"] for p in participants if p["teamId"] == team_id)
        teams.append(
            {
                "teamId": team_id,
                "win": won,
                "bans": [{"championId": c, "pickTurn": i + 1} for i, c in enumerate(bans)],
                "objectives": {
                    "atakhan": _objective(won, 1 if won else 0),
                    "baron": _objective(won, 1 if won else 0),
                    "champion": _objective(team_id == 100, kills),
                    "dragon": _objective(won, 3 if won else 1),
                    "horde": _objective(not won, 2 if won else 4),
                    "inhibitor": _objective(won, 2 if won else 0),
                    "riftHerald": _objective(won, 1 if won else 0),
                    "tower": _objective(won, 9 if won else 3),
                },
            }
        )
    return teams


def make_match_json(
    match_id: str,
    participants_spec: Sequence[ParticipantSpec] = (),
    *,
    queue_id: int = 420,
    duration_s: int = 1800,
    start: datetime | None = None,
    game_version: str = "16.17.712.5021",
    game_mode: str = "CLASSIC",
    winning_team: int = 100,
    end_of_game_result: str | None = "GameComplete",
    remake: bool = False,
) -> dict[str, Any]:
    """A complete match-v5 payload with 10 participants.

    ``participants_spec`` fills slots in order (0-4 blue, 5-9 red); missing slots get
    filler players. ``remake=True`` marks everyone ``gameEndedInEarlySurrender``.
    """
    if len(participants_spec) > 10:
        raise ValueError("at most 10 participants")
    start = start or DEFAULT_START
    specs = list(participants_spec)
    specs += filler_specs(match_id, 10 - len(specs), offset=len(specs))
    participants = [
        make_participant(i, ps, duration_s=duration_s, winning_team=winning_team)
        for i, ps in enumerate(specs)
    ]
    if remake:
        for p in participants:
            p["gameEndedInEarlySurrender"] = True
            p["teamEarlySurrendered"] = p["teamId"] != winning_team
    start_ms = int(start.timestamp() * 1000)
    platform, _, game_id = match_id.partition("_")
    info: dict[str, Any] = {
        "gameCreation": start_ms - 60_000,
        "gameDuration": duration_s,
        "gameEndTimestamp": start_ms + duration_s * 1000,
        "gameId": int(game_id) if game_id.isdigit() else 0,
        "gameMode": game_mode,
        "gameName": f"teambuilder-match-{game_id or match_id}",
        "gameStartTimestamp": start_ms,
        "gameType": "MATCHED_GAME",
        "gameVersion": game_version,
        "mapId": 11,
        "participants": participants,
        "platformId": platform or "NA1",
        "queueId": queue_id,
        "teams": make_teams(participants, winning_team),
        "tournamentCode": "",
    }
    if end_of_game_result is not None:
        info["endOfGameResult"] = end_of_game_result
    return {
        "metadata": {
            "dataVersion": "2",
            "matchId": match_id,
            "participants": [p["puuid"] for p in participants],
        },
        "info": info,
    }


def match_series(
    puuid: str,
    count: int,
    *,
    game_name: str = "Tester",
    tag_line: str = "NA1",
    start: datetime | None = None,
    spacing: timedelta = timedelta(hours=1),
    queue_id: int = 420,
    prefix: str = "NA1_",
    first_id: int = 5_000_000_000,
) -> list[dict[str, Any]]:
    """``count`` matches featuring ``puuid`` in slot 0, oldest first, alternating wins."""
    start = start or DEFAULT_START
    return [
        make_match_json(
            f"{prefix}{first_id + i}",
            [spec(puuid, game_name, tag_line)],
            queue_id=queue_id,
            start=start + spacing * i,
            winning_team=100 if i % 2 == 0 else 200,
        )
        for i in range(count)
    ]
