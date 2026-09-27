"""The champion rollup worker against the test database: exactly-once counting, late
timelines, ineligible games, lazy rune/ban fill from ``raw``, rebuild and prune."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.models import (
    ChampionBan,
    ChampionMatchup,
    ChampionPatchTotal,
    ChampionRollup,
    ChampionStat,
    Match,
    MatchParticipant,
    MatchTimelinePlayer,
)
from hextrack.demo.seed import seed_demo
from hextrack.ingest import poller
from hextrack.ingest.mapping import map_match
from hextrack.stats.champions import KIND_CORE, KIND_RUNE_PAGE, KIND_SKILL_MAX, TIMELINE_KINDS
from hextrack.stats.champions.items import ItemCatalog
from hextrack.stats.champions.worker import (
    ROLLUP_LOCK_KEY,
    RollupRunner,
    champions_status,
    prune,
    rebuild,
    run_rollup_batch,
    run_rollups,
)
from tests.conftest import FIXTURES_DIR
from tests.factories import make_match_json
from tests.test_ingest_support import IngestFakeRiot, make_ctx

START = datetime(2026, 3, 1, 20, tzinfo=UTC)
PRIMARY = [8010, 9111, 9104, 8299]
SECONDARY = [8444, 8451]


class FakeDDragon:
    def __init__(self) -> None:
        self.catalog = ItemCatalog.from_item_json(
            json.loads((FIXTURES_DIR / "item_sample.json").read_text())
        )
        self.patches: list[str] = []

    async def item_catalog(self, patch: str) -> ItemCatalog | None:
        self.patches.append(patch)
        return self.catalog


def full_perks(raw: dict[str, Any]) -> dict[str, Any]:
    for p in raw["info"]["participants"]:
        p["perks"] = {
            "statPerks": {"offense": 5005, "flex": 5008, "defense": 5011},
            "styles": [
                {"style": 8000, "selections": [{"perk": r} for r in PRIMARY]},
                {"style": 8400, "selections": [{"perk": r} for r in SECONDARY]},
            ],
        }
    return raw


async def store(
    session: AsyncSession, raw: dict[str, Any], *, strip_runes: bool = False, **match: Any
) -> str:
    mapped = map_match(raw)
    row = {**mapped.match, **match}
    participants = [dict(p) for p in mapped.participants]
    if strip_runes:
        row["ban_ids"] = None
        for p in participants:
            p.update(primary_style_id=None, rune_ids=None, stat_shards=None)
    await session.execute(insert(Match).values(**row))
    await session.execute(insert(MatchParticipant), participants)
    await session.commit()
    return mapped.match_id


def game(n: int, **kwargs: Any) -> dict[str, Any]:
    return full_perks(make_match_json(f"NA1_{7_000_000 + n}", start=START, **kwargs))


def timeline_rows(match_id: str) -> list[dict[str, Any]]:
    return [
        {
            "match_id": match_id,
            "participant_id": pid,
            "purchases": [1055, 2003, 3071, 3047, 6692, 6333],
            "purchase_s": [2, 3, 600, 700, 900, 1300],
            "skill_order": [1, 2, 3, 1, 1, 4, 1, 1],
        }
        for pid in range(1, 11)
    ]


@pytest.fixture
def dd() -> FakeDDragon:
    return FakeDDragon()


async def batch(
    factory: async_sessionmaker[AsyncSession], dd: FakeDDragon, settings: Settings, **kw: Any
) -> int:
    async with factory() as s:
        n = await run_rollup_batch(s, dd, settings, **kw)
        await s.commit()
    return n


async def snapshot(session: AsyncSession) -> dict[str, Any]:
    async def rows(model: Any, *order: Any) -> list[tuple[Any, ...]]:
        cols = [c for c in model.__table__.columns]
        result = await session.execute(select(*cols).order_by(*order))
        return [tuple(r) for r in result.all()]

    return {
        "stats": await rows(ChampionStat, ChampionStat.champion_id, ChampionStat.position),
        "rollups": await rows(
            ChampionRollup,
            ChampionRollup.champion_id,
            ChampionRollup.position,
            ChampionRollup.kind,
            ChampionRollup.key,
        ),
        "matchups": await rows(
            ChampionMatchup, ChampionMatchup.champion_id, ChampionMatchup.opponent_id
        ),
        "bans": await rows(ChampionBan, ChampionBan.champion_id),
        "totals": await rows(ChampionPatchTotal, ChampionPatchTotal.patch),
    }


async def states(session: AsyncSession) -> dict[str, int]:
    session.expire_all()
    return dict((await session.execute(select(Match.match_id, Match.champ_rollup))).all())


async def test_counts_each_match_exactly_once(session, session_factory, settings, dd) -> None:
    a = await store(session, game(1))
    b = await store(session, game(2, winning_team=200))

    assert await batch(session_factory, dd, settings) == 2
    first = await snapshot(session)
    assert await batch(session_factory, dd, settings) == 0
    assert await snapshot(session) == first
    assert await states(session) == {a: 1, b: 1}

    totals = first["totals"]
    assert totals == [("16.17", 420, 2, 0)]
    stat = await session.get(ChampionStat, (266, "TOP", "16.17", 420))
    assert stat is not None
    assert (stat.champion_key, stat.games, stat.wins, stat.timeline_games) == ("Aatrox", 2, 1, 0)
    assert stat.duration_s == 3600
    # Factory bans: 157, 238, 84, -1, 350 | 67, 555, 11, 145, 360 -> 9 champions, once each.
    assert len(first["bans"]) == 9
    assert all(row[3] == 2 for row in first["bans"])
    matchup = await session.get(ChampionMatchup, (266, "TOP", "16.17", 420, 122))
    assert matchup is not None and matchup.games == 2
    kinds = {row[4] for row in first["rollups"]}
    assert KIND_RUNE_PAGE in kinds
    assert not kinds & TIMELINE_KINDS


async def test_duplicate_bans_count_once(session, session_factory, settings, dd) -> None:
    raw = game(3)
    raw["info"]["teams"][1]["bans"][0]["championId"] = 157  # banned by both teams
    await store(session, raw)
    await batch(session_factory, dd, settings)
    ban = await session.get(ChampionBan, ("16.17", 420, 157))
    assert ban is not None and ban.bans == 1


async def test_timeline_at_first_count_sets_2(session, session_factory, settings, dd) -> None:
    mid = await store(session, game(4), timeline_state="ok")
    await session.execute(insert(MatchTimelinePlayer), timeline_rows(mid))
    await session.commit()

    await batch(session_factory, dd, settings)
    assert (await states(session))[mid] == 2
    stat = await session.get(ChampionStat, (266, "TOP", "16.17", 420))
    assert stat is not None and (stat.games, stat.timeline_games) == (1, 1)
    core = await session.get(
        ChampionRollup, (266, "TOP", "16.17", 420, KIND_CORE, "3071-6692-6333")
    )
    assert core is not None and (core.games, core.extra_sum) == (1, 1300)
    total = await session.get(ChampionPatchTotal, ("16.17", 420))
    assert total is not None and (total.matches, total.timeline_matches) == (1, 1)


async def test_late_timeline_adds_only_timeline_kinds(
    session, session_factory, settings, dd
) -> None:
    mid = await store(session, game(5), timeline_state="pending")
    await batch(session_factory, dd, settings)
    before = await snapshot(session)

    # What the crawler's store_timeline does: rows + 'ok' + 1 -> 3, one transaction.
    await session.execute(insert(MatchTimelinePlayer), timeline_rows(mid))
    await session.execute(
        update(Match).where(Match.match_id == mid).values(timeline_state="ok", champ_rollup=3)
    )
    await session.commit()

    assert await batch(session_factory, dd, settings) == 1
    assert (await states(session))[mid] == 2
    after = await snapshot(session)
    assert after["bans"] == before["bans"]
    assert after["matchups"] == before["matchups"]
    assert after["totals"] == [("16.17", 420, 1, 1)]
    new_rollups = set(after["rollups"]) - set(before["rollups"])
    assert new_rollups and {row[4] for row in new_rollups} <= TIMELINE_KINDS
    assert {row[:6] for row in before["rollups"]} <= {row[:6] for row in after["rollups"]}
    stat = await session.get(ChampionStat, (266, "TOP", "16.17", 420))
    assert stat is not None and (stat.games, stat.timeline_games, stat.timeline_wins) == (1, 1, 1)
    skill = await session.get(ChampionRollup, (266, "TOP", "16.17", 420, KIND_SKILL_MAX, "1-2-3"))
    assert skill is not None and skill.games == 1

    assert await batch(session_factory, dd, settings) == 0
    assert await snapshot(session) == after


async def test_ineligible_games_are_marked(session, session_factory, settings, dd) -> None:
    aram = await store(session, game(6, queue_id=450))
    remake = await store(session, game(7, duration_s=200, remake=True))
    old = await store(
        session,
        full_perks(make_match_json("NA1_7000008", start=datetime(2025, 12, 1, tzinfo=UTC))),
    )
    ok = await store(session, game(9))

    assert await batch(session_factory, dd, settings) == 4
    assert await states(session) == {aram: -1, remake: -1, old: -1, ok: 1}
    total = await session.get(ChampionPatchTotal, ("16.17", 420))
    assert total is not None and total.matches == 1
    assert await session.scalar(select(func.count()).select_from(ChampionPatchTotal)) == 1


async def test_fills_runes_and_bans_from_raw(session, session_factory, settings, dd) -> None:
    mid = await store(session, game(10), strip_runes=True)
    await batch(session_factory, dd, settings)

    session.expire_all()
    rows = (
        await session.execute(
            select(
                MatchParticipant.primary_style_id,
                MatchParticipant.rune_ids,
                MatchParticipant.stat_shards,
            ).where(MatchParticipant.match_id == mid)
        )
    ).all()
    assert len(rows) == 10
    assert all(tuple(r) == (8000, PRIMARY + SECONDARY, [5005, 5008, 5011]) for r in rows)
    bans = await session.scalar(select(Match.ban_ids).where(Match.match_id == mid))
    assert sorted(bans or []) == sorted([157, 238, 84, 350, 67, 555, 11, 145, 360])
    page = await session.get(
        ChampionRollup,
        (266, "TOP", "16.17", 420, KIND_RUNE_PAGE, "8000-8400-8010-9111-9104-8299-8444-8451"),
    )
    assert page is not None and page.games == 1
    assert await session.get(ChampionBan, ("16.17", 420, 157)) is not None


async def test_rebuild_resets_and_recounts(session, session_factory, settings, dd) -> None:
    await store(session, game(11))
    await store(session, game(12, winning_team=200))
    await store(session, game(13, queue_id=450))
    await batch(session_factory, dd, settings)
    counted = await snapshot(session)

    async with session_factory() as s:
        assert await rebuild(s) == 3
        await s.commit()
    assert set((await states(session)).values()) == {0}
    empty = await snapshot(session)
    assert all(not rows for rows in empty.values())

    run = await run_rollups(session_factory, dd, settings, budget_seconds=None, batch_size=2)
    assert (run.matches, run.batches) == (3, 2)
    assert await snapshot(session) == counted


async def test_batch_skips_while_another_holds_the_lock(
    session, session_factory, settings, dd
) -> None:
    await store(session, game(14))
    async with session_factory() as holder:
        await holder.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": ROLLUP_LOCK_KEY})
        assert await batch(session_factory, dd, settings) == 0
        await holder.rollback()
    assert await batch(session_factory, dd, settings) == 1


async def test_missing_item_data_leaves_matches_queued(
    session, session_factory, settings, dd
) -> None:
    mid = await store(session, game(15))

    class Offline:
        async def item_catalog(self, patch: str) -> ItemCatalog | None:
            return None

    assert await batch(session_factory, Offline(), settings) == 0  # type: ignore[arg-type]
    assert (await states(session))[mid] == 0


async def test_prune_drops_small_rows_on_old_patches(session) -> None:
    patches = ["16.8", "16.9", "16.10", "16.11"]
    await session.execute(
        insert(ChampionPatchTotal),
        [{"patch": p, "queue_id": 420, "matches": 10, "timeline_matches": 0} for p in patches],
    )
    base = {"champion_id": 1, "position": "TOP", "queue_id": 420, "kind": "item", "wins": 0}
    await session.execute(
        insert(ChampionRollup),
        [
            {**base, "patch": "16.8", "key": "small", "games": 2},
            {**base, "patch": "16.8", "key": "big", "games": 3},
            {**base, "patch": "16.9", "key": "small", "games": 1},
            {**base, "patch": "16.10", "key": "small", "games": 1},
            {**base, "patch": "16.11", "key": "small", "games": 1},
        ],
    )
    await session.commit()

    assert await prune(session) == 1
    await session.commit()
    left = (await session.execute(select(ChampionRollup.patch, ChampionRollup.key))).all()
    assert sorted(map(tuple, left)) == [
        ("16.10", "small"),
        ("16.11", "small"),
        ("16.8", "big"),
        ("16.9", "small"),
    ]


async def test_runner_counts_and_status_reports(session, session_factory, settings, dd) -> None:
    await store(session, game(16))
    await store(session, game(17, queue_id=450))
    runner = RollupRunner(session_factory, settings, dd)
    run = await runner.run()
    assert run is not None and run.matches == 2

    status = await champions_status(session)
    assert status.by_state == {-1: 1, 1: 1}
    assert [(p.patch, p.queue_id, p.matches) for p in status.patches] == [("16.17", 420, 1)]
    assert status.tables["champion_patch_totals"] == 1
    assert status.tables["champion_stats"] == 10
    await runner.aclose()


async def test_runner_never_raises(session, session_factory, settings) -> None:
    mid = await store(session, game(18))

    class Broken:
        async def item_catalog(self, patch: str) -> ItemCatalog | None:
            raise RuntimeError("boom")

    runner = RollupRunner(session_factory, settings, Broken())  # type: ignore[arg-type]
    assert await runner.run() is None
    assert (await states(session))[mid] == 0


async def test_poll_forever_counts_rollups_after_each_tick(
    session, session_factory, settings, dd, monkeypatch
) -> None:
    mid = await store(session, game(19))
    monkeypatch.setattr(
        poller,
        "RollupRunner",
        lambda factory, cfg: RollupRunner(factory, cfg, dd),
    )
    fast = settings.model_copy(update={"poll_interval_seconds": 0.05, "live_games": False})
    ctx = make_ctx(fast, session_factory, IngestFakeRiot(fast))
    stop = asyncio.Event()
    task = asyncio.create_task(poller.poll_forever(ctx, stop, rollups=True))
    try:
        for _ in range(250):
            if (await states(session))[mid] == 1:
                break
            await asyncio.sleep(0.02)
        assert (await states(session))[mid] == 1
    finally:
        stop.set()
        await asyncio.wait_for(task, 5)


async def test_demo_games_flow_through_with_timelines(
    session, session_factory, settings, dd
) -> None:
    report = await seed_demo(
        settings, reset=False, matches=30, now=datetime(2026, 9, 1, 12, tzinfo=UTC)
    )
    run = await run_rollups(session_factory, dd, settings, budget_seconds=None)
    assert run.matches == report.matches
    counted = await states(session)
    assert set(counted.values()) <= {2, -1}
    assert 2 in counted.values()
    kinds = set((await session.scalars(select(ChampionRollup.kind).distinct())).all())
    assert {KIND_CORE, KIND_SKILL_MAX} <= kinds
