"""Pure translation of a match-v5 payload into ``matches`` / ``match_participants`` rows.

Nothing is stored unless :func:`map_match` succeeds, which is what keeps Riot error bodies
(``{"status": {"status_code": 429, ...}}``) and truncated payloads out of the database.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

CLASSIC: Final = "CLASSIC"
#: Arena (queues 1700 / 1710): eight two-player subteams, not two teams of five. Riot still
#: puts ``teamId`` 100 on placements 1-4 and 200 on 5-8; the real team is
#: ``playerSubteamId``.
CHERRY: Final = "CHERRY"
GAME_COMPLETE: Final = "GameComplete"
#: Games shorter than this with no endOfGameResult are treated as incomplete / remakes.
MIN_COMPLETE_DURATION_SECONDS: Final = 300
#: A game this short is a remake even when no one formally early-surrendered: nobody played
#: a real game, and the stats, the AI Score and the bot all have to agree on that.
REMAKE_MAX_SECONDS: Final = 300
CLASSIC_PARTICIPANTS: Final = 10

VALID_POSITIONS: Final[frozenset[str]] = frozenset({"TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"})
UNKNOWN_POSITION: Final = "UNKNOWN"

#: Counted once each (the legacy model double-counted getBackPings).
PING_FIELDS: Final[tuple[str, ...]] = (
    "holdPings",
    "getBackPings",
    "onMyWayPings",
    "needVisionPings",
    "enemyMissingPings",
    "enemyVisionPings",
)
ITEM_FIELDS: Final[tuple[str, ...]] = tuple(f"item{i}" for i in range(7))

#: match_participants column -> match-v5 participant field, for plain integer stats
#: (missing or null -> 0).
INT_STATS: Final[dict[str, str]] = {
    "champ_level": "champLevel",
    "kills": "kills",
    "deaths": "deaths",
    "assists": "assists",
    "double_kills": "doubleKills",
    "triple_kills": "tripleKills",
    "quadra_kills": "quadraKills",
    "penta_kills": "pentaKills",
    "largest_multi_kill": "largestMultiKill",
    "largest_killing_spree": "largestKillingSpree",
    "killing_sprees": "killingSprees",
    "longest_time_spent_living": "longestTimeSpentLiving",
    "total_time_spent_dead": "totalTimeSpentDead",
    "gold_earned": "goldEarned",
    "gold_spent": "goldSpent",
    "total_minions_killed": "totalMinionsKilled",
    "neutral_minions_killed": "neutralMinionsKilled",
    "total_ally_jungle_minions_killed": "totalAllyJungleMinionsKilled",
    "total_enemy_jungle_minions_killed": "totalEnemyJungleMinionsKilled",
    "total_damage_dealt": "totalDamageDealt",
    "total_damage_dealt_to_champions": "totalDamageDealtToChampions",
    "physical_damage_dealt_to_champions": "physicalDamageDealtToChampions",
    "magic_damage_dealt_to_champions": "magicDamageDealtToChampions",
    "true_damage_dealt_to_champions": "trueDamageDealtToChampions",
    "total_damage_taken": "totalDamageTaken",
    "damage_self_mitigated": "damageSelfMitigated",
    "damage_dealt_to_objectives": "damageDealtToObjectives",
    "damage_dealt_to_buildings": "damageDealtToBuildings",
    "damage_dealt_to_turrets": "damageDealtToTurrets",
    "vision_score": "visionScore",
    "wards_placed": "wardsPlaced",
    "wards_killed": "wardsKilled",
    "vision_wards_bought": "visionWardsBoughtInGame",
    "detector_wards_placed": "detectorWardsPlaced",
    "time_ccing_others": "timeCCingOthers",
    "total_time_cc_dealt": "totalTimeCCDealt",
    "total_heal": "totalHeal",
    "total_heals_on_teammates": "totalHealsOnTeammates",
    "total_damage_shielded_on_teammates": "totalDamageShieldedOnTeammates",
    "turret_kills": "turretKills",
    "turret_takedowns": "turretTakedowns",
    "inhibitor_kills": "inhibitorKills",
    "inhibitor_takedowns": "inhibitorTakedowns",
    "dragon_kills": "dragonKills",
    "baron_kills": "baronKills",
    "summoner1_id": "summoner1Id",
    "summoner2_id": "summoner2Id",
}
#: match_participants column -> participant field, booleans (missing -> False).
BOOL_STATS: Final[dict[str, str]] = {
    "first_blood_kill": "firstBloodKill",
    "first_tower_kill": "firstTowerKill",
    "game_ended_in_early_surrender": "gameEndedInEarlySurrender",
    "game_ended_in_surrender": "gameEndedInSurrender",
}
#: Participant fields that must be present (a payload without them is not a real match).
REQUIRED_PARTICIPANT_FIELDS: Final[tuple[str, ...]] = (
    "puuid",
    "teamId",
    "championId",
    "win",
    "kills",
    "deaths",
    "assists",
)
REQUIRED_INFO_FIELDS: Final[tuple[str, ...]] = (
    "gameMode",
    "gameVersion",
    "gameDuration",
    "gameStartTimestamp",
    "queueId",
    "participants",
)


class InvalidMatchPayload(ValueError):
    """The payload is not a complete match-v5 match (error body, truncated JSON, ...)."""


@dataclass(slots=True)
class MappedMatch:
    """Rows ready for insertion.

    ``match`` holds every ``matches`` column (including ``raw``, the unmodified payload);
    ``participants`` holds one dict of ``match_participants`` columns per player, ordered by
    participant_id. AI columns (ai_score, ai_scored_at, model_version) are not set here.
    """

    match: dict[str, Any]
    participants: list[dict[str, Any]] = field(default_factory=list)

    @property
    def match_id(self) -> str:
        return str(self.match["match_id"])


# --- small typed accessors ---------------------------------------------------------------


def _int(obj: Mapping[str, Any], key: str, *, where: str, default: int = 0) -> int:
    value = obj.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise InvalidMatchPayload(f"{where}.{key} must be an integer, got {value!r}")


def _required_int(obj: Mapping[str, Any], key: str, *, where: str) -> int:
    if obj.get(key) is None:
        raise InvalidMatchPayload(f"{where}.{key} is missing")
    return _int(obj, key, where=where)


def _positive_or_none(obj: Mapping[str, Any], key: str, *, where: str) -> int | None:
    """An integer field that Riot fills with 0 when it does not apply."""
    value = _int(obj, key, where=where)
    return value if value > 0 else None


def _bool(obj: Mapping[str, Any], key: str, *, where: str) -> bool:
    value = obj.get(key)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise InvalidMatchPayload(f"{where}.{key} must be a boolean, got {value!r}")


def _str(obj: Mapping[str, Any], key: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _mapping(obj: object, where: str) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise InvalidMatchPayload(f"{where} must be an object")
    return obj


# --- derived values ------------------------------------------------------------------------


def patch_from_version(game_version: str) -> str:
    """``"16.17.712.5021"`` -> ``"16.17"``."""
    parts = game_version.strip().split(".")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        raise InvalidMatchPayload(f"unrecognised gameVersion {game_version!r}")
    return f"{int(parts[0])}.{int(parts[1])}"


def ms_to_datetime(ms: int) -> datetime:
    """Epoch milliseconds -> tz-aware UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def normalize_position(value: str | None) -> str:
    if value and value.upper() in VALID_POSITIONS:
        return value.upper()
    return UNKNOWN_POSITION


def pings_total(participant: Mapping[str, Any]) -> int:
    where = "participant"
    return sum(_int(participant, key, where=where) for key in PING_FIELDS)


def game_duration_seconds(info: Mapping[str, Any]) -> int:
    """info.gameDuration in seconds (pre-11.20 payloads without gameEndTimestamp used ms)."""
    duration = _required_int(info, "gameDuration", where="info")
    if "gameEndTimestamp" not in info and duration > 10 * 60 * 60:
        duration //= 1000
    if duration < 0:
        raise InvalidMatchPayload("info.gameDuration is negative")
    return duration


def _perks(participant: Mapping[str, Any]) -> tuple[int | None, int | None]:
    perks = participant.get("perks")
    if not isinstance(perks, Mapping):
        return None, None
    styles = perks.get("styles")
    if not isinstance(styles, list):
        return None, None
    primary: int | None = None
    secondary: int | None = None
    if styles and isinstance(styles[0], Mapping):
        selections = styles[0].get("selections")
        if isinstance(selections, list) and selections and isinstance(selections[0], Mapping):
            perk = selections[0].get("perk")
            primary = perk if isinstance(perk, int) else None
    if len(styles) > 1 and isinstance(styles[1], Mapping):
        style = styles[1].get("style")
        secondary = style if isinstance(style, int) else None
    return primary, secondary


# --- public API ----------------------------------------------------------------------------


def map_participant(
    participant: Mapping[str, Any],
    *,
    index: int,
    match_id: str,
    game_start: datetime,
    queue_id: int,
) -> dict[str, Any]:
    """Map one ``info.participants[index]`` entry to a match_participants row dict."""
    where = f"info.participants[{index}]"
    p = _mapping(participant, where)
    for key in REQUIRED_PARTICIPANT_FIELDS:
        if p.get(key) is None:
            raise InvalidMatchPayload(f"{where}.{key} is missing")
    puuid = _str(p, "puuid")
    if puuid is None:
        raise InvalidMatchPayload(f"{where}.puuid is empty")

    game_name = _str(p, "riotIdGameName") or _str(p, "summonerName")
    tagline = _str(p, "riotIdTagline")
    champion_name = _str(p, "championName")
    if champion_name is None:
        raise InvalidMatchPayload(f"{where}.championName is missing")

    items = [_int(p, key, where=where) for key in ITEM_FIELDS]
    primary_rune, secondary_style = _perks(p)

    row: dict[str, Any] = {
        "match_id": match_id,
        "puuid": puuid,
        "participant_id": _int(p, "participantId", where=where, default=index + 1),
        "team_id": _required_int(p, "teamId", where=where),
        "game_start": game_start,
        "queue_id": queue_id,
        "riot_id_game_name": game_name,
        "riot_id_tagline": tagline,
        "profile_icon_id": p.get("profileIcon") if isinstance(p.get("profileIcon"), int) else None,
        "summoner_level": (
            p.get("summonerLevel") if isinstance(p.get("summonerLevel"), int) else None
        ),
        "champion_id": _required_int(p, "championId", where=where),
        "champion_name": champion_name,
        "team_position": normalize_position(_str(p, "teamPosition")),
        # Arena only; Riot sends 0 in every other mode.
        "player_subteam_id": _positive_or_none(p, "playerSubteamId", where=where),
        "placement": _positive_or_none(p, "placement", where=where),
        "win": _bool(p, "win", where=where),
        "pings_total": pings_total(p),
        "items": items,
        "primary_rune_id": primary_rune,
        "secondary_style_id": secondary_style,
    }
    for column, key in INT_STATS.items():
        row[column] = _int(p, key, where=where)
    for column, key in BOOL_STATS.items():
        row[column] = _bool(p, key, where=where)
    return row


def map_match(raw: Mapping[str, Any]) -> MappedMatch:
    """Validate and map a raw match-v5 payload. Raises :class:`InvalidMatchPayload`."""
    root = _mapping(raw, "payload")
    if "status" in root and "info" not in root:
        status = root.get("status")
        raise InvalidMatchPayload(f"payload is a Riot error body: {status!r}")
    metadata = _mapping(root.get("metadata"), "metadata")
    info = _mapping(root.get("info"), "info")

    match_id = _str(metadata, "matchId")
    if match_id is None:
        raise InvalidMatchPayload("metadata.matchId is missing")
    for key in REQUIRED_INFO_FIELDS:
        if info.get(key) is None:
            raise InvalidMatchPayload(f"info.{key} is missing")

    game_mode = str(info["gameMode"])
    game_version = str(info["gameVersion"])
    queue_id = _required_int(info, "queueId", where="info")
    start_ms = _required_int(info, "gameStartTimestamp", where="info")
    if start_ms <= 0:
        raise InvalidMatchPayload("info.gameStartTimestamp is not a valid timestamp")
    game_start = ms_to_datetime(start_ms)
    duration = game_duration_seconds(info)

    raw_participants = info["participants"]
    if not isinstance(raw_participants, list) or not raw_participants:
        raise InvalidMatchPayload("info.participants must be a non-empty list")
    if game_mode == CLASSIC and len(raw_participants) != CLASSIC_PARTICIPANTS:
        raise InvalidMatchPayload(
            f"CLASSIC match must have {CLASSIC_PARTICIPANTS} participants, "
            f"got {len(raw_participants)}"
        )

    participants = [
        map_participant(p, index=i, match_id=match_id, game_start=game_start, queue_id=queue_id)
        for i, p in enumerate(raw_participants)
    ]
    puuids = [p["puuid"] for p in participants]
    if len(set(puuids)) != len(puuids):
        raise InvalidMatchPayload("info.participants contains duplicate puuids")
    participants.sort(key=lambda row: row["participant_id"])

    match_row: dict[str, Any] = {
        "match_id": match_id,
        "platform_id": _str(info, "platformId"),
        "queue_id": queue_id,
        "game_mode": game_mode,
        "game_type": _str(info, "gameType"),
        "game_version": game_version,
        "patch": patch_from_version(game_version),
        "game_start": game_start,
        "game_duration": duration,
        "end_of_game_result": _str(info, "endOfGameResult"),
        "remake": (
            any(p["game_ended_in_early_surrender"] for p in participants)
            or duration < REMAKE_MAX_SECONDS
        ),
        "raw": dict(root),
    }
    return MappedMatch(match=match_row, participants=participants)


def _get(match: Mapping[str, Any] | object, key: str) -> Any:
    if isinstance(match, Mapping):
        return match.get(key)
    return getattr(match, key, None)


def is_scorable(match: Mapping[str, Any] | object) -> bool:
    """True when the AI Score applies: a completed Summoner's Rift (CLASSIC) game.

    Accepts a ``MappedMatch.match`` dict or a ``Match`` ORM row. Remakes are never
    scorable, and ``remake`` covers games shorter than :data:`REMAKE_MAX_SECONDS` (see
    :func:`map_match`), which is the same rule match history and the season stats use. A
    missing ``end_of_game_result`` (older payloads) counts as complete when the game lasted
    longer than 300 s.
    """
    if _get(match, "game_mode") != CLASSIC or _get(match, "remake"):
        return False
    result = _get(match, "end_of_game_result")
    if result is None:
        duration = _get(match, "game_duration")
        return isinstance(duration, int) and duration > MIN_COMPLETE_DURATION_SECONDS
    return result == GAME_COMPLETE
