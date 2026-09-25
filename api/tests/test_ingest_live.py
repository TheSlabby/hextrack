"""ingest.live: spectator rounds, rank lookups for new games, stored state, poller hook."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select

from hextrack.db.models import AppState, Summoner
from hextrack.db.repo import app_state as app_state_repo
from hextrack.ingest import live, poller
from hextrack.ingest.live import STATE_KEY, refresh_live_games
from hextrack.riot.errors import (
    RiotBadResponse,
    RiotError,
    RiotForbidden,
    RiotKeyMissing,
    RiotRateLimited,
    RiotUnavailable,
)
from hextrack.riot.schemas import CurrentGameInfoDto
from tests.fakes import Call
from tests.test_ingest_support import IngestFakeRiot, make_ctx


class LiveFakeRiot(IngestFakeRiot):
    """IngestFakeRiot plus spectator-v5: ``games`` maps puuid -> raw CurrentGameInfo JSON;
    ``fail_for`` maps puuid -> error raised for that player only."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.games: dict[str, dict[str, Any]] = {}
        self.fail_for: dict[str, RiotError] = {}

    def start_game(self, raw: dict[str, Any]) -> None:
        for p in raw["participants"]:
            if p.get("puuid"):
                self.games[p["puuid"]] = raw

    def end_game(self, game_id: int) -> None:
        self.games = {k: v for k, v in self.games.items() if v["gameId"] != game_id}

    async def active_game_by_puuid(self, puuid: str) -> CurrentGameInfoDto | None:
        if puuid in self.fail_for:
            self.calls.append(Call("active_game_by_puuid", (puuid,)))
            raise self.fail_for[puuid]
        self._enter("active_game_by_puuid", puuid)
        raw = self.games.get(puuid)
        return CurrentGameInfoDto.model_validate(raw) if raw is not None else None


def live_game(
    game_id: int,
    players: list[str],
    *,
    bots: int = 0,
    queue: int = 420,
    game_type: str = "MATCHED",
) -> dict[str, Any]:
    """Raw spectator JSON: ``players`` (puuids) alternate teams, then ``bots`` bots."""
    participants: list[dict[str, Any]] = [
        {
            "puuid": puuid,
            "teamId": 100 if i % 2 == 0 else 200,
            "championId": 1 + i,
            "spell1Id": 4,
            "spell2Id": 14,
            "riotId": f"{puuid}#NA1",
            "profileIconId": 29,
            "bot": False,
            "perks": {"perkIds": [8112, 8139], "perkStyle": 8100, "perkSubStyle": 8300},
        }
        for i, puuid in enumerate(players)
    ]
    participants += [
        {"puuid": None, "teamId": 200, "championId": 90 + i, "bot": True, "riotId": None}
        for i in range(bots)
    ]
    return {
        "gameId": game_id,
        "gameType": game_type,
        "gameStartTime": 1_790_000_000_000,
        "mapId": 11,
        "gameLength": 300,
        "platformId": "NA1",
        "gameMode": "CLASSIC" if game_type != "CUSTOM_GAME" else "PRACTICETOOL",
        "gameQueueConfigId": queue,
        "bannedChampions": [{"championId": 99, "teamId": 100, "pickTurn": 1}],
        "observers": {"encryptionKey": "abc"},
        "participants": participants,
    }


@pytest.fixture
def riot(settings) -> LiveFakeRiot:
    return LiveFakeRiot(settings)


@pytest.fixture
def ctx(clean_db, settings, session_factory, riot):
    return make_ctx(settings, session_factory, riot)


async def _roster(session, *names: str) -> list[str]:
    """Tracked summoners (roster order = name order); returns puuids."""
    puuids = []
    for name in names:
        puuid = f"p-{name.lower()}"
        session.add(
            Summoner(
                puuid=puuid,
                game_name=name,
                tag_line="NA1",
                platform="na1",
                is_tracked=True,
                tracked_since=datetime(2026, 1, 1, tzinfo=UTC),
                backfilled_at=datetime(2026, 1, 2, tzinfo=UTC),
            )
        )
        puuids.append(puuid)
    await session.commit()
    return puuids


async def _state(session) -> dict[str, Any] | None:
    value = await session.scalar(
        select(AppState.value)
        .where(AppState.key == STATE_KEY)
        .execution_options(populate_existing=True)
    )
    return dict(value) if value is not None else None


def _games(state: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    assert state is not None
    return {g["info"]["gameId"]: g for g in state["games"]}


def _spectated(riot: LiveFakeRiot) -> list[str]:
    return [c.args[0] for c in riot.calls_to("active_game_by_puuid")]


def _rank_lookups(riot: LiveFakeRiot) -> list[str]:
    return [c.args[0] for c in riot.calls_to("league_entries_by_puuid")]


# --- one round -------------------------------------------------------------------------------


async def test_one_call_covers_every_roster_player_in_the_game(ctx, riot, session):
    a, b, c = await _roster(session, "Alpha", "Bravo", "Charlie")
    riot.start_game(live_game(1, [a, "x1", b, "x2"]))

    report = await refresh_live_games(ctx)

    # Alpha's game covers Bravo; Charlie is checked and not in a game.
    assert _spectated(riot) == [a, c]
    assert report.checked == 2 and report.games == 1 and report.errors == []
    state = await _state(session)
    assert state is not None
    assert datetime.fromisoformat(state["checked_at"]) <= datetime.now(UTC)
    (game,) = state["games"]
    assert game["info"]["gameId"] == 1
    assert game["first_seen_at"] == game["seen_at"] == state["checked_at"]


async def test_nobody_in_game_stores_an_empty_list(ctx, riot, session):
    await _roster(session, "Alpha", "Bravo")

    report = await refresh_live_games(ctx)

    assert (report.checked, report.games, report.rank_lookups) == (2, 0, 0)
    assert _games(await _state(session)) == {}


async def test_new_game_looks_up_ranks_of_non_roster_players_only(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    riot.add_league_entry("x1", "RANKED_SOLO_5x5", "GOLD", "II", 45)
    riot.start_game(live_game(7, [a, "x1", b, "x2"], bots=2))

    report = await refresh_live_games(ctx)

    assert sorted(_rank_lookups(riot)) == ["x1", "x2"]  # no roster players, no bots
    assert report.rank_lookups == 2
    ranks = _games(await _state(session))[7]["ranks"]
    assert set(ranks) == {"x1", "x2"}
    assert ranks["x2"] == []  # unranked is stored, so it isn't asked again
    (entry,) = ranks["x1"]
    assert entry["queueType"] == "RANKED_SOLO_5x5" and entry["tier"] == "GOLD"
    assert entry["leaguePoints"] == 45


async def test_continuing_game_keeps_first_seen_and_ranks(ctx, riot, session):
    (a,) = await _roster(session, "Alpha")
    riot.add_league_entry("x1", "RANKED_SOLO_5x5", "SILVER", "I", 10)
    raw = live_game(3, [a, "x1"])
    riot.start_game(raw)
    await refresh_live_games(ctx)
    first = _games(await _state(session))[3]

    # Riot's data moves on; the changed league entry must not be fetched again.
    raw["gameLength"] = 900
    riot.add_league_entry("x1", "RANKED_SOLO_5x5", "GOLD", "IV", 0)
    report = await refresh_live_games(ctx)

    assert report.rank_lookups == 0 and len(_rank_lookups(riot)) == 1
    second = _games(await _state(session))[3]
    assert second["first_seen_at"] == first["first_seen_at"]
    assert second["seen_at"] > first["seen_at"]
    assert second["ranks"] == first["ranks"]
    assert second["info"]["gameLength"] == 900


async def test_failed_rank_lookups_are_retried_next_round(ctx, riot, session):
    (a,) = await _roster(session, "Alpha")
    riot.start_game(live_game(4, [a, "x1", "x2"]))
    riot.fail("league_entries_by_puuid", RiotBadResponse("bad body"))

    report = await refresh_live_games(ctx)
    assert report.rank_lookups == 2 and len(report.errors) == 1
    assert set(_games(await _state(session))[4]["ranks"]) == {"x2"}

    report = await refresh_live_games(ctx)
    assert report.rank_lookups == 1 and _rank_lookups(riot)[-1] == "x1"
    assert set(_games(await _state(session))[4]["ranks"]) == {"x1", "x2"}


async def test_finished_game_disappears(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    riot.start_game(live_game(1, [a, "x1"]))
    riot.start_game(live_game(2, [b, "x2"]))
    await refresh_live_games(ctx)
    assert set(_games(await _state(session))) == {1, 2}

    riot.end_game(1)
    report = await refresh_live_games(ctx)

    assert report.games == 1
    assert set(_games(await _state(session))) == {2}


async def test_player_moving_to_a_new_game_replaces_the_old_one(ctx, riot, session):
    (a,) = await _roster(session, "Alpha")
    riot.start_game(live_game(1, [a]))
    await refresh_live_games(ctx)
    riot.end_game(1)
    riot.start_game(live_game(2, [a]))

    await refresh_live_games(ctx)

    assert set(_games(await _state(session))) == {2}


@pytest.mark.parametrize(
    "game",
    [
        live_game(9, ["p-alpha", "x1"], game_type="CUSTOM_GAME", queue=0),
        live_game(9, ["p-alpha", "x1"], queue=0),
    ],
    ids=["custom", "queue-0"],
)
async def test_custom_games_are_skipped(ctx, riot, session, game):
    await _roster(session, "Alpha")
    riot.start_game(game)

    report = await refresh_live_games(ctx)

    assert (report.checked, report.games, report.rank_lookups) == (1, 0, 0)
    assert _games(await _state(session)) == {}


@pytest.mark.parametrize(
    "error", [RiotRateLimited(retry_after=5), RiotUnavailable("down", status=503)]
)
async def test_interrupted_round_keeps_games_it_could_not_recheck(ctx, riot, session, error):
    a, b, c = await _roster(session, "Alpha", "Bravo", "Charlie")
    riot.start_game(live_game(1, [a, "x1"]))
    riot.start_game(live_game(3, [c, "x3"]))
    await refresh_live_games(ctx)
    before = _games(await _state(session))

    # Alpha's game ended (Alpha is re-checked); the limit hits at Bravo, so Charlie is
    # never asked this round.
    riot.end_game(1)
    riot.calls.clear()
    riot.fail_for[b] = error
    report = await refresh_live_games(ctx)

    assert _spectated(riot) == [a, b]
    assert report.checked == 2 and len(report.errors) == 1
    after = _games(await _state(session))
    assert set(after) == {3}  # Alpha's finished game is gone, Charlie's kept as it was
    assert after[3] == before[3]


async def test_rate_limited_round_skips_rank_lookups(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    riot.start_game(live_game(1, [a, "x1"]))
    riot.fail_for[b] = RiotRateLimited(retry_after=3)

    report = await refresh_live_games(ctx)

    assert report.games == 1 and report.rank_lookups == 0
    assert _games(await _state(session))[1]["ranks"] == {}  # looked up next round


async def test_carried_over_games_expire(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    old = (datetime.now(UTC) - live.CARRY_OVER_MAX_AGE - timedelta(minutes=1)).isoformat()
    recent = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    games = [
        {"info": live_game(1, [b]), "ranks": {}, "first_seen_at": old, "seen_at": old},
        {"info": live_game(2, [b]), "ranks": {}, "first_seen_at": old, "seen_at": recent},
    ]
    await app_state_repo.set_state(session, STATE_KEY, {"checked_at": old, "games": games})
    await session.commit()
    # Alpha answers "not in game", then the limit hits before Bravo is asked.
    riot.fail_for[b] = RiotRateLimited(retry_after=3)

    await refresh_live_games(ctx)

    assert set(_games(await _state(session))) == {2}


@pytest.mark.parametrize("error", [RiotForbidden("Forbidden", status=403), RiotKeyMissing()])
async def test_rejected_key_stops_the_round_and_writes_nothing(ctx, riot, session, error):
    await _roster(session, "Alpha", "Bravo")
    riot.fail("active_game_by_puuid", error, times=None)

    report = await refresh_live_games(ctx)

    assert report.checked == 1 and len(report.errors) == 1
    assert await _state(session) is None


async def test_other_errors_skip_only_that_player(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    riot.start_game(live_game(5, [b]))
    riot.fail("active_game_by_puuid", RiotBadResponse("garbage"))

    report = await refresh_live_games(ctx)

    assert _spectated(riot) == [a, b]
    assert report.checked == 2 and report.games == 1 and len(report.errors) == 1


async def test_untracked_and_demo_players_are_not_checked(ctx, riot, session):
    (a,) = await _roster(session, "Alpha")
    session.add_all(
        [
            Summoner(puuid="p-stranger", game_name="Stranger", tag_line="NA1", platform="na1"),
            Summoner(
                puuid="demo-000000000001",
                game_name="Demo",
                tag_line="NA1",
                platform="na1",
                is_tracked=True,
                tracked_since=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        ]
    )
    await session.commit()

    await refresh_live_games(ctx)

    assert _spectated(riot) == [a]


async def test_stored_state_round_trips_through_the_spectator_schema(ctx, riot, session):
    a, b = await _roster(session, "Alpha", "Bravo")
    raw = live_game(11, [a, "x1", b], bots=1)
    riot.start_game(raw)

    await refresh_live_games(ctx)

    (game,) = _games(await _state(session)).values()
    info = CurrentGameInfoDto.model_validate(game["info"])
    assert info == CurrentGameInfoDto.model_validate(raw)
    assert info.game_queue_config_id == 420 and info.banned_champions[0].champion_id == 99
    assert [p.puuid for p in info.participants] == [a, "x1", b, None]
    assert info.participants[0].perks is not None
    assert info.participants[0].perks.perk_style == 8100
    assert game["info"]["observers"] == {"encryptionKey": "abc"}  # extra fields survive


# --- poller hook -----------------------------------------------------------------------------


@pytest.fixture
def fast_ctx(ctx, riot):
    riot.add_account("Alpha", "NA1", puuid="p-alpha")
    ctx.settings = ctx.settings.model_copy(update={"poll_interval_seconds": 0.05})
    return ctx


async def _wait_for(predicate) -> None:
    for _ in range(250):
        if await predicate():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached in time")


async def _run_until(ctx, predicate) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(poller.poll_forever(ctx, stop))
    try:
        await _wait_for(predicate)
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)


async def test_poll_forever_refreshes_live_games_after_each_tick(fast_ctx, riot, session, caplog):
    (a,) = await _roster(session, "Alpha")
    riot.start_game(live_game(1, [a, "x1"]))
    caplog.set_level(logging.INFO, logger="hextrack.ingest.poller")

    async def refreshed() -> bool:
        return await _state(session) is not None

    await _run_until(fast_ctx, refreshed)

    assert set(_games(await _state(session))) == {1}
    assert "live: 1 checked, 1 game, 1 rank lookups" in caplog.text


async def test_live_games_can_be_switched_off(fast_ctx, riot, session):
    await _roster(session, "Alpha")
    fast_ctx.settings = fast_ctx.settings.model_copy(update={"live_games": False})

    async def two_ticks() -> bool:
        return len(riot.calls_to("summoner_by_puuid")) >= 2

    await _run_until(fast_ctx, two_ticks)

    assert riot.calls_to("active_game_by_puuid") == []
    assert await _state(session) is None


async def test_live_refresh_failures_never_stop_polling(fast_ctx, riot, session, monkeypatch):
    await _roster(session, "Alpha")
    calls = 0

    async def exploding(ctx):
        nonlocal calls
        calls += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(poller, "refresh_live_games", exploding)

    async def two_rounds() -> bool:
        return len(riot.calls_to("summoner_by_puuid")) >= 2 and calls >= 2

    await _run_until(fast_ctx, two_rounds)


async def test_stop_cancels_a_stuck_live_refresh(fast_ctx, riot, session, monkeypatch):
    await _roster(session, "Alpha")
    entered = asyncio.Event()

    async def stuck(ctx):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(poller, "refresh_live_games", stuck)

    async def is_stuck() -> bool:
        return entered.is_set()

    await _run_until(fast_ctx, is_stuck)  # returns within the 5 s wait_for
