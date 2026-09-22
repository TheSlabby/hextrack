"""ingest.service: match ingestion, scoring, events, renames and match discovery."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from hextrack.db.models import BotEvent, Match, MatchParticipant, Summoner
from hextrack.db.repo import summoners as summoners_repo
from hextrack.ingest import service
from hextrack.ingest.mapping import InvalidMatchPayload
from hextrack.ingest.service import discover_matches, ingest_match, ingest_match_json
from hextrack.riot.errors import RiotBadResponse, RiotRateLimited, RiotUnavailable
from tests.factories import make_match_json, match_series, spec
from tests.test_ingest_support import (
    IngestFakeRiot,
    StubScorer,
    count,
    events_of,
    make_ctx,
    participants_of,
    recent,
    stored_match_ids,
)


@pytest.fixture
def riot(settings) -> IngestFakeRiot:
    return IngestFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


def _summoner(puuid: str, name: str, tag: str = "NA1", *, tracked: bool = True) -> Summoner:
    return Summoner(
        puuid=puuid,
        game_name=name,
        tag_line=tag,
        platform="na1",
        profile_icon_id=7,
        is_tracked=tracked,
        tracked_since=datetime(2026, 1, 1, tzinfo=UTC) if tracked else None,
    )


# --- storing ---------------------------------------------------------------------------------


async def test_ingest_match_stores_match_and_participants(ctx, riot, session):
    raw = make_match_json("NA1_100", [spec("me", "Me", "NA1", kills=7)], start=recent())
    riot.add_match(raw)

    result = await ingest_match(ctx, session, "NA1_100")
    await session.commit()

    assert result == service.IngestResult("NA1_100", created=True, scored=False, participants=10)
    match = await session.get(Match, "NA1_100")
    assert match is not None
    assert match.raw == raw and match.queue_id == 420 and match.scored_at is None
    rows = await participants_of(session, "NA1_100")
    assert len(rows) == 10
    assert rows[0].puuid == "me" and rows[0].kills == 7
    assert all(r.ai_score is None and r.model_version is None for r in rows)


async def test_ingest_is_idempotent(ctx, riot, session):
    raw = make_match_json("NA1_101", start=recent())
    riot.add_match(raw)

    first = await ingest_match(ctx, session, "NA1_101")
    await session.commit()
    second = await ingest_match(ctx, session, "NA1_101")
    again = await ingest_match_json(ctx, session, copy.deepcopy(raw))
    await session.commit()

    assert first is not None and first.created
    assert second == service.IngestResult("NA1_101", created=False, scored=False, participants=10)
    assert again.created is False and again.participants == 10
    # an already stored match is never fetched again
    assert len(riot.calls_to("match")) == 1
    assert await count(session, Match) == 1
    assert await count(session, MatchParticipant) == 10


@pytest.mark.parametrize(
    "corrupt",
    [
        {"status": {"status_code": 429, "message": "Rate limit exceeded"}},
        {"metadata": {"matchId": "NA1_102"}},
        {"metadata": {"matchId": "NA1_102"}, "info": {"gameMode": "CLASSIC"}},
        "not even an object",
    ],
    ids=["riot-error-body", "no-info", "truncated-info", "not-an-object"],
)
async def test_corrupt_payload_is_never_stored(ctx, riot, session, corrupt):
    riot.add_match(make_match_json("NA1_102", start=recent()))
    riot.corrupt["NA1_102"] = corrupt

    assert await ingest_match(ctx, session, "NA1_102") is None
    await session.commit()
    assert await stored_match_ids(session) == set()
    assert await count(session, MatchParticipant) == 0
    assert await count(session, BotEvent) == 0


async def test_payload_with_nine_participants_or_other_id_is_rejected(ctx, riot, session):
    short = make_match_json("NA1_103", start=recent())
    short["info"]["participants"].pop()
    riot.add_match(make_match_json("NA1_103", start=recent()))
    riot.corrupt["NA1_103"] = short
    other = make_match_json("NA1_999", start=recent())
    riot.add_match(make_match_json("NA1_104", start=recent()))
    riot.corrupt["NA1_104"] = other

    assert await ingest_match(ctx, session, "NA1_103") is None
    assert await ingest_match(ctx, session, "NA1_104") is None
    await session.commit()
    assert await stored_match_ids(session) == set()

    with pytest.raises(InvalidMatchPayload):
        await ingest_match_json(ctx, session, short)
    assert await stored_match_ids(session) == set()


async def test_not_found_and_bad_response_return_none(ctx, riot, session):
    assert await ingest_match(ctx, session, "NA1_404") is None
    riot.add_match(make_match_json("NA1_105", start=recent()))
    riot.fail("match", RiotBadResponse("body failed validation"))
    assert await ingest_match(ctx, session, "NA1_105") is None
    assert await stored_match_ids(session) == set()


@pytest.mark.parametrize("error", [RiotRateLimited(retry_after=3), RiotUnavailable("503")])
async def test_transient_riot_errors_propagate(ctx, riot, session, error):
    riot.add_match(make_match_json("NA1_106", start=recent()))
    riot.fail("match", error)
    with pytest.raises(type(error)):
        await ingest_match(ctx, session, "NA1_106")
    assert await stored_match_ids(session) == set()


# --- scoring ---------------------------------------------------------------------------------


async def test_scores_every_participant_with_the_loaded_model(ctx, riot, session):
    scorer = StubScorer("model-v7")
    ctx.scorer = scorer
    riot.add_match(make_match_json("NA1_110", duration_s=1500, start=recent()))

    result = await ingest_match(ctx, session, "NA1_110")
    await session.commit()

    assert result is not None and result.scored is True
    assert scorer.calls == [(1500, 10)]
    rows = await participants_of(session, "NA1_110")
    assert [r.ai_score for r in rows] == pytest.approx([0.05 + 0.09 * i for i in range(10)])
    assert {r.model_version for r in rows} == {"model-v7"}
    assert all(r.ai_scored_at is not None for r in rows)
    match = await session.get(Match, "NA1_110", populate_existing=True)
    assert match is not None
    assert match.model_version == "model-v7" and match.scored_at is not None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"remake": True, "duration_s": 200},
        {"game_mode": "ARAM", "queue_id": 450},
        {"end_of_game_result": "Abort_Unexpected"},
    ],
    ids=["remake", "aram", "aborted"],
)
async def test_unscorable_matches_are_stored_unscored(ctx, session, kwargs):
    scorer = StubScorer()
    ctx.scorer = scorer
    raw = make_match_json("NA1_111", start=recent(), **kwargs)

    result = await ingest_match_json(ctx, session, raw)
    await session.commit()

    assert result.created and result.scored is False
    assert scorer.calls == []
    rows = await participants_of(session, "NA1_111")
    assert len(rows) == 10 and all(r.ai_score is None for r in rows)


async def test_model_failure_still_stores_the_match(ctx, session):
    ctx.scorer = StubScorer(fail=True)
    result = await ingest_match_json(ctx, session, make_match_json("NA1_112", start=recent()))
    await session.commit()
    assert result.created and not result.scored
    assert all(r.ai_score is None for r in await participants_of(session, "NA1_112"))


async def test_incomplete_model_output_is_not_written(ctx, session):
    class HalfScorer(StubScorer):
        def score_match(self, game_duration_seconds, participants):
            scores = super().score_match(game_duration_seconds, participants)
            return dict(list(scores.items())[:5]) | {participants[5]["puuid"]: float("nan")}

    ctx.scorer = HalfScorer()
    result = await ingest_match_json(ctx, session, make_match_json("NA1_113", start=recent()))
    assert not result.scored
    assert all(r.ai_score is None for r in await participants_of(session, "NA1_113"))


async def test_out_of_range_scores_are_clamped(ctx, session):
    class WildScorer(StubScorer):
        def score_match(self, game_duration_seconds, participants):
            return {p["puuid"]: (1.7 if i % 2 else -0.2) for i, p in enumerate(participants)}

    ctx.scorer = WildScorer()
    await ingest_match_json(ctx, session, make_match_json("NA1_114", start=recent()))
    scores = [r.ai_score for r in await participants_of(session, "NA1_114")]
    assert scores == [0.0, 1.0] * 5


# --- summoners -------------------------------------------------------------------------------


async def test_last_seen_only_moves_forward(ctx, session):
    session.add(_summoner("me", "Me", tracked=False))
    await session.commit()
    newer = datetime(2026, 3, 5, 20, tzinfo=UTC)
    older = datetime(2026, 3, 2, 20, tzinfo=UTC)

    await ingest_match_json(ctx, session, make_match_json("NA1_120", [spec("me")], start=newer))
    await ingest_match_json(ctx, session, make_match_json("NA1_121", [spec("me")], start=older))
    await session.commit()

    me = await session.get(Summoner, "me", populate_existing=True)
    assert me is not None and me.last_seen == newer
    # unknown participants are not created as summoners
    assert await count(session, Summoner) == 1


async def test_rename_is_adopted_from_the_newest_game_only(ctx, session):
    session.add(_summoner("me", "Old Name", "NA1"))
    await session.commit()

    older = make_match_json(
        "NA1_130", [spec("me", "Ancient", "OLD")], start=datetime(2026, 3, 1, tzinfo=UTC)
    )
    newer = make_match_json(
        "NA1_131", [spec("me", "New Name", "NEW")], start=datetime(2026, 3, 9, tzinfo=UTC)
    )
    await ingest_match_json(ctx, session, newer)
    await ingest_match_json(ctx, session, older)
    await session.commit()

    me = await session.get(Summoner, "me", populate_existing=True)
    assert me is not None and (me.game_name, me.tag_line) == ("New Name", "NEW")


async def test_rename_to_a_riot_id_held_by_another_row_is_skipped(ctx, session):
    session.add_all([_summoner("me", "Me"), _summoner("other", "Taken", "TAG")])
    await session.commit()

    raw = make_match_json("NA1_132", [spec("me", "taken", "tag")], start=recent())
    await ingest_match_json(ctx, session, raw)
    await session.commit()

    me = await session.get(Summoner, "me", populate_existing=True)
    assert me is not None and me.game_name == "Me"


# --- events ----------------------------------------------------------------------------------


async def test_great_bad_and_new_match_events_for_tracked_players(ctx, session):
    session.add_all(
        [
            _summoner("great", "Great"),
            _summoner("bad", "Bad"),
            _summoner("zero", "Zero"),
            _summoner("stranger", "Stranger", tracked=False),
        ]
    )
    await session.commit()
    start = recent()
    raw = make_match_json(
        "NA1_140",
        [
            spec("great", "Great", "NA1", kills=10, deaths=1, assists=5),  # KDA 15
            spec("bad", "Bad", "NA1", kills=1, deaths=5, assists=2),  # KDA 0.6
            spec("zero", "Zero", "NA1", kills=0, deaths=0, assists=0),  # KDA 0, no deaths
            spec("stranger", "Stranger", "NA1", kills=20, deaths=0, assists=9),
        ],
        start=start,
        duration_s=1745,
    )

    await ingest_match_json(ctx, session, raw)
    await session.commit()

    rows = await events_of(session)
    by_kind = {(e.kind, e.payload["puuid"]) for e in rows}
    assert by_kind == {
        ("new_match", "great"),
        ("great_game", "great"),
        ("new_match", "bad"),
        ("bad_game", "bad"),
        ("new_match", "zero"),
    }
    assert all(e.processed_at is None and e.attempts == 0 for e in rows)
    great = next(e.payload for e in rows if e.kind == "great_game")
    assert great == {
        "puuid": "great",
        "game_name": "Great",
        "tag_line": "NA1",
        "profile_icon_id": 4000,
        "match_id": "NA1_140",
        "queue_id": 420,
        "champion_id": 266,
        "champion_name": "Aatrox",
        "team_position": "TOP",
        "win": True,
        "remake": False,
        "kills": 10,
        "deaths": 1,
        "assists": 5,
        "kda": 15.0,
        "ai_score": None,
        "model_version": None,
        "game_start": start.isoformat(),
        "game_duration": 1745,
    }


async def test_kda_threshold_is_strict(ctx, session):
    session.add_all([_summoner("six", "Six"), _summoner("one", "One")])
    await session.commit()
    raw = make_match_json(
        "NA1_141",
        [
            spec("six", kills=4, deaths=1, assists=2),  # exactly 6.0: not great
            spec("one", kills=1, deaths=2, assists=1),  # exactly 1.0: not bad
        ],
        start=recent(),
    )
    await ingest_match_json(ctx, session, raw)
    assert {e.kind for e in await events_of(session)} == {"new_match"}


async def test_game_events_carry_the_ai_score(ctx, session):
    session.add(_summoner("me", "Me"))
    await session.commit()
    ctx.scorer = StubScorer("model-v9")
    raw = make_match_json("NA1_142", [spec("me", kills=12, deaths=0, assists=3)], start=recent())

    await ingest_match_json(ctx, session, raw)

    great = (await events_of(session, "great_game"))[0].payload
    assert great["ai_score"] == pytest.approx(0.05)
    assert great["model_version"] == "model-v9"
    assert great["kda"] == 15.0


async def test_events_only_for_newly_stored_recent_matches(ctx, session):
    session.add(_summoner("me", "Me"))
    await session.commit()
    raw = make_match_json("NA1_143", [spec("me", kills=12, deaths=1, assists=3)], start=recent())

    await ingest_match_json(ctx, session, raw)
    await ingest_match_json(ctx, session, copy.deepcopy(raw))
    assert len(await events_of(session)) == 2  # new_match + great_game, once

    # legacy import / demo seed path
    await ingest_match_json(
        ctx, session, make_match_json("NA1_144", [spec("me")], start=recent()), enqueue_events=False
    )
    # a season backfill of old games must not flood Discord
    old = make_match_json(
        "NA1_145", [spec("me", kills=20, deaths=0)], start=datetime.now(UTC) - timedelta(days=3)
    )
    await ingest_match_json(ctx, session, old)
    assert len(await events_of(session)) == 2


async def test_remake_only_produces_new_match(ctx, session):
    session.add(_summoner("me", "Me"))
    await session.commit()
    raw = make_match_json(
        "NA1_146", [spec("me", kills=0, deaths=3, assists=0)], start=recent(), remake=True
    )
    await ingest_match_json(ctx, session, raw)
    rows = await events_of(session)
    assert [e.kind for e in rows] == ["new_match"] and rows[0].payload["remake"] is True


# --- discovery -------------------------------------------------------------------------------


async def test_discover_season_filters_stored_ids(ctx, riot, session):
    series = match_series("me", 5, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    ids_newest_first = [r["metadata"]["matchId"] for r in reversed(series)]
    await ingest_match_json(ctx, session, series[0])
    await session.commit()

    found = await service.discover(ctx, session, "me", backfill=False)

    assert found.mode == "season" and found.complete is True
    assert found.missing == ids_newest_first[:-1]
    assert found.listed == ids_newest_first
    (call,) = riot.calls_to("match_ids_by_puuid")
    assert call.kwargs == {
        "start": 0,
        "count": ctx.settings.backfill_count,
        "queue": None,
        "type_": "ranked",
        "start_time": ctx.settings.season_start,
    }


async def test_discover_season_finds_holes_below_stored_games(ctx, riot, session, settings):
    """Stored history is only contiguous below the watermark. Without one, discovery pages
    the whole season instead of stopping at the first page that has a stored id: that is
    how games in a half-filled gap used to be lost for good."""
    ctx.settings = settings.model_copy(update={"backfill_count": 3})
    series = match_series("me", 8, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    # The two newest games are stored, with a hole below them.
    for raw in series[6:]:
        await ingest_match_json(ctx, session, raw)
    await session.commit()

    new = await discover_matches(ctx, session, "me", backfill=False)

    assert new == [r["metadata"]["matchId"] for r in reversed(series[:6])]
    assert [c.kwargs["start"] for c in riot.calls_to("match_ids_by_puuid")] == [0, 3, 6]


async def test_discover_season_fills_gaps_longer_than_one_page(ctx, riot, session, settings):
    """A player who played more games than one page since the last stored game must not
    lose the older ones (the imported legacy roster resumes after a months-long gap)."""
    ctx.settings = settings.model_copy(update={"backfill_count": 3})
    series = match_series("me", 8, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    await ingest_match_json(ctx, session, series[0])
    await session.commit()

    new = await discover_matches(ctx, session, "me", backfill=False)

    assert new == [r["metadata"]["matchId"] for r in reversed(series[1:])]
    assert [c.kwargs["start"] for c in riot.calls_to("match_ids_by_puuid")] == [0, 3, 6]


async def test_discover_is_capped_and_says_so(ctx, riot, session, settings):
    """A capped listing is incomplete, which is what keeps the watermark from claiming
    games the listing never looked at."""
    ctx.settings = settings.model_copy(update={"backfill_count": 2})
    for raw in match_series("me", 9, game_name="Me"):
        riot.add_match(raw)

    found = await service.discover(ctx, session, "me", backfill=True, max_ids=4)

    assert len(found.listed) == 4 and found.complete is False
    assert len(riot.calls_to("match_ids_by_puuid")) == 2


async def test_discover_since_the_watermark_lists_only_newer_games(ctx, riot, session, settings):
    """With a watermark, discovery lists from it instead of scanning the whole season."""
    series = match_series("me", 6, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    session.add(Summoner(puuid="me", game_name="Me", tag_line="NA1", platform="na1"))
    await session.flush()
    for raw in series[:4]:
        await ingest_match_json(ctx, session, raw)
    watermark = series[3]["info"]["gameStartTimestamp"]
    await summoners_repo.advance_synced_through(
        session, "me", datetime.fromtimestamp(watermark / 1000, tz=UTC)
    )
    await session.commit()

    found = await service.discover(ctx, session, "me", backfill=False)

    assert found.mode == "since" and found.complete is True
    assert found.missing == [r["metadata"]["matchId"] for r in reversed(series[4:])]
    (call,) = riot.calls_to("match_ids_by_puuid")
    assert call.kwargs["start_time"] < datetime.fromtimestamp(watermark / 1000, tz=UTC)
    # Only games around the watermark were listed, not the whole season.
    assert all(i in found.listed for i in found.missing)
    assert series[0]["metadata"]["matchId"] not in found.listed


async def test_watermark_moves_up_over_the_stored_prefix_only(ctx, riot, session, settings):
    """The watermark stops at the first game that is still missing, so a partly ingested
    gap is listed again next time instead of being skipped forever."""
    series = match_series("me", 4, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    session.add(Summoner(puuid="me", game_name="Me", tag_line="NA1", platform="na1"))
    await session.flush()
    # Oldest two stored, third missing, newest stored.
    for raw in (series[0], series[1], series[3]):
        await ingest_match_json(ctx, session, raw)
    await session.commit()

    found = await service.discover(ctx, session, "me", backfill=True)
    moved = await service.advance_sync(session, found, resolved=set())
    await session.commit()

    second_start = datetime.fromtimestamp(series[1]["info"]["gameStartTimestamp"] / 1000, tz=UTC)
    assert moved == second_start
    assert await summoners_repo.get_synced_through(session, "me") == second_start

    # Once the hole is filled the watermark jumps to the newest game.
    await ingest_match_json(ctx, session, series[2])
    await session.commit()
    found = await service.discover(ctx, session, "me", backfill=True)
    moved = await service.advance_sync(session, found, resolved=set())
    await session.commit()
    newest = datetime.fromtimestamp(series[3]["info"]["gameStartTimestamp"] / 1000, tz=UTC)
    assert moved == newest


async def test_watermark_does_not_move_on_an_incomplete_listing(ctx, riot, session, settings):
    ctx.settings = settings.model_copy(update={"backfill_count": 2})
    series = match_series("me", 6, game_name="Me")
    for raw in series:
        riot.add_match(raw)
    session.add(Summoner(puuid="me", game_name="Me", tag_line="NA1", platform="na1"))
    await session.flush()
    for raw in series[4:]:
        await ingest_match_json(ctx, session, raw)
    await session.commit()

    found = await service.discover(ctx, session, "me", backfill=True, max_ids=2)
    assert found.complete is False
    # Games older than the cap were never listed, so nothing about them is settled.
    assert await service.advance_sync(session, found, resolved=set()) is None
    assert await summoners_repo.get_synced_through(session, "me") is None


async def test_discover_without_stored_games_takes_one_page(ctx, riot, session, settings):
    ctx.settings = settings.model_copy(update={"poll_match_count": 3})
    for raw in match_series("stranger", 8, game_name="Stranger"):
        riot.add_match(raw)

    new = await discover_matches(ctx, session, "stranger", backfill=False)

    assert len(new) == 3
    (call,) = riot.calls_to("match_ids_by_puuid")
    assert call.kwargs["start_time"] is None


async def test_discover_backfill_pages_from_season_start(ctx, riot, session, settings):
    ctx.settings = settings.model_copy(update={"backfill_count": 3})
    before_season = settings.season_start - timedelta(days=2)
    riot.add_match(make_match_json("NA1_1", [spec("me")], start=before_season))
    series = match_series("me", 7, game_name="Me")
    for raw in series:
        riot.add_match(raw)

    new = await discover_matches(ctx, session, "me", backfill=True)

    assert new == [r["metadata"]["matchId"] for r in reversed(series)]
    calls = riot.calls_to("match_ids_by_puuid")
    assert [c.kwargs["start"] for c in calls] == [0, 3, 6]
    assert all(c.kwargs["count"] == 3 for c in calls)
    assert all(c.kwargs["start_time"] == settings.season_start for c in calls)
    assert all(c.kwargs["type_"] == "ranked" for c in calls)


async def test_discover_backfill_is_capped(ctx, riot, session, settings, monkeypatch):
    monkeypatch.setattr(service, "MAX_BACKFILL_IDS", 4)
    ctx.settings = settings.model_copy(update={"backfill_count": 2})
    for raw in match_series("me", 9, game_name="Me"):
        riot.add_match(raw)

    new = await discover_matches(ctx, session, "me", backfill=True)

    assert len(new) == 4
    assert len(riot.calls_to("match_ids_by_puuid")) == 2


async def test_discover_returns_nothing_when_all_stored(ctx, riot, session):
    series = match_series("me", 2, game_name="Me")
    for raw in series:
        riot.add_match(raw)
        await ingest_match_json(ctx, session, raw)
    assert await discover_matches(ctx, session, "me", backfill=False) == []
    assert await discover_matches(ctx, session, "unknown-puuid", backfill=False) == []


async def test_stored_participant_rows_match_payload_order(ctx, session):
    raw = make_match_json("NA1_150", start=recent())
    await ingest_match_json(ctx, session, raw)
    rows = await participants_of(session, "NA1_150")
    assert [r.puuid for r in rows] == [p["puuid"] for p in raw["info"]["participants"]]
    stored = await session.scalar(select(Match.patch).where(Match.match_id == "NA1_150"))
    assert stored == "16.17"
