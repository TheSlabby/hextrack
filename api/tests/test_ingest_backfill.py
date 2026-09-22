"""ingest.backfill: the one-off deep scrape that catches a stale roster up to Riot."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from hextrack.db.models import Summoner
from hextrack.ingest.backfill import (
    BackfillReport,
    _ranked_counts,
    _reset_sync_state,
    _select_players,
    run_ticks,
)
from tests.factories import match_series
from tests.test_ingest_support import IngestFakeRiot, make_ctx, stored_match_ids

SEASON_START = datetime(2026, 1, 8, 20, tzinfo=UTC)


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    return IngestFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    fast = settings.model_copy(update={"poll_interval_seconds": 0.05, "poll_match_count": 3})
    return make_ctx(fast, session_factory, riot)


async def _tracked(session, riot, name: str, *, synced_through: datetime | None) -> str:
    puuid = f"p-{name.lower()}"
    riot.add_account(name, "NA1", puuid=puuid, level=120)
    riot.add_league_entry(puuid, "RANKED_SOLO_5x5", "GOLD", "II", 40)
    session.add(
        Summoner(
            puuid=puuid,
            game_name=name,
            tag_line="NA1",
            platform="na1",
            is_tracked=True,
            tracked_since=datetime(2026, 1, 1, tzinfo=UTC),
            backfilled_at=datetime(2026, 1, 2, tzinfo=UTC),
            synced_through=synced_through,
        )
    )
    await session.commit()
    return puuid


async def test_backfill_recovers_games_a_stale_watermark_would_skip(ctx, riot, session):
    """The roster's real problem: the poller was off for months, so the watermark sits far
    in the past-future of the stored history and steady-state discovery lists from it."""
    series = match_series("p-stale", 9, game_name="Stale", start=ctx.settings.season_start)
    for raw in series:
        riot.add_match(raw)
    # Watermark claims everything is synced through the newest game, but nothing is stored.
    newest = datetime.fromtimestamp(series[-1]["info"]["gameStartTimestamp"] / 1000, tz=UTC)
    await _tracked(session, riot, "Stale", synced_through=newest)

    report = BackfillReport(since=ctx.settings.season_start)
    async with ctx.session_factory() as s:
        before = await _ranked_counts(s, ["p-stale"])
        await _reset_sync_state(s, ["p-stale"])
        await s.commit()
    await run_ticks(ctx, ["p-stale"], report, max_ticks=5)

    assert before.get("p-stale", 0) == 0
    assert await stored_match_ids(session) == {r["metadata"]["matchId"] for r in series}
    async with ctx.session_factory() as s:
        after = await _ranked_counts(s, ["p-stale"])
        row = await s.get(Summoner, "p-stale")
    assert after["p-stale"] == 9
    assert row is not None and row.backfilled_at is not None and row.synced_through is not None
    assert report.matches_ingested == 9 and report.ticks <= 5


async def test_reset_only_touches_the_selected_players(ctx, riot, session):
    await _tracked(session, riot, "Kept", synced_through=SEASON_START)
    await _tracked(session, riot, "Reset", synced_through=SEASON_START)

    async with ctx.session_factory() as s:
        assert await _reset_sync_state(s, ["p-reset"]) == 1
        await s.commit()

    rows = {
        r.puuid: r
        for r in (await session.scalars(select(Summoner).where(Summoner.is_tracked))).all()
    }
    assert rows["p-reset"].synced_through is None and rows["p-reset"].backfilled_at is None
    assert rows["p-kept"].synced_through == SEASON_START
    assert rows["p-kept"].backfilled_at is not None


async def test_select_players_filters_by_riot_id_and_rejects_unknown(ctx, riot, session):
    await _tracked(session, riot, "Alpha", synced_through=None)
    await _tracked(session, riot, "Beta", synced_through=None)

    async with ctx.session_factory() as s:
        everyone = await _select_players(s, None)
        just_one = await _select_players(s, ["alpha#na1"])
        with pytest.raises(ValueError, match="not on the tracked roster"):
            await _select_players(s, ["Ghost#NA1"])

    assert {p.game_name for p in everyone} == {"Alpha", "Beta"}
    assert [p.game_name for p in just_one] == ["Alpha"]
