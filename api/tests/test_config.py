from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hextrack.config import API_DIR, Settings, parse_rate_limits


def make(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_defaults_and_paths():
    s = make()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.model_dir == (API_DIR / "artifacts").resolve()
    assert s.web_dist == (API_DIR.parent / "web" / "dist").resolve()
    assert s.season_start == datetime(2026, 1, 8, 20, tzinfo=UTC)
    assert s.app_rate_limits == [(20, 1.0), (100, 120.0)]
    assert s.sync_database_url.startswith("postgresql+psycopg://")


def test_env_parsing(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/d")
    monkeypatch.setenv("RIOT_API_KEY", "")
    monkeypatch.setenv("HEXTRACK_CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("HEXTRACK_SEASON_START", "2026-01-08T14:00:00-06:00")
    monkeypatch.setenv("DISCORD_BROADCAST_CHANNEL_ID", "")
    monkeypatch.setenv("HEXTRACK_BAD_GAME_EMBEDS", "true")
    s = make()
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/d"
    assert s.riot_api_key is None and not s.riot_key_configured
    assert s.cors_origins == ["http://a.test", "http://b.test"]
    assert s.season_start == datetime(2026, 1, 8, 20, tzinfo=UTC)
    assert s.discord_broadcast_channel_id is None
    assert s.bad_game_embeds is True


def test_validation():
    with pytest.raises(ValidationError):
        make(discord_tz="Mars/Olympus")
    with pytest.raises(ValidationError):
        make(riot_app_rate_limits="20")
    assert parse_rate_limits("500:10, 30000:600") == [(500, 10.0), (30000, 600.0)]
