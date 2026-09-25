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
#: A signed difference of two rates / AI scores, in [-1, 1].
RateDiff = Annotated[float, Field(ge=-1.0, le=1.0)]
#: A percentile in [0, 100]: "better than X% of the population".
Percentile = Annotated[float, Field(ge=0.0, le=100.0)]
#: Period filter of the friend-group and insight endpoints: "season" = games started at or
#: after ``settings.season_start``; "all" = every stored game.
StatsSince = Literal["season", "all"]
#: Day of week, 0 = Monday .. 6 = Sunday (Python ``datetime.weekday()``).
DayOfWeek = Annotated[int, Field(ge=0, le=6)]
#: Hour of day, 0..23, in the requested time zone.
HourOfDay = Annotated[int, Field(ge=0, le=23)]


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
    #: Mean of the player's per-game ``ai_role_percentile`` (games scored by the active model
    #: with a known position); None when there are none.
    avg_ai_role_percentile: Percentile | None = None


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
    #: Score within role: this game's AI Score is better than X% of all ranked, non-remake
    #: games scored by the active model in the same ``team_position`` (whole database).
    #: None when unscored, scored by another model version, or the position is UNKNOWN.
    ai_role_percentile: Percentile | None = None


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
    #: Mean of the player's per-game ``ai_role_percentile`` over the leaderboard's games;
    #: None when no game has one.
    avg_ai_role_percentile: Percentile | None = None
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


# --- squad (friend group) --------------------------------------------------------------------
# Shared rules for everything below: ranked Summoner's Rift only (420 solo, 440 flex, narrowed
# by ``queue``), remakes excluded, ``since`` as in StatsSince. AI Scores are 0..1 like every
# other score in this API (the UI shows them x100) and only count when scored by the active
# model (``model_version``); None means "not scored".


class SquadPlayer(ApiModel):
    """One tracked (roster) player's totals in the requested period."""

    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int | None
    games: int
    wins: int
    winrate: Rate
    avg_ai_score: Rate | None


class SquadPair(ApiModel):
    """Two roster players who played ranked games on the SAME team.

    Duo synergy: ``games``/``wins``/``winrate`` of their shared games, compared with
    ``expected_winrate``. Who carries whom: over ``scored_games`` (shared games where both
    have an active-model score), how often a's score was higher / lower / equal to b's.
    """

    #: Always ``a_puuid < b_puuid`` in code-point order (Python / JS string comparison), so
    #: each pair appears once.
    a_puuid: str
    b_puuid: str
    #: Ranked games where both were on the same team.
    games: int
    wins: int
    winrate: Rate
    #: Mean of a's and b's own overall winrates (SquadPlayer.winrate) in the same period.
    expected_winrate: Rate
    #: ``winrate - expected_winrate``: positive = they win more together than apart.
    winrate_delta: RateDiff
    #: a's / b's average AI Score over the shared scored games.
    avg_ai_a: Rate | None
    avg_ai_b: Rate | None
    #: Shared games where both have a score from the active model.
    scored_games: int
    #: Scored shared games where a's score was higher than / lower than / equal to b's.
    a_higher: int
    b_higher: int
    ties: int
    #: Mean of (a's score - b's score) over the scored shared games, on the 0..1 scale
    #: (x100 = points in the UI); None when ``scored_games`` is 0.
    avg_score_diff: RateDiff | None


class SquadPairs(ApiModel):
    since: StatsSince
    season_start: AwareDatetime
    queue: LeaderboardQueue
    model_version: str | None
    #: Pairs with fewer shared ``games`` than this are small samples (the UI greys them).
    min_games: int
    #: Every tracked player (including ones without games), most games first.
    players: list[SquadPlayer]
    #: Every roster pair with at least one shared same-team game (also those below
    #: ``min_games``), most shared games first.
    pairs: list[SquadPair]


# --- stacks (games the squad played together) ---------------------------------------------

#: "all": every stored queue except Arena and customs; "flex": Ranked Flex only.
StackQueue = Literal["all", "flex"]
#: How lopsided the teammates' AI Scores were (stats/verdict.py). The frontend maps each tier
#: to banter text (web/src/components/match/verdicts.ts); keep the two lists identical.
VerdictTier = Literal[
    "hardCarry",
    "carry",
    "edge",
    "winTogether",
    "soloLost",
    "ranDown",
    "offDay",
    "tried",
    "loseTogether",
]


class StackVerdict(ApiModel):
    """Banter verdict for one stack: teammates share the result, so their scores compare."""

    tier: VerdictTier
    #: The called-out player (carrier, the one who ran it down...); None for "together" tiers.
    target_puuid: str | None
    #: AI Score points (0..100) between the target and the next teammate.
    gap: Annotated[int, Field(ge=0, le=100)]


class StackGame(ApiModel):
    """One team in one match on which ``size``+ roster players played together."""

    match_id: str
    queue_id: int
    queue_label: str
    game_mode: str
    game_start: AwareDatetime
    game_duration: int
    patch: str
    team_id: TeamId
    win: bool
    team_kills: int
    enemy_kills: int
    #: The stack's roster players, lane order.
    members: list[ParticipantSummary]
    #: None when a member isn't scored by the active model.
    verdict: StackVerdict | None


class StackGamePage(ApiModel):
    #: Newest first. Both teams of a match (two opposing stacks) are always on the same page.
    items: list[StackGame]
    #: Opaque; pass back as ?cursor= for the next page. None when exhausted.
    next_cursor: str | None


class StackPlayer(ApiModel):
    """A roster player's numbers across the stacks in the requested scope."""

    puuid: str
    game_name: str
    tag_line: str
    profile_icon_id: int | None
    games: int
    wins: int
    winrate: Rate
    #: Mean AI Score over games scored by the active model (a plain number, never graded).
    avg_ai_score: Rate | None
    scored_games: int
    kills: int
    deaths: int
    assists: int
    kda: float
    #: Verdict counts: carries = hardCarry + carry + edge, ran_downs = soloLost + ranDown.
    hard_carries: int
    carries: int
    ran_downs: int
    off_days: int
    tried: int
    top_champion_id: int | None
    top_champion_name: str | None
    top_champion_games: int


class StackLineup(ApiModel):
    """An exact set of roster players (sorted puuids) and their record together."""

    puuids: list[str]
    games: int
    wins: int
    winrate: Rate
    last_played: AwareDatetime


StackAwardKey = Literal["carry_king", "ran_it_down", "tried_their_best"]


class StackAward(ApiModel):
    key: StackAwardKey
    puuid: str
    count: int


StackHighlightKey = Literal[
    "biggest_stomp", "worst_loss", "longest_game", "fastest_win", "most_team_kills"
]


class StackHighlight(ApiModel):
    key: StackHighlightKey
    match_id: str
    game_start: AwareDatetime
    queue_label: str
    win: bool
    game_duration: int
    team_kills: int
    enemy_kills: int
    member_puuids: list[str]


class StackSummary(ApiModel):
    since: StatsSince
    season_start: AwareDatetime
    queue: StackQueue
    #: Fewest roster players on one team for it to count (5 = a full stack).
    size: Annotated[int, Field(ge=3, le=5)]
    model_version: str | None
    #: A lineup needs this many games to be "best lineup".
    min_lineup_games: int
    games: int
    wins: int
    winrate: Rate
    #: Newest first, at most 20.
    recent_form: list[bool] = Field(max_length=20)
    #: Seconds; None without games.
    avg_duration: float | None
    avg_team_kills: float | None
    avg_enemy_kills: float | None
    #: Stacks with a verdict (every member scored by the active model).
    verdict_games: int
    #: Roster players with at least one stack, most games first.
    players: list[StackPlayer]
    #: Most-played lineups, at most 10.
    lineups: list[StackLineup] = Field(max_length=10)
    best_lineup: StackLineup | None
    most_played_lineup: StackLineup | None
    #: Only awards with a count above zero.
    awards: list[StackAward]
    highlights: list[StackHighlight]


# --- personal insights -----------------------------------------------------------------------

SessionState = Literal["first_game", "after_win", "after_one_loss", "after_two_plus_losses"]


class SessionGameBucket(ApiModel):
    #: Game number within a session; 6 means "6th game or later".
    n: Annotated[int, Field(ge=1, le=6)]
    games: int
    wins: int
    winrate: Rate
    avg_ai_score: Rate | None


class SessionStateBucket(ApiModel):
    #: What happened just before this game in the same session.
    state: SessionState
    games: int
    wins: int
    winrate: Rate
    avg_ai_score: Rate | None


class SessionInsights(ApiModel):
    """Tilt detector. A session = consecutive ranked games of the player where
    ``next.game_start - (previous.game_start + previous.duration) <= gap_minutes``."""

    puuid: str
    since: StatsSince
    queue: LeaderboardQueue
    model_version: str | None
    gap_minutes: int
    #: Buckets with fewer games than this are small samples (the UI greys them).
    min_games: int
    sessions: int
    games: int
    avg_session_games: float
    longest_session_games: int
    #: Always six buckets, n = 1..6 in order (empty buckets have games 0).
    by_game_number: list[SessionGameBucket] = Field(max_length=6)
    #: Always four buckets in the order first_game, after_win, after_one_loss,
    #: after_two_plus_losses.
    by_state: list[SessionStateBucket] = Field(max_length=4)


class ScheduleCell(ApiModel):
    dow: DayOfWeek
    hour: HourOfDay
    games: int
    wins: int
    avg_ai_score: Rate | None


class ScheduleDay(ApiModel):
    dow: DayOfWeek
    games: int
    wins: int
    winrate: Rate
    avg_ai_score: Rate | None


class ScheduleHour(ApiModel):
    hour: HourOfDay
    games: int
    wins: int
    winrate: Rate
    avg_ai_score: Rate | None


class ScheduleWindow(ApiModel):
    """Three consecutive hours on one day of week (never crossing midnight)."""

    dow: DayOfWeek
    #: 0..21.
    start_hour: Annotated[int, Field(ge=0, le=21)]
    #: Exclusive: ``start_hour + 3`` (3..24).
    end_hour: Annotated[int, Field(ge=3, le=24)]
    games: int
    winrate: Rate


class ScheduleInsights(ApiModel):
    """Best time to play: win rate by local day of week and hour of game start."""

    puuid: str
    since: StatsSince
    queue: LeaderboardQueue
    model_version: str | None
    #: IANA time zone the hours are in (as requested).
    tz: str
    #: Cells / windows with fewer games than this are small samples.
    min_games: int
    #: Only non-empty (dow, hour) cells.
    cells: list[ScheduleCell]
    #: Always 7 entries, dow 0..6 in order.
    by_dow: list[ScheduleDay] = Field(max_length=7)
    #: Always 24 entries, hour 0..23 in order.
    by_hour: list[ScheduleHour] = Field(max_length=24)
    #: Highest / lowest winrate 3-hour window with at least ``min_games``; None if none.
    #: Ties: more games, then a window whose first hour has games, then the earlier one.
    #: ``worst_window`` is also None when no window has a lower winrate than the best one.
    best_window: ScheduleWindow | None
    worst_window: ScheduleWindow | None


class ChampionMatchup(ApiModel):
    """The player's record against one enemy champion in their lane."""

    #: The lane opponent's champion.
    champion_id: int
    #: Data Dragon key of the opponent's champion.
    champion_name: str
    games: int
    wins: int
    losses: int
    winrate: Rate
    #: The player's own average AI Score in these games.
    avg_ai_score: Rate | None
    #: Mean of (player gold_earned - opponent gold_earned).
    avg_gold_diff: float


class MatchupInsights(ApiModel):
    """Nemesis champions. The lane opponent is the enemy with the same ``team_position``;
    games where the position is UNKNOWN / empty or not exactly one per team are skipped."""

    puuid: str
    since: StatsSince
    queue: LeaderboardQueue
    model_version: str | None
    #: Champions faced fewer times than this are left out of both lists.
    min_games: int
    #: Games with an identified lane opponent (before the ``min_games`` cut).
    total_matchups: int
    #: Losing records only (winrate < 50%): lowest winrate first, then more games; at most 8.
    nemeses: list[ChampionMatchup] = Field(max_length=8)
    #: Winning records only (winrate > 50%): highest winrate first, then more games; at
    #: most 8. A champion is never in both lists; even (50%) records are in neither.
    favorites: list[ChampionMatchup] = Field(max_length=8)


class LuckGame(ApiModel):
    match_id: str
    game_start: AwareDatetime
    queue_id: int
    champion_name: str
    team_position: Position
    kills: int
    deaths: int
    assists: int
    #: Seconds.
    duration: int
    ai_score: Rate
    ai_role_percentile: Percentile | None


class LuckInsights(ApiModel):
    """Unlucky losses (lost, but scored >= high_threshold) and lucky wins (won, but scored
    <= low_threshold), from games scored by the active model."""

    puuid: str
    since: StatsSince
    queue: LeaderboardQueue
    model_version: str | None
    #: 0.6 (60 in the UI).
    high_threshold: Rate
    #: 0.4 (40 in the UI).
    low_threshold: Rate
    #: Scored losses / how many of them were unlucky.
    losses_scored: int
    unlucky_count: int
    #: Scored wins / how many of them were lucky.
    wins_scored: int
    lucky_count: int
    #: Highest score first, at most ``limit``.
    unlucky_losses: list[LuckGame]
    #: Lowest score first, at most ``limit``.
    lucky_wins: list[LuckGame]


# --- records ---------------------------------------------------------------------------------

RecordKey = Literal[
    "most_kills",
    "most_assists",
    "most_deaths",
    "best_kda",
    "most_damage",
    "highest_damage_per_min",
    "most_cs",
    "highest_cs_per_min",
    "most_gold",
    "highest_vision",
    "highest_kill_participation",
    "longest_game",
    "fastest_win",
    "highest_ai_score",
    "largest_killing_spree",
    "most_damage_taken",
    "most_healing",
]
#: How ``RecordEntry.value`` is expressed: count / number = plain number; percent = ratio
#: 0..1; duration = seconds; per_min = per minute; score = AI Score 0..1.
RecordUnit = Literal["count", "number", "percent", "duration", "per_min", "score"]
RecordScope = Literal["roster", "player"]


class RecordEntry(ApiModel):
    """One game holding a record (or a pentakill game)."""

    #: 1 = best. Ties share the order of ``game_start`` (earlier first).
    rank: Annotated[int, Field(ge=1)]
    #: In the category's unit; for ``pentakills`` the number of pentakills in that game.
    value: float
    puuid: str
    game_name: str
    tag_line: str
    #: Data Dragon key.
    champion_name: str
    match_id: str
    game_start: AwareDatetime
    win: bool


class RecordCategory(ApiModel):
    key: RecordKey
    label: str
    unit: RecordUnit
    #: False only for fastest_win (lower value = better record); most_deaths is "higher".
    higher_is_better: bool
    #: Best first, at most ``Records.limit``; empty when no game qualifies.
    entries: list[RecordEntry]


class QuadrakillCount(ApiModel):
    puuid: str
    game_name: str
    tag_line: str
    #: Sum of quadra kills over the period.
    count: int


class Records(ApiModel):
    """Single-game records. Scope "roster" = all tracked players; "player" = only ``puuid``
    (tracked or not). best_kda needs at least 5 takedowns; highest_kill_participation needs
    at least 10 team kills; highest_ai_score only uses active-model scores. A record must be
    above zero. longest_game and fastest_win list each match once (the friend with the
    lowest participant id)."""

    since: StatsSince
    queue: LeaderboardQueue
    scope: RecordScope
    #: The player for scope "player"; None for "roster".
    puuid: str | None
    model_version: str | None
    #: Entries per category.
    limit: int
    #: Every RecordKey, in the RecordKey order above.
    categories: list[RecordCategory]
    #: Every pentakill game, newest first (``rank`` counts from 1 in that order).
    pentakills: list[RecordEntry]
    #: Players with at least one quadra kill, most first.
    quadrakills: list[QuadrakillCount]


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
    "ChampionMatchup",
    "ChampionStat",
    "DayOfWeek",
    "Division",
    "ErrorResponse",
    "FeatureAttribution",
    "FeatureGroup",
    "Health",
    "HealthBot",
    "HealthModel",
    "HealthPoller",
    "HealthRiot",
    "HourOfDay",
    "Leaderboard",
    "LeaderboardEntry",
    "LeaderboardQueue",
    "LuckGame",
    "LuckInsights",
    "MatchDetail",
    "MatchPage",
    "MatchSummary",
    "MatchupInsights",
    "Meta",
    "ObjectiveStat",
    "ParticipantSummary",
    "Percentile",
    "Position",
    "ProfileStats",
    "QuadrakillCount",
    "QueueType",
    "RankEntry",
    "RankHistory",
    "RankPoint",
    "RateDiff",
    "RecordCategory",
    "RecordEntry",
    "RecordKey",
    "RecordScope",
    "RecordUnit",
    "Records",
    "RefreshResult",
    "RefreshStatus",
    "RoleStat",
    "RosterEntry",
    "ScheduleCell",
    "ScheduleDay",
    "ScheduleHour",
    "ScheduleInsights",
    "ScheduleWindow",
    "SessionGameBucket",
    "SessionInsights",
    "SessionState",
    "SessionStateBucket",
    "SquadPair",
    "SquadPairs",
    "SquadPlayer",
    "StatsSince",
    "SummonerProfile",
    "SummonerSearchResult",
    "TeamDetail",
    "TeamId",
    "TeamObjectives",
    "TeamSummary",
    "Tier",
]
