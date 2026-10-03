"""ORM models (SQLAlchemy 2.0 typed declarative).

Column naming: snake_case versions of the Riot match-v5 field names wherever one exists,
so ``hextrack.ingest.mapping`` is a mechanical translation. Exceptions are documented inline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hextrack.db.base import Base

TZDateTime = DateTime(timezone=True)


def _int_stat() -> Any:
    """Non-null integer stat defaulting to 0 (client and server side)."""
    return mapped_column(Integer, default=0, server_default=text("0"))


def _bool_stat() -> Any:
    """Non-null boolean flag defaulting to false (client and server side)."""
    return mapped_column(Boolean, default=False, server_default=text("false"))


class Summoner(Base):
    """A Riot account we know about. ``is_tracked`` marks the curated friends roster."""

    __tablename__ = "summoners"

    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    game_name: Mapped[str] = mapped_column(Text)
    tag_line: Mapped[str] = mapped_column(Text)
    #: Platform routing value, e.g. "na1".
    platform: Mapped[str] = mapped_column(Text)
    profile_icon_id: Mapped[int | None] = mapped_column(Integer)
    summoner_level: Mapped[int | None] = mapped_column(Integer)
    is_tracked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    tracked_since: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: Game start of the newest match we have stored for this player.
    last_seen: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: Last successful summoner-v4 + league-v4 refresh (drives the on-demand cooldown).
    last_refreshed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: When the season backfill (count=HEXTRACK_BACKFILL_COUNT, startTime=season) completed.
    backfilled_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: Match-discovery watermark: every ranked game of this player up to this game start is
    #: stored, so discovery only has to list what Riot recorded after it (see
    #: ``hextrack.ingest.service.discover``). None until the first complete listing.
    synced_through: Mapped[datetime | None] = mapped_column(TZDateTime)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now()
    )

    rank_snapshots: Mapped[list[RankSnapshot]] = relationship(
        back_populates="summoner",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="RankSnapshot.taken_at",
    )

    __table_args__ = (
        Index(
            "ix_summoners_tracked",
            "is_tracked",
            postgresql_where=text("is_tracked"),
        ),
    )

    @property
    def riot_id(self) -> str:
        return f"{self.game_name}#{self.tag_line}"

    def __repr__(self) -> str:
        return f"Summoner({self.riot_id!r}, tracked={self.is_tracked})"


class Match(Base):
    """One match-v5 game. ``raw`` keeps the full validated payload for retraining."""

    __tablename__ = "matches"

    match_id: Mapped[str] = mapped_column(Text, primary_key=True)
    #: info.platformId, e.g. "NA1".
    platform_id: Mapped[str | None] = mapped_column(Text)
    queue_id: Mapped[int] = mapped_column(Integer)
    game_mode: Mapped[str] = mapped_column(Text)
    game_type: Mapped[str | None] = mapped_column(Text)
    game_version: Mapped[str] = mapped_column(Text)
    #: "major.minor" from game_version, e.g. "16.17".
    patch: Mapped[str] = mapped_column(Text)
    game_start: Mapped[datetime] = mapped_column(TZDateTime)
    #: Seconds.
    game_duration: Mapped[int] = mapped_column(Integer)
    #: info.endOfGameResult ("GameComplete", "Abort_Unexpected", ...); None on old payloads.
    end_of_game_result: Mapped[str | None] = mapped_column(Text)
    #: True when any participant has gameEndedInEarlySurrender (a remake).
    remake: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    #: How the game got here: "roster" (poller / lookups / imports) or "crawl" (the data
    #: crawler; games of players HexTrack doesn't track, kept for training).
    source: Mapped[str] = mapped_column(Text, default="roster", server_default=text("'roster'"))
    #: Champion ids banned in the game (both teams, no "no ban" -1). NULL until filled from
    #: ``raw`` (new games at ingestion, older ones by the champion rollup worker).
    ban_ids: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    #: Match timeline (item purchases, skill order): NULL = not sampled, "pending", "ok",
    #: "missing" (Riot 404) or "failed" (gave up after TIMELINE_MAX_ATTEMPTS).
    timeline_state: Mapped[str | None] = mapped_column(Text)
    timeline_attempts: Mapped[int] = mapped_column(
        SmallInteger, default=0, server_default=text("0")
    )
    #: Champion rollups: 0 to count, 1 counted, 2 counted with its timeline, 3 timeline
    #: arrived after the game was counted, -1 not eligible (see stats/champions).
    champ_rollup: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    ingested_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    #: Set when every participant row was scored by ``model_version``.
    scored_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    model_version: Mapped[str | None] = mapped_column(Text)

    participants: Mapped[list[MatchParticipant]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MatchParticipant.participant_id",
    )

    def __repr__(self) -> str:
        return f"Match({self.match_id!r}, queue={self.queue_id})"


class MatchParticipant(Base):
    """One player's stat line in one match (10 per Summoner's Rift game)."""

    __tablename__ = "match_participants"

    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    participant_id: Mapped[int] = mapped_column(SmallInteger)
    #: 100 blue, 200 red.
    team_id: Mapped[int] = mapped_column(SmallInteger)
    #: Denormalized from matches.game_start for the (puuid, game_start desc) index.
    game_start: Mapped[datetime] = mapped_column(TZDateTime)
    #: Denormalized from matches.queue_id for per-queue history filters.
    queue_id: Mapped[int] = mapped_column(Integer)

    # identity snapshot at game time
    riot_id_game_name: Mapped[str | None] = mapped_column(Text)
    riot_id_tagline: Mapped[str | None] = mapped_column(Text)
    profile_icon_id: Mapped[int | None] = mapped_column(Integer)
    summoner_level: Mapped[int | None] = mapped_column(Integer)

    champion_id: Mapped[int] = mapped_column(Integer)
    #: Data Dragon champion key, e.g. "MonkeyKing".
    champion_name: Mapped[str] = mapped_column(Text)
    champ_level: Mapped[int] = mapped_column(SmallInteger, default=0, server_default=text("0"))
    #: TOP | JUNGLE | MIDDLE | BOTTOM | UTILITY | UNKNOWN (Riot's "" and "Invalid" -> UNKNOWN).
    team_position: Mapped[str] = mapped_column(
        Text, default="UNKNOWN", server_default=text("'UNKNOWN'")
    )
    #: Arena (CHERRY) only: the two-player subteam, 1..8. None in every other mode, where
    #: ``team_id`` is the real team.
    player_subteam_id: Mapped[int | None] = mapped_column(SmallInteger)
    #: Arena (CHERRY) only: final placement, 1..8 (None in every other mode).
    placement: Mapped[int | None] = mapped_column(SmallInteger)
    win: Mapped[bool] = mapped_column(Boolean)
    game_ended_in_early_surrender: Mapped[bool] = _bool_stat()
    game_ended_in_surrender: Mapped[bool] = _bool_stat()

    # combat
    kills: Mapped[int] = _int_stat()
    deaths: Mapped[int] = _int_stat()
    assists: Mapped[int] = _int_stat()
    first_blood_kill: Mapped[bool] = _bool_stat()
    double_kills: Mapped[int] = _int_stat()
    triple_kills: Mapped[int] = _int_stat()
    quadra_kills: Mapped[int] = _int_stat()
    penta_kills: Mapped[int] = _int_stat()
    largest_multi_kill: Mapped[int] = _int_stat()
    largest_killing_spree: Mapped[int] = _int_stat()
    killing_sprees: Mapped[int] = _int_stat()
    longest_time_spent_living: Mapped[int] = _int_stat()
    total_time_spent_dead: Mapped[int] = _int_stat()

    # economy
    gold_earned: Mapped[int] = _int_stat()
    gold_spent: Mapped[int] = _int_stat()
    total_minions_killed: Mapped[int] = _int_stat()
    neutral_minions_killed: Mapped[int] = _int_stat()
    total_ally_jungle_minions_killed: Mapped[int] = _int_stat()
    total_enemy_jungle_minions_killed: Mapped[int] = _int_stat()

    # damage
    total_damage_dealt: Mapped[int] = _int_stat()
    total_damage_dealt_to_champions: Mapped[int] = _int_stat()
    physical_damage_dealt_to_champions: Mapped[int] = _int_stat()
    magic_damage_dealt_to_champions: Mapped[int] = _int_stat()
    true_damage_dealt_to_champions: Mapped[int] = _int_stat()
    total_damage_taken: Mapped[int] = _int_stat()
    damage_self_mitigated: Mapped[int] = _int_stat()
    damage_dealt_to_objectives: Mapped[int] = _int_stat()
    damage_dealt_to_buildings: Mapped[int] = _int_stat()
    damage_dealt_to_turrets: Mapped[int] = _int_stat()

    # vision (control wards == visionWardsBoughtInGame)
    vision_score: Mapped[int] = _int_stat()
    wards_placed: Mapped[int] = _int_stat()
    wards_killed: Mapped[int] = _int_stat()
    vision_wards_bought: Mapped[int] = _int_stat()
    detector_wards_placed: Mapped[int] = _int_stat()

    # utility
    time_ccing_others: Mapped[int] = _int_stat()
    total_time_cc_dealt: Mapped[int] = _int_stat()
    total_heal: Mapped[int] = _int_stat()
    total_heals_on_teammates: Mapped[int] = _int_stat()
    total_damage_shielded_on_teammates: Mapped[int] = _int_stat()

    # objectives
    turret_kills: Mapped[int] = _int_stat()
    turret_takedowns: Mapped[int] = _int_stat()
    inhibitor_kills: Mapped[int] = _int_stat()
    inhibitor_takedowns: Mapped[int] = _int_stat()
    dragon_kills: Mapped[int] = _int_stat()
    baron_kills: Mapped[int] = _int_stat()
    first_tower_kill: Mapped[bool] = _bool_stat()

    # communication: hold + getBack + onMyWay + needVision + enemyMissing + enemyVision
    pings_total: Mapped[int] = _int_stat()

    # build
    #: item0..item6 (item6 = trinket); 0 means an empty slot. Always 7 entries.
    items: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    summoner1_id: Mapped[int] = _int_stat()
    summoner2_id: Mapped[int] = _int_stat()
    #: perks.styles[0].selections[0].perk (keystone) and perks.styles[1].style.
    primary_rune_id: Mapped[int | None] = mapped_column(Integer)
    secondary_style_id: Mapped[int | None] = mapped_column(Integer)
    #: Full rune page: perks.styles[0].style, the 4 primary + 2 secondary selections in
    #: order, and statPerks (offense, flex, defense). NULL until filled from ``raw``.
    primary_style_id: Mapped[int | None] = mapped_column(SmallInteger)
    rune_ids: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    stat_shards: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    #: ``roleBoundItem``: the role quest's extra slot (bot lane keeps its boots here since
    #: the 2026 season). 0 = empty; NULL = not filled yet / not in the payload.
    role_bound_item: Mapped[int | None] = mapped_column(Integer)

    # AI Score
    #: P(win | stat line) in [0, 1] from ``model_version``; None until scored.
    ai_score: Mapped[float | None] = mapped_column(Float)
    ai_scored_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    model_version: Mapped[str | None] = mapped_column(Text)

    match: Mapped[Match] = relationship(back_populates="participants")

    __table_args__ = (
        Index("ix_match_participants_model_version", "model_version"),
        Index(
            "ix_match_participants_unscored",
            "match_id",
            postgresql_where=text("ai_score IS NULL"),
        ),
    )

    @property
    def control_wards(self) -> int:
        return self.vision_wards_bought

    @property
    def cs(self) -> int:
        return self.total_minions_killed + self.neutral_minions_killed

    def __repr__(self) -> str:
        return f"MatchParticipant({self.match_id!r}, {self.riot_id_game_name!r})"


class RankSnapshot(Base):
    """League-v4 entry over time. Inserted only on change or as a 24h heartbeat."""

    __tablename__ = "rank_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    puuid: Mapped[str] = mapped_column(Text, ForeignKey("summoners.puuid", ondelete="CASCADE"))
    #: RANKED_SOLO_5x5 | RANKED_FLEX_SR
    queue_type: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text)
    #: "IV".."I"; None for MASTER / GRANDMASTER / CHALLENGER.
    rank: Mapped[str | None] = mapped_column(Text)
    lp: Mapped[int] = mapped_column(Integer)
    wins: Mapped[int] = mapped_column(Integer)
    losses: Mapped[int] = mapped_column(Integer)
    #: ``hextrack.rank.rank_value(tier, rank, lp)``.
    rank_value: Mapped[int] = mapped_column(Integer)
    taken_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    is_heartbeat: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))

    summoner: Mapped[Summoner] = relationship(back_populates="rank_snapshots")


class BotEvent(Base):
    """Outbox consumed by the Discord bot (``FOR UPDATE SKIP LOCKED``)."""

    __tablename__ = "bot_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    #: One of ``hextrack.ingest.events.EVENT_KINDS``.
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ix_bot_events_pending",
            "created_at",
            postgresql_where=text("processed_at IS NULL"),
        ),
    )


class AiModel(Base):
    """A trained AI Score model. Exactly zero or one row has ``is_active``."""

    __tablename__ = "ai_models"

    version: Mapped[str] = mapped_column(Text, primary_key=True)
    feature_names: Mapped[list[str]] = mapped_column(ARRAY(Text))
    #: e.g. {"val_auc": 0.87, "val_accuracy": 0.79, "n_train": 12000, ...}
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    trained_at: Mapped[datetime] = mapped_column(TZDateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())

    __table_args__ = (
        Index(
            "uq_ai_models_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


class CrawlPlayer(Base):
    """The data crawler's frontier: players whose ranked history it will fetch."""

    __tablename__ = "crawl_players"

    puuid: Mapped[str] = mapped_column(Text, primary_key=True)
    #: Where the crawler found them: "ladder" (league-exp pages) or "match" (a crawled game).
    found_via: Mapped[str] = mapped_column(Text)
    #: Tier / division from the ladder page they came from (None when found in a game).
    tier: Mapped[str | None] = mapped_column(Text)
    division: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(TZDateTime, server_default=func.now())
    #: Last time their match list was fetched; None = never crawled yet.
    crawled_at: Mapped[datetime | None] = mapped_column(TZDateTime)
    #: Games of theirs the crawler stored so far.
    matches_added: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    #: Last error text, if their crawl failed (cleared on success).
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_crawl_players_queue", "crawled_at", "discovered_at"),)


class MatchTimelinePlayer(Base):
    """What one player bought and levelled, in order, from the match timeline (only the
    extracted sequences are kept, not the timeline itself)."""

    __tablename__ = "match_timeline_players"

    match_id: Mapped[str] = mapped_column(
        Text, ForeignKey("matches.match_id", ondelete="CASCADE"), primary_key=True
    )
    participant_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    #: Item ids in purchase order (undone purchases removed) and the second each was bought.
    purchases: Mapped[list[int]] = mapped_column(ARRAY(Integer))
    purchase_s: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    #: Skill slot (1 Q, 2 W, 3 E, 4 R) per normal level-up, in order.
    skill_order: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))


class ChampionStat(Base):
    """Per champion / position / patch / queue totals (champion rollup worker)."""

    __tablename__ = "champion_stats"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[str] = mapped_column(Text, primary_key=True)
    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    champion_key: Mapped[str] = mapped_column(Text)
    games: Mapped[int] = _int_stat()
    wins: Mapped[int] = _int_stat()
    kills: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    deaths: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    assists: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    damage: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    cs: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    gold: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    duration_s: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))
    #: Games (and wins) of these that had a timeline (the build-order denominators).
    timeline_games: Mapped[int] = _int_stat()
    timeline_wins: Mapped[int] = _int_stat()


class ChampionBan(Base):
    __tablename__ = "champion_bans"

    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bans: Mapped[int] = _int_stat()


class ChampionPatchTotal(Base):
    """Counted games per patch and queue: pick / ban rate denominators and the patch picker."""

    __tablename__ = "champion_patch_totals"

    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    matches: Mapped[int] = _int_stat()
    timeline_matches: Mapped[int] = _int_stat()


class ChampionRollup(Base):
    """Counted choices per champion / position / patch / queue: ``kind`` is what was chosen
    (see hextrack.stats.champions.KINDS), ``key`` the choice (e.g. item ids "3078-3071-6333").
    ``extra_sum`` carries a per-kind extra total (e.g. seconds to finish the core build)."""

    __tablename__ = "champion_rollups"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[str] = mapped_column(Text, primary_key=True)
    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    games: Mapped[int] = _int_stat()
    wins: Mapped[int] = _int_stat()
    extra_sum: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))


class ChampionMatchup(Base):
    """Lane matchups: the champion in ``position`` against ``opponent_id`` in the same lane."""

    __tablename__ = "champion_matchups"

    champion_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    position: Mapped[str] = mapped_column(Text, primary_key=True)
    patch: Mapped[str] = mapped_column(Text, primary_key=True)
    queue_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    opponent_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    games: Mapped[int] = _int_stat()
    wins: Mapped[int] = _int_stat()
    #: Sum of (own gold - opponent gold) at the end of the game.
    gold_diff_sum: Mapped[int] = mapped_column(BigInteger, default=0, server_default=text("0"))


class AppState(Base):
    """Small key/value store for heartbeats, e.g. key "poller" or "bot"."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = mapped_column(
        TZDateTime, server_default=func.now(), onupdate=func.now()
    )


# --- indexes that need expressions (defined after the classes so columns are resolved) ---

#: Riot IDs are case-insensitive: one account per (lower(name), lower(tag), platform).
Index(
    "uq_summoners_riot_id_lower",
    func.lower(Summoner.game_name),
    func.lower(Summoner.tag_line),
    Summoner.platform,
    unique=True,
)
#: Prefix search: ``lower(game_name) LIKE 'abc%'``.
Index(
    "ix_summoners_game_name_prefix",
    text("lower(game_name) text_pattern_ops"),
    _table=Summoner.__table__,
)
Index("ix_matches_game_start", Match.game_start.desc())
Index("ix_matches_queue_id_game_start", Match.queue_id, Match.game_start.desc())
#: Roster-only lookups (rescore, population means) skip the crawler's games through this.
Index("ix_matches_source_queue_start", Match.source, Match.queue_id, Match.game_start.desc())
#: Scored rows only (the roster's games; crawled games are stored unscored): the role
#: percentile population reads this small index instead of scanning every participant.
Index(
    "ix_match_participants_scored_position",
    MatchParticipant.team_position,
    postgresql_include=["ai_score", "model_version", "queue_id", "match_id"],
    postgresql_where=text("ai_score IS NOT NULL"),
)
#: The timeline backlog (crawler) and the champion rollup queue (worker).
Index(
    "ix_matches_timeline_pending",
    Match.source,
    Match.game_start.desc(),
    postgresql_where=text("timeline_state = 'pending'"),
)
Index(
    "ix_matches_rollup_todo",
    Match.ingested_at,
    postgresql_where=text("champ_rollup IN (0, 3)"),
)
#: The list page reads every champion of a few patches.
Index("ix_champion_stats_patch_queue", ChampionStat.patch, ChampionStat.queue_id)
Index(
    "ix_match_participants_puuid_game_start",
    MatchParticipant.puuid,
    MatchParticipant.game_start.desc(),
)
Index(
    "ix_match_participants_puuid_queue_game_start",
    MatchParticipant.puuid,
    MatchParticipant.queue_id,
    MatchParticipant.game_start.desc(),
)
Index(
    "ix_rank_snapshots_puuid_queue_taken_at",
    RankSnapshot.puuid,
    RankSnapshot.queue_type,
    RankSnapshot.taken_at.desc(),
)

ALL_TABLES: tuple[str, ...] = (
    "summoners",
    "matches",
    "match_participants",
    "rank_snapshots",
    "bot_events",
    "ai_models",
    "app_state",
    "crawl_players",
    "match_timeline_players",
    "champion_stats",
    "champion_bans",
    "champion_patch_totals",
    "champion_rollups",
    "champion_matchups",
)
