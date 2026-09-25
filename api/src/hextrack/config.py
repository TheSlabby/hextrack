"""Application settings.

Values come from the process environment, then ``api/.env``, then the repo-root ``.env``
(environment variables always win). Relative filesystem paths are resolved against the
``api/`` directory so commands behave the same regardless of the current working directory.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: ``api/`` directory (…/api/src/hextrack/config.py -> …/api).
API_DIR: Path = Path(__file__).resolve().parents[2]
#: Monorepo root.
REPO_ROOT: Path = API_DIR.parent

DEFAULT_DATABASE_URL = "postgresql+asyncpg://hextrack:hextrack@localhost:5432/hextrack"


def normalize_async_database_url(url: str) -> str:
    """Return ``url`` using the asyncpg driver (accepts plain ``postgresql://`` URLs)."""
    for prefix in (
        "postgresql+asyncpg://",
        "postgresql+psycopg://",
        "postgresql://",
        "postgres://",
    ):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


def _resolve_path(value: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = API_DIR / path
    return path.resolve()


class Settings(BaseSettings):
    """All runtime configuration for the API, worker, bot and CLI."""

    model_config = SettingsConfigDict(
        # Later files take priority: api/.env overrides the repo-root .env.
        env_file=(REPO_ROOT / ".env", API_DIR / ".env"),
        # systemd LoadCredential= (production): one file per secret, named like its env var
        # (RIOT_API_KEY, DISCORD_TOKEN, ...). Environment variables still take priority.
        secrets_dir=os.environ.get("CREDENTIALS_DIRECTORY") or None,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        protected_namespaces=(),
    )

    # --- database -------------------------------------------------------------------------
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL, validation_alias=AliasChoices("DATABASE_URL", "database_url")
    )

    # --- Riot -----------------------------------------------------------------------------
    riot_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("RIOT_API_KEY", "riot_api_key")
    )
    riot_platform: str = Field(
        default="na1", validation_alias=AliasChoices("RIOT_PLATFORM", "riot_platform")
    )
    riot_region: str = Field(
        default="americas", validation_alias=AliasChoices("RIOT_REGION", "riot_region")
    )
    #: Application rate limits as "count:seconds" pairs, e.g. "20:1,100:120". A ceiling: the
    #: limits Riot announces are capped by these for every window given here.
    riot_app_rate_limits: str = Field(
        default="20:1,100:120",
        validation_alias=AliasChoices("RIOT_APP_RATE_LIMITS", "riot_app_rate_limits"),
    )
    #: The share of the key the public on-demand endpoints (lookups, the Update button) may
    #: spend per routing value; requests beyond it fail fast with 429 instead of queuing.
    #: The standalone worker reserves this share (see :attr:`worker_app_rate_limits`).
    #: Empty disables both the cap and the reservation.
    riot_ondemand_rate_limits: str = Field(
        default="5:1,20:120",
        validation_alias=AliasChoices("RIOT_ONDEMAND_RATE_LIMITS", "riot_ondemand_rate_limits"),
    )
    #: Longest an HTTP request may sit in the Riot rate limiter before it is answered with
    #: 429 instead (the worker queues without a bound; the API never should).
    riot_ondemand_max_wait_seconds: float = Field(
        default=5.0,
        ge=0.0,
        validation_alias=AliasChoices(
            "RIOT_ONDEMAND_MAX_WAIT_SECONDS", "riot_ondemand_max_wait_seconds"
        ),
    )

    # --- HexTrack -------------------------------------------------------------------------
    model_dir: Path = Field(
        default=Path("./artifacts"),
        validation_alias=AliasChoices("HEXTRACK_MODEL_DIR", "model_dir"),
    )
    web_dist: Path = Field(
        default=Path("../web/dist"),
        validation_alias=AliasChoices("HEXTRACK_WEB_DIST", "web_dist"),
    )
    admin_token: str | None = Field(
        default=None, validation_alias=AliasChoices("HEXTRACK_ADMIN_TOKEN", "admin_token")
    )
    season_start: datetime = Field(
        default=datetime(2026, 1, 8, 20, 0, tzinfo=UTC),
        validation_alias=AliasChoices("HEXTRACK_SEASON_START", "season_start"),
    )
    #: Check the roster for live games (spectator-v5) after every poll.
    live_games: bool = Field(
        default=True,
        validation_alias=AliasChoices("HEXTRACK_LIVE_GAMES", "live_games"),
    )
    poll_interval_seconds: int = Field(
        default=120,
        ge=5,
        validation_alias=AliasChoices("HEXTRACK_POLL_INTERVAL_SECONDS", "poll_interval_seconds"),
    )
    ondemand_cooldown_seconds: int = Field(
        default=120,
        ge=0,
        validation_alias=AliasChoices(
            "HEXTRACK_ONDEMAND_COOLDOWN_SECONDS", "ondemand_cooldown_seconds"
        ),
    )
    ondemand_max_matches: int = Field(
        default=10,
        ge=0,
        validation_alias=AliasChoices("HEXTRACK_ONDEMAND_MAX_MATCHES", "ondemand_max_matches"),
    )
    backfill_count: int = Field(
        default=100,
        ge=1,
        le=100,
        validation_alias=AliasChoices("HEXTRACK_BACKFILL_COUNT", "backfill_count"),
    )
    poll_match_count: int = Field(
        default=20,
        ge=1,
        le=100,
        validation_alias=AliasChoices("HEXTRACK_POLL_MATCH_COUNT", "poll_match_count"),
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias=AliasChoices("HEXTRACK_CORS_ORIGINS", "cors_origins"),
    )
    public_url: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("HEXTRACK_PUBLIC_URL", "public_url"),
    )
    rank_icon_base: str | None = Field(
        default=None, validation_alias=AliasChoices("HEXTRACK_RANK_ICON_BASE", "rank_icon_base")
    )
    bad_game_embeds: bool = Field(
        default=False,
        validation_alias=AliasChoices("HEXTRACK_BAD_GAME_EMBEDS", "bad_game_embeds"),
    )

    # --- Discord --------------------------------------------------------------------------
    discord_token: str | None = Field(
        default=None, validation_alias=AliasChoices("DISCORD_TOKEN", "discord_token")
    )
    discord_broadcast_channel_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DISCORD_BROADCAST_CHANNEL_ID", "discord_broadcast_channel_id"
        ),
    )
    discord_daily_post_hour: int = Field(
        default=6,
        ge=0,
        le=23,
        validation_alias=AliasChoices("DISCORD_DAILY_POST_HOUR", "discord_daily_post_hour"),
    )
    discord_tz: str = Field(
        default="America/Chicago", validation_alias=AliasChoices("DISCORD_TZ", "discord_tz")
    )

    # --- runtime only (never read from the environment) -----------------------------------
    #: Run the poller inside the API process. Set by ``hextrack serve --with-worker`` (which
    #: exports HEXTRACK_RUN_WORKER_IN_PROCESS=1 so uvicorn's reloader children inherit it);
    #: not meant to be put in .env.
    run_worker_in_process: bool = Field(
        default=False,
        exclude=True,
        validation_alias=AliasChoices("HEXTRACK_RUN_WORKER_IN_PROCESS", "run_worker_in_process"),
    )

    # --- validators -----------------------------------------------------------------------
    @field_validator("database_url")
    @classmethod
    def _async_driver(cls, value: str) -> str:
        return normalize_async_database_url(value.strip())

    @field_validator(
        "riot_api_key", "admin_token", "discord_token", "rank_icon_base", mode="before"
    )
    @classmethod
    def _blank_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("discord_broadcast_channel_id", mode="before")
    @classmethod
    def _blank_channel_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("riot_platform", "riot_region")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("model_dir", "web_dist")
    @classmethod
    def _resolve(cls, value: Path) -> Path:
        return _resolve_path(value)

    @field_validator("season_start")
    @classmethod
    def _tz_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("riot_app_rate_limits")
    @classmethod
    def _validate_rate_limits(cls, value: str) -> str:
        parse_rate_limits(value)
        return value.strip()

    @field_validator("riot_ondemand_rate_limits")
    @classmethod
    def _validate_ondemand_limits(cls, value: str) -> str:
        parse_rate_limits(value, allow_empty=True)
        return value.strip()

    @field_validator("discord_tz")
    @classmethod
    def _validate_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r}") from exc
        return value

    # --- derived --------------------------------------------------------------------------
    @property
    def riot_key_configured(self) -> bool:
        return self.riot_api_key is not None

    @property
    def app_rate_limits(self) -> list[tuple[int, float]]:
        """Parsed ``RIOT_APP_RATE_LIMITS`` as ``[(max_requests, window_seconds), ...]``."""
        return parse_rate_limits(self.riot_app_rate_limits)

    @property
    def ondemand_rate_limits(self) -> list[tuple[int, float]]:
        """Parsed ``RIOT_ONDEMAND_RATE_LIMITS`` (empty when the cap is disabled)."""
        return parse_rate_limits(self.riot_ondemand_rate_limits, allow_empty=True)

    @property
    def worker_app_rate_limits(self) -> list[tuple[int, float]]:
        """Application limits for the poller: the configured ones minus the on-demand share,
        so lookups and the Update button still get through while a backfill runs."""
        reserved = {window: count for count, window in self.ondemand_rate_limits}
        return [
            (max(count - reserved.get(window, 0), 1), window)
            for count, window in self.app_rate_limits
        ]

    @property
    def sync_database_url(self) -> str:
        """``database_url`` rewritten for the synchronous psycopg driver."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)

    @property
    def discord_zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.discord_tz)

    @property
    def season_start_ms(self) -> int:
        return int(self.season_start.timestamp() * 1000)


def parse_rate_limits(spec: str, *, allow_empty: bool = False) -> list[tuple[int, float]]:
    """Parse "20:1,100:120" into ``[(20, 1.0), (100, 120.0)]`` (Riot header format).

    ``allow_empty`` accepts a blank value as "no limits" instead of raising.
    """
    limits: list[tuple[int, float]] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        count_str, sep, window_str = part.partition(":")
        if not sep:
            raise ValueError(f"invalid rate limit {part!r}; expected 'count:seconds'")
        count, window = int(count_str), float(window_str)
        if count <= 0 or window <= 0:
            raise ValueError(f"invalid rate limit {part!r}; values must be positive")
        limits.append((count, window))
    if not limits and not allow_empty:
        raise ValueError("at least one rate limit is required")
    return limits


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide cached settings."""
    return Settings()
