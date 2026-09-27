"""``hextrack crawl status`` against the test database, and the ladder seeding helper."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select, update
from typer.testing import CliRunner

from hextrack.cli import app
from hextrack.config import get_settings
from hextrack.db.models import AppState, CrawlPlayer, Match, Summoner
from hextrack.ingest.crawl_seed import SeedError, normalize_ladder, seed_from_ladder
from hextrack.riot.schemas import LeagueEntryDto
from tests.factories import make_match_json
from tests.test_ai_support import insert_matches

runner = CliRunner()


@pytest.fixture
def cli_env(settings, monkeypatch):
    """Point the CLI's cached settings at the test DB."""
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    get_settings.cache_clear()
    try:
        yield settings
    finally:
        get_settings.cache_clear()
        root.handlers[:] = handlers
        root.setLevel(level)


@pytest.fixture
async def empty_frontier(clean_db, session_factory):
    async with session_factory() as s:
        await s.execute(delete(CrawlPlayer))
        await s.commit()


async def test_crawl_status_prints_heartbeat_frontier_and_counts(
    empty_frontier, session_factory, cli_env
):
    now = datetime.now(UTC)
    ids = await insert_matches(
        session_factory,
        [make_match_json(f"NA1_CRAWLCLI{i}", start=now - timedelta(days=2)) for i in range(4)],
    )
    async with session_factory() as s:
        await s.execute(update(Match).where(Match.match_id.in_(ids[:3])).values(source="crawl"))
        # one crawled game ingested two days ago: not in the last 24 h
        await s.execute(
            update(Match)
            .where(Match.match_id == ids[0])
            .values(ingested_at=now - timedelta(days=2))
        )
        s.add_all(
            [
                CrawlPlayer(puuid="c1", found_via="ladder", tier="GOLD", division="II"),
                CrawlPlayer(
                    puuid="c2",
                    found_via="ladder",
                    tier="GOLD",
                    division="II",
                    crawled_at=now,
                    matches_added=3,
                ),
                CrawlPlayer(puuid="c3", found_via="ladder", tier="IRON", division="IV"),
                CrawlPlayer(puuid="c4", found_via="match", last_error="HTTP 500"),
                CrawlPlayer(puuid="c5", found_via="match", crawled_at=now),
            ]
        )
        s.add(
            AppState(
                key="crawler",
                value={
                    "running": True,
                    "updated_at": now.isoformat(),
                    "paused_reason": "budget",
                    "matches_added_today": 3,
                    "day": now.date().isoformat(),
                    "reserve": {"app_headroom": 17},
                },
            )
        )
        await s.commit()

    result = await asyncio.to_thread(runner.invoke, app, ["crawl", "status"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "running" in out and "paused: budget" in out
    assert "reserve.app_headroom" in out and "17" in out
    assert "Frontier by source" in out and "ladder" in out and "match" in out
    # Iron sorts before Gold; players found in games come last
    assert out.index("IRON IV") < out.index("GOLD II") < out.index("(found in games)")
    assert "crawled games: 3 stored (2 in the last 24 h) of 4 games" in out
    assert "database size:" in out
    assert "free disk:" in out


async def test_crawl_status_without_crawler(empty_frontier, cli_env):
    result = await asyncio.to_thread(runner.invoke, app, ["crawl", "status"])
    assert result.exit_code == 0, result.output
    assert "no heartbeat yet" in result.output
    assert "crawled games: 0 stored" in result.output


def test_crawl_help():
    result = runner.invoke(app, ["crawl", "--help"])
    assert result.exit_code == 0
    assert "status" in result.output and "seed" in result.output


def _entry(puuid: str | None) -> LeagueEntryDto:
    return LeagueEntryDto.model_validate(
        {
            "queueType": "RANKED_SOLO_5x5",
            "tier": "GOLD",
            "rank": "II",
            "leaguePoints": 10,
            "wins": 1,
            "losses": 1,
            "puuid": puuid,
        }
    )


class _LadderRiot:
    """Just enough of RiotClient for seeding: two pages, then empty."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, int]] = []
        self.pages = {1: [_entry("p1"), _entry("p2"), _entry(None)], 2: [_entry("p3")]}

    async def league_exp_entries(self, queue, tier, division, *, page=1):
        self.calls.append((queue, tier, division, page))
        return self.pages.get(page, [])


async def test_seed_from_ladder_skips_known_and_tracked(empty_frontier, session_factory, settings):
    async with session_factory() as s:
        s.add(CrawlPlayer(puuid="p2", found_via="match"))
        s.add(
            Summoner(
                puuid="p3", game_name="Tracked", tag_line="NA1", platform="NA1", is_tracked=True
            )
        )
        await s.commit()

    riot = _LadderRiot()
    ctx = SimpleNamespace(settings=settings, riot=riot)
    async with session_factory() as s:
        report = await seed_from_ladder(ctx, s, "gold", "ii", pages=3)
        await s.commit()

    assert [c[3] for c in riot.calls] == [1, 2, 3]
    assert riot.calls[0][:3] == ("RANKED_SOLO_5x5", "GOLD", "II")
    assert (report.listed, report.added, report.already_known, report.skipped_tracked) == (
        3,
        1,
        1,
        1,
    )
    async with session_factory() as s:
        rows = (await s.execute(select(CrawlPlayer).order_by(CrawlPlayer.puuid))).scalars().all()
    by_puuid = {r.puuid: r for r in rows}
    assert set(by_puuid) == {"p1", "p2"}
    assert (by_puuid["p1"].found_via, by_puuid["p1"].tier, by_puuid["p1"].division) == (
        "ladder",
        "GOLD",
        "II",
    )
    assert by_puuid["p2"].found_via == "match"  # untouched


def test_normalize_ladder():
    assert normalize_ladder(" gold ", "ii") == ("GOLD", "II")
    assert normalize_ladder("master", "I") == ("MASTER", "I")
    with pytest.raises(SeedError):
        normalize_ladder("wood", "I")
    with pytest.raises(SeedError):
        normalize_ladder("GOLD", "V")
    with pytest.raises(SeedError):
        normalize_ladder("CHALLENGER", "II")
