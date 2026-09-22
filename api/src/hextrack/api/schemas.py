"""Public API response contract (``/api/v1``).

The frontend generates its TypeScript types from the OpenAPI spec built from these models,
so every field is explicit: snake_case names, tz-aware ISO-8601 datetimes, explicit
nullables and Literal enums. Fields typed ``X | None`` are always present (never omitted).
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

QueueType = Literal["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]
Tier = Literal[
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
]
Division = Literal["I", "II", "III", "IV"]
Position = Literal["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY", "UNKNOWN"]
FeatureGroup = Literal["combat", "economy", "vision", "objectives", "survival", "teamplay"]
LeaderboardQueue = Literal["all", "solo", "flex"]
#: ok / partial / cooldown as in ingest.ondemand; "unavailable": the Riot key is missing or
#: rejected, so a stored player is served from the database without an update.
RefreshStatus = Literal["ok", "cooldown", "partial", "unavailable"]
TeamId = Literal[100, 200]

#: A probability / ratio in [0, 1].
Rate = Annotated[float, Field(ge=0.0, le=1.0)]


class ApiModel(BaseModel):
    """Base for response models: built from dicts or ORM attributes, extra keys rejected."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="forbid",
        # Fields with defaults are still always serialized: mark them required in the
        # (response) JSON schema so generated TypeScript types are non-optional.
        json_schema_serialization_defaults_required=True,
    )


# --- errors ----------------------------------------------------------------------------------


class ErrorResponse(ApiModel):
    detail: str
    #: Machine-readable reason: riot_key, riot_rate_limited, riot_unavailable, not_found,
    #: model_missing, unauthorized, forbidden, invalid_riot_id, ...
    code: str | None = None


# --- ranks -----------------------------------------------------------------------------------


class RankEntry(ApiModel):
    queue_type: QueueType
    tier: Tier
    #: None for MASTER / GRANDMASTER / CHALLENGER.
    rank: Division | None
    lp: int
    wins: int
    losses: int
    winrate: Rate
    rank_value: int
    taken_at: AwareDatetime


class RankPoint(ApiModel):
    taken_at: AwareDatetime
    tier: Tier
    rank: Division | None
    lp: int
    rank_value: int
    wins: int
    losses: int


class RankHistory(ApiModel):
    puuid: str
    queue_type: QueueType
    #: Oldest -> newest.
    points: list[RankPoint]


# --- summoner profile ------------------------------------------------------------------------


class ProfileStats(ApiModel):
    """Season aggregates over ranked queues (420, 440), remakes excluded."""

    games: int
    wins: int
    losses: int
    winrate: Rate
    avg_kills: float
    avg_deaths: float
    avg_assists: float
    #: (kills + assists) / max(deaths, 1) over the totals.
    kda: float
    avg_cs_per_min: float
    avg_damage_per_min: float
    avg_vision_per_min: float
    avg_kill_participation: Rate
    avg_ai_score: Rate | None
    ai_scored_games: int


class ChampionStat(ApiModel):
    champion_id: int
    #: Data Dragon key.
    champion_name: str
    games: int
    wins: int
    winrate: Rate
    kda: float
    avg_ai_score: Rate | None


class RoleStat(ApiModel):
    position: Position
    games: int
    wins: int
    winrate: Rate


class SummonerProfile(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    platform: str
    profile_icon_id: int | None
    summoner_level: int | None
    is_tracked: bool
    tracked_since: AwareDatetime | None
    last_refreshed_at: AwareDatetime | None
    #: When the Update button becomes available again (None = now).
    can_refresh_at: AwareDatetime | None
    solo: RankEntry | None
    flex: RankEntry | None
    stats: ProfileStats
    #: At most 7, most played first.
    top_champions: list[ChampionStat] = Field(max_length=7)
    roles: list[RoleStat]
    #: Win/loss of recent ranked games, newest first, at most 20.
    recent_form: list[bool] = Field(max_length=20)
    #: Data Dragon key of the most played champion (splash banner).
    main_champion: str | None


class SummonerSearchResult(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int | None
    summoner_level: int | None
    is_tracked: bool
    solo_tier: Tier | None
    solo_rank: Division | None


class RefreshResult(ApiModel):
    status: RefreshStatus
    new_matches: int
    pending: int
    next_allowed_at: AwareDatetime
    message: str
    profile: SummonerProfile


# --- matches ---------------------------------------------------------------------------------


class ParticipantSummary(ApiModel):
    puuid: str
    game_name: str | None
    tag_line: str | None
    participant_id: int
    team_id: TeamId
    #: Arena (CHERRY) only: the two-player subteam (1..8) this player actually played on.
    #: ``team_id`` there is only Riot's top-half / bottom-half split.
    subteam_id: int | None = None
    #: Arena (CHERRY) only: final placement, 1 (best) to 8.
    placement: int | None = None
    team_position: Position
    champion_id: int
    champion_name: str
    champ_level: int
    win: bool
    kills: int
    deaths: int
    assists: int
    #: (k + a) / d; k + a when deaths == 0 ("perfect").
    kda: float
    #: Share of the team's kills (in Arena: the two-player subteam's kills).
    kill_participation: Rate
    #: total_minions_killed + neutral_minions_killed.
    cs: int
    cs_per_min: float
    gold: int
    gold_per_min: float
    damage_to_champions: int
    damage_per_min: float
    damage_taken: int
    vision_score: int
    wards_placed: int
    wards_killed: int
    control_wards: int
    #: item0..item6 (item6 = trinket); 0 = empty slot.
    items: list[int] = Field(min_length=7, max_length=7)
    summoner1_id: int
    summoner2_id: int
    largest_multikill: int = Field(ge=0, le=5)
    ai_score: Rate | None
    #: 1..10 by ai_score within the match (1 = best), None if unscored.
    ai_rank: Annotated[int, Field(ge=1, le=10)] | None
    is_tracked: bool


class ObjectiveStat(ApiModel):
    first: bool
    kills: int


class TeamObjectives(ApiModel):
    baron: ObjectiveStat
    dragon: ObjectiveStat
    rift_herald: ObjectiveStat
    horde: ObjectiveStat
    tower: ObjectiveStat
    inhibitor: ObjectiveStat
    champion: ObjectiveStat
    #: Absent from pre-2025 payloads.
    atakhan: ObjectiveStat | None = None


class TeamSummary(ApiModel):
    team_id: TeamId
    win: bool
    kills: int
    deaths: int
    assists: int
    gold: int
    damage_to_champions: int
    participants: list[ParticipantSummary]


class TeamDetail(TeamSummary):
    objectives: TeamObjectives
    #: Banned champion ids (-1 = no ban), in pick-turn order.
    bans: list[int]


class MatchSummary(ApiModel):
    match_id: str
    queue_id: int
    queue_label: str
    game_mode: str
    game_start: AwareDatetime
    #: Seconds.
    game_duration: int
    patch: str
    remake: bool
    #: The requested summoner's own line.
    me: ParticipantSummary
    #: Blue (100) first.
    teams: list[TeamSummary]


class MatchPage(ApiModel):
    items: list[MatchSummary]
    #: Opaque; pass back as ?cursor= for the next page. None when exhausted.
    next_cursor: str | None


class MatchDetail(ApiModel):
    match_id: str
    queue_id: int
    queue_label: str
    game_mode: str
    game_version: str
    patch: str
    game_start: AwareDatetime
    game_duration: int
    remake: bool
    model_version: str | None
    teams: list[TeamDetail]


# --- AI --------------------------------------------------------------------------------------


class AiTrendPoint(ApiModel):
    match_id: str
    game_start: AwareDatetime
    champion_name: str
    win: bool
    ai_score: Rate


class AiTrend(ApiModel):
    puuid: str
    model_version: str | None
    average: Rate | None
    #: Oldest -> newest.
    points: list[AiTrendPoint]


class FeatureAttribution(ApiModel):
    feature: str
    label: str
    group: FeatureGroup
    #: Signed mean gradient x input, in logit units.
    mean_attribution: float
    mean_abs_attribution: float = Field(ge=0.0)
    player_value: float
    population_value: float | None


class AiExplain(ApiModel):
    puuid: str
    model_version: str
    n_matches: int
    base_score: Rate | None
    #: Sorted by mean_abs_attribution descending.
    features: list[FeatureAttribution]


# --- leaderboard / roster --------------------------------------------------------------------


class BestAlly(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    games: int
    wins: int
    winrate: Rate


class LeaderboardEntry(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int | None
    summoner_level: int | None
    solo: RankEntry | None
    flex: RankEntry | None
    games: int
    wins: int
    losses: int
    winrate: Rate
    kda: float
    avg_kills: float
    avg_deaths: float
    avg_assists: float
    avg_ai_score: Rate | None
    #: Solo-queue rank_value change since season start.
    lp_delta: int | None
    best_ally: BestAlly | None
    #: Data Dragon keys, at most 3.
    top_champions: list[str] = Field(max_length=3)
    #: Newest first, at most 10.
    recent_form: list[bool] = Field(max_length=10)


class Leaderboard(ApiModel):
    season_start: AwareDatetime
    model_version: str | None
    queue: LeaderboardQueue
    entries: list[LeaderboardEntry]


class RosterEntry(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    tracked_since: AwareDatetime | None
    profile_icon_id: int | None


# --- meta / health ---------------------------------------------------------------------------


class Meta(ApiModel):
    ddragon_version: str
    ddragon_cdn: str
    platform: str
    region: str
    season_start: AwareDatetime
    model_version: str | None
    model_trained_at: AwareDatetime | None
    #: Queue id (as string) -> label.
    queues: dict[str, str]


class HealthModel(ApiModel):
    loaded: bool
    version: str | None
    trained_at: AwareDatetime | None
    n_features: int | None


class HealthRiot(ApiModel):
    key_configured: bool
    key_ok: bool | None
    last_error: str | None


class HealthPoller(ApiModel):
    last_run_at: AwareDatetime | None
    last_error: str | None
    running: bool


class HealthBot(ApiModel):
    #: DISCORD_TOKEN and DISCORD_BROADCAST_CHANNEL_ID are set for this deployment.
    configured: bool
    #: The bot process wrote a heartbeat within the last minute and did not report stopping.
    running: bool
    #: Connected to the Discord gateway at the last heartbeat.
    connected: bool
    heartbeat_at: AwareDatetime | None
    last_error: str | None


class Health(ApiModel):
    #: "degraded" when the DB is unreachable or the Riot key is missing/rejected.
    status: Literal["ok", "degraded"]
    version: str
    db_ok: bool
    model: HealthModel
    riot: HealthRiot
    poller: HealthPoller
    bot: HealthBot


__all__ = [
    "AiExplain",
    "AiTrend",
    "AiTrendPoint",
    "ApiModel",
    "BestAlly",
    "ChampionStat",
    "Division",
    "ErrorResponse",
    "FeatureAttribution",
    "FeatureGroup",
    "Health",
    "HealthBot",
    "HealthModel",
    "HealthPoller",
    "HealthRiot",
    "Leaderboard",
    "LeaderboardEntry",
    "LeaderboardQueue",
    "MatchDetail",
    "MatchPage",
    "MatchSummary",
    "Meta",
    "ObjectiveStat",
    "ParticipantSummary",
    "Position",
    "ProfileStats",
    "QueueType",
    "RankEntry",
    "RankHistory",
    "RankPoint",
    "RefreshResult",
    "RefreshStatus",
    "RoleStat",
    "RosterEntry",
    "SummonerProfile",
    "SummonerSearchResult",
    "TeamDetail",
    "TeamId",
    "TeamObjectives",
    "TeamSummary",
    "Tier",
]
