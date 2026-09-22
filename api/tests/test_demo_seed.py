"""Demo dataset: realism/consistency of the generated games and the DB seeding."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.config import Settings
from hextrack.db.models import BotEvent, Match, MatchParticipant, RankSnapshot, Summoner
from hextrack.demo import seed as seed_module
from hextrack.demo.matchgen import (
    CHAMPIONS,
    CHAMPIONS_BY_ID,
    FARSIGHT,
    FLASH,
    ITEM_COST,
    MAX_GAME_SECONDS,
    MIN_GAME_SECONDS,
    ORACLE_LENS,
    REMAKE_RESULT,
    SMITE,
    SPELLS_BY_ROLE,
    STEALTH_WARD,
    game_version_for,
)
from hextrack.demo.names import (
    DEMO_PUUID_PREFIX,
    PROFILE_ICONS,
    PUUID_LENGTH,
    ROSTER,
    validate_roster,
)
from hextrack.demo.seed import DemoDataset, build_dataset, seed_demo, standing_for_value
from hextrack.ingest.context import IngestContext
from hextrack.ingest.mapping import is_scorable, map_match
from hextrack.ingest.service import ingest_match_json
from hextrack.rank import APEX_TIERS, TIER_ORDER, rank_value
from hextrack.riotid import parse_riot_id, riot_id_key
from tests.factories import make_match_json, spec
from tests.fakes import FakeRiotClient

NOW = datetime(2026, 9, 21, 22, 0, tzinfo=UTC)
TRACKED_NAMES = {
    "Hexwalker#NA1",
    "Baron Stealer#GG",
    "Ward Bot 9000#SUP",
    "Jungle Diff#JGL",
    "Mid Or Feed#MID",
    "Kite Theory#ADC",
    "Top Island#TOP",
    "Dragon Soul#EZ",
}


@pytest.fixture(scope="module")
def dataset() -> DemoDataset:
    return build_dataset(now=NOW)


def _participants(raw: Mapping[str, Any]) -> list[dict[str, Any]]:
    return list(raw["info"]["participants"])


def _is_remake(raw: Mapping[str, Any]) -> bool:
    return raw["info"]["endOfGameResult"] != "GameComplete"


# --- determinism -----------------------------------------------------------------------------


def test_dataset_is_deterministic(dataset: DemoDataset) -> None:
    again = build_dataset(now=NOW)
    assert again.matches == dataset.matches
    assert again.snapshots == dataset.snapshots
    assert again.summoners == dataset.summoners


def test_other_seed_gives_other_games(dataset: DemoDataset) -> None:
    other = build_dataset(now=NOW, seed=8)
    assert len(other.matches) == len(dataset.matches)
    assert other.matches != dataset.matches
    # Same roster (stable puuids), different strangers.
    assert {s.puuid for s in other.tracked} == {s.puuid for s in dataset.tracked}


def test_player_and_match_counts_are_configurable() -> None:
    small = build_dataset(now=NOW, players=3, matches=30, seed=1)
    assert len(small.matches) == 30
    assert [f"{s.game_name}#{s.tag_line}" for s in small.tracked] == [p.riot_id for p in ROSTER[:3]]
    big = build_dataset(now=NOW, players=10, matches=40, seed=1)
    assert len(big.tracked) == 10
    keys = [riot_id_key(s.game_name, s.tag_line) for s in big.summoners]
    assert len(keys) == len(set(keys))
    with pytest.raises(ValueError):
        build_dataset(now=NOW, players=0)
    with pytest.raises(ValueError):
        build_dataset(now=NOW, matches=0)


# --- people ----------------------------------------------------------------------------------


def test_roster_and_opponents(dataset: DemoDataset) -> None:
    validate_roster()
    tracked = {f"{s.game_name}#{s.tag_line}" for s in dataset.tracked}
    assert tracked == TRACKED_NAMES
    opponents = [s for s in dataset.summoners if not s.is_tracked]
    assert 250 <= len(opponents) <= 320
    keys = [riot_id_key(s.game_name, s.tag_line) for s in dataset.summoners]
    assert len(keys) == len(set(keys)), "Riot IDs must be unique case-insensitively"
    for s in dataset.summoners:
        assert s.puuid.startswith(DEMO_PUUID_PREFIX)
        assert len(s.puuid) == PUUID_LENGTH
        rid = parse_riot_id(f"{s.game_name}#{s.tag_line}")
        assert (rid.game_name, rid.tag_line) == (s.game_name, s.tag_line)
        assert 3 <= len(s.game_name) <= 16
        assert s.profile_icon_id in PROFILE_ICONS
        assert s.summoner_level >= 30
    names = [s.game_name for s in opponents]
    assert sum(" " in n for n in names) >= 20, "some names contain spaces"
    assert 1 <= sum(not n.isascii() for n in names) <= 3, "one or two unicode names"
    for s in dataset.tracked:
        assert s.tracked_since is not None and s.tracked_since < NOW - timedelta(days=100)
        assert s.last_refreshed_at is not None and s.last_refreshed_at <= NOW


# --- games -----------------------------------------------------------------------------------


def test_every_generated_match_maps(dataset: DemoDataset) -> None:
    ids = []
    for raw in dataset.matches:
        mapped = map_match(raw)
        ids.append(mapped.match_id)
        assert mapped.match_id.startswith("DEMO_")
        assert len(mapped.participants) == 10
        assert len({p["champion_id"] for p in mapped.participants}) == 10
        assert {p["team_position"] for p in mapped.participants} == {
            "TOP",
            "JUNGLE",
            "MIDDLE",
            "BOTTOM",
            "UTILITY",
        }
        for p in mapped.participants:
            assert len(p["items"]) == 7
            assert p["primary_rune_id"] is not None and p["secondary_style_id"] is not None
            assert p["riot_id_game_name"] and p["riot_id_tagline"]
        assert is_scorable(mapped.match) is not _is_remake(raw)
    assert ids == [f"DEMO_{n}" for n in range(1, len(dataset.matches) + 1)]


def test_queues_durations_and_time_spread(dataset: DemoDataset) -> None:
    queues = Counter(raw["info"]["queueId"] for raw in dataset.matches)
    assert set(queues) == {420, 440}
    assert queues[420] > 0.6 * len(dataset.matches)
    assert queues[440] >= 10
    starts = []
    for raw in dataset.matches:
        info = raw["info"]
        start = datetime.fromtimestamp(info["gameStartTimestamp"] / 1000, tz=UTC)
        starts.append(start)
        assert NOW - timedelta(days=101) <= start < NOW
        end = datetime.fromtimestamp(info["gameEndTimestamp"] / 1000, tz=UTC)
        assert end <= NOW
        assert info["gameCreation"] < info["gameStartTimestamp"] < info["gameEndTimestamp"]
        # (the payload start carries a few random milliseconds past the planned start)
        assert info["gameVersion"] in {
            game_version_for(start),
            game_version_for(start - timedelta(seconds=1)),
        }
        if not _is_remake(raw):
            assert MIN_GAME_SECONDS <= info["gameDuration"] <= MAX_GAME_SECONDS
    assert starts == sorted(starts)
    assert max(starts) - min(starts) > timedelta(days=80)
    patches = {raw["info"]["gameVersion"].rsplit(".", 2)[0] for raw in dataset.matches}
    assert len(patches) >= 5


def test_remakes(dataset: DemoDataset) -> None:
    remakes = [raw for raw in dataset.matches if _is_remake(raw)]
    assert 1 <= len(remakes) <= 5
    for raw in remakes:
        info = raw["info"]
        assert info["endOfGameResult"] == REMAKE_RESULT
        assert 180 <= info["gameDuration"] <= 300
        assert all(p["gameEndedInEarlySurrender"] for p in info["participants"])
        mapped = map_match(raw)
        assert mapped.match["remake"] is True
        assert not is_scorable(mapped.match)


def test_stats_are_internally_consistent(dataset: DemoDataset) -> None:
    for raw in dataset.matches:
        info = raw["info"]
        teams = {t["teamId"]: t for t in info["teams"]}
        parts = _participants(raw)
        by_team = defaultdict(list)
        for p in parts:
            by_team[p["teamId"]].append(p)
        assert sum(t["win"] for t in teams.values()) == 1
        for team_id, members in by_team.items():
            team = teams[team_id]
            enemy = 300 - team_id
            kills = sum(p["kills"] for p in members)
            objectives = team["objectives"]
            assert objectives["champion"]["kills"] == kills
            assert sum(p["deaths"] for p in members) == sum(p["kills"] for p in by_team[enemy])
            assert sum(p["dragonKills"] for p in members) == objectives["dragon"]["kills"]
            assert sum(p["baronKills"] for p in members) == objectives["baron"]["kills"]
            assert sum(p["turretKills"] for p in members) <= objectives["tower"]["kills"]
            assert sum(p["inhibitorKills"] for p in members) <= objectives["inhibitor"]["kills"]
            assert objectives["tower"]["kills"] <= 11
            assert len(team["bans"]) == 5
            for p in members:
                assert p["win"] is team["win"]
                if kills:
                    assert (p["kills"] + p["assists"]) / kills <= 1.0
                assert p["goldSpent"] <= p["goldEarned"]
                assert p["turretTakedowns"] >= p["turretKills"]
                assert p["inhibitorTakedowns"] >= p["inhibitorKills"]
                assert (
                    p["physicalDamageDealtToChampions"]
                    + p["magicDamageDealtToChampions"]
                    + p["trueDamageDealtToChampions"]
                    == p["totalDamageDealtToChampions"]
                )
                assert p["totalDamageDealt"] >= p["totalDamageDealtToChampions"]
                assert p["damageDealtToObjectives"] >= p["damageDealtToBuildings"]
                assert p["damageDealtToBuildings"] >= p["damageDealtToTurrets"]
                assert p["largestMultiKill"] <= 5
                assert p["largestMultiKill"] <= p["kills"]
                if p["pentaKills"]:
                    assert p["quadraKills"] and p["tripleKills"] and p["doubleKills"]
                if p["quadraKills"]:
                    assert p["tripleKills"] and p["doubleKills"]
                assert p["totalTimeSpentDead"] < info["gameDuration"]
                assert p["timePlayed"] == info["gameDuration"]
                assert 1 <= p["champLevel"] <= 18
                assert p["visionWardsBoughtInGame"] >= p["detectorWardsPlaced"]
                assert p["challenges"]["takedowns"] == p["kills"] + p["assists"]
        banned = [b["championId"] for t in info["teams"] for b in t["bans"] if b["championId"] > 0]
        picked = {p["championId"] for p in parts}
        assert not picked & set(banned)
        assert len(banned) == len(set(banned))
        fb = [p for p in parts if p["firstBloodKill"]]
        assert len(fb) == (1 if any(p["kills"] for p in parts) else 0)
        if fb:
            assert teams[fb[0]["teamId"]]["objectives"]["champion"]["first"] is True


def test_champions_items_and_spells(dataset: DemoDataset) -> None:
    assert len(CHAMPIONS) >= 60
    assert CHAMPIONS_BY_ID[62].key == "MonkeyKing"
    assert CHAMPIONS_BY_ID[157].key == "Yasuo"
    assert CHAMPIONS_BY_ID[222].key == "Jinx"
    assert CHAMPIONS_BY_ID[412].key == "Thresh"
    known_items = set(ITEM_COST) | {STEALTH_WARD, ORACLE_LENS, FARSIGHT, 0}
    used_champions: set[int] = set()
    for raw in dataset.matches:
        for p in _participants(raw):
            champ = CHAMPIONS_BY_ID[p["championId"]]
            used_champions.add(champ.id)
            assert p["championName"] == champ.key
            role = p["teamPosition"]
            assert role in champ.roles
            items = [p[f"item{i}"] for i in range(7)]
            assert set(items) <= known_items
            assert items[6] in (STEALTH_WARD, ORACLE_LENS, FARSIGHT)
            spells = {p["summoner1Id"], p["summoner2Id"]}
            allowed = {s for pair, _ in SPELLS_BY_ROLE[role] for s in pair}
            assert spells <= allowed
            if role == "JUNGLE":
                assert SMITE in spells
            elif FLASH not in spells:
                assert 6 in spells  # Ghost instead of Flash
    assert len(used_champions) >= 60


def test_stats_follow_roles_and_results(dataset: DemoDataset) -> None:
    per_role: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    win_gpm: list[float] = []
    loss_gpm: list[float] = []
    for raw in dataset.matches:
        if _is_remake(raw):
            continue
        minutes = raw["info"]["gameDuration"] / 60
        for p in _participants(raw):
            stats = per_role[p["teamPosition"]]
            stats["cs"].append(p["totalMinionsKilled"] / minutes)
            stats["neutral"].append(p["neutralMinionsKilled"] / minutes)
            stats["vision"].append(p["visionScore"] / minutes)
            stats["damage"].append(p["totalDamageDealtToChampions"] / minutes)
            stats["gold"].append(p["goldEarned"] / minutes)
            (win_gpm if p["win"] else loss_gpm).append(p["goldEarned"] / minutes)

    def mean(role: str, key: str) -> float:
        values = per_role[role][key]
        return sum(values) / len(values)

    assert mean("UTILITY", "cs") < 2.5 < mean("TOP", "cs")
    assert mean("UTILITY", "vision") > 1.8 * mean("MIDDLE", "vision")
    assert mean("JUNGLE", "neutral") > 4.0 > mean("BOTTOM", "neutral")
    assert mean("BOTTOM", "damage") > mean("UTILITY", "damage")
    assert mean("MIDDLE", "gold") > mean("UTILITY", "gold")
    assert sum(win_gpm) / len(win_gpm) > 1.05 * sum(loss_gpm) / len(loss_gpm)
    multikills: Counter[str] = Counter()
    for raw in dataset.matches:
        for p in _participants(raw):
            multikills["penta"] += p["pentaKills"]
            multikills["quadra"] += p["quadraKills"]
            multikills["triple"] += p["tripleKills"]
    assert multikills["triple"] > multikills["quadra"] >= multikills["penta"]
    assert multikills["penta"] <= 6


def test_friends_queue_together(dataset: DemoDataset) -> None:
    tracked = {s.puuid for s in dataset.tracked}
    same_team: Counter[frozenset[str]] = Counter()
    stacks: Counter[int] = Counter()
    for raw in dataset.matches:
        per_team = Counter(p["teamId"] for p in _participants(raw) if p["puuid"] in tracked)
        assert per_team, "every demo game has at least one tracked player"
        biggest = max(per_team.values())
        stacks[biggest] += 1
        if raw["info"]["queueId"] == 420:
            assert biggest <= 2, "solo/duo allows at most a duo"
        pairs = [p["puuid"] for p in _participants(raw) if p["puuid"] in tracked]
        for a in pairs:
            for b in pairs:
                if a < b:
                    same_team[frozenset((a, b))] += 1
    assert stacks[2] >= 40
    assert stacks[3] + stacks[5] >= 5
    assert max(same_team.values()) >= 15, "a regular duo exists (best ally is meaningful)"


def test_rank_journeys_follow_results(dataset: DemoDataset) -> None:
    tracked = {s.puuid: s for s in dataset.tracked}
    results: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for raw in dataset.matches:
        if _is_remake(raw):
            continue
        queue = "RANKED_FLEX_SR" if raw["info"]["queueId"] == 440 else "RANKED_SOLO_5x5"
        for p in _participants(raw):
            if p["puuid"] in tracked:
                results[(p["puuid"], queue)]["wins" if p["win"] else "losses"] += 1

    series: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for snap in dataset.snapshots:
        assert snap.rank_value == rank_value(snap.tier, snap.rank, snap.lp)
        assert (snap.rank is None) == (snap.tier in APEX_TIERS)
        assert snap.taken_at <= NOW
        if snap.puuid in tracked:
            series[(snap.puuid, snap.queue_type)].append(snap)

    promotions = demotions = 0
    final_tiers = set()
    for key, snaps in series.items():
        snaps.sort(key=lambda s: s.taken_at)
        first, last = snaps[0], snaps[-1]
        assert not first.is_heartbeat
        assert last.wins - first.wins == results[key]["wins"]
        assert last.losses - first.losses == results[key]["losses"]
        assert NOW - last.taken_at < timedelta(hours=41)
        for a, b in zip(snaps, snaps[1:], strict=False):
            assert b.taken_at - a.taken_at < timedelta(hours=41), "heartbeat every day or two"
            assert b.wins + b.losses >= a.wins + a.losses
            if b.is_heartbeat:
                assert (b.tier, b.rank, b.lp, b.wins, b.losses) == (
                    a.tier,
                    a.rank,
                    a.lp,
                    a.wins,
                    a.losses,
                )
            if b.rank_value > a.rank_value and (b.tier, b.rank) != (a.tier, a.rank):
                promotions += 1
            if b.rank_value < a.rank_value and (b.tier, b.rank) != (a.tier, a.rank):
                demotions += 1
        if key[1] == "RANKED_SOLO_5x5":
            final_tiers.add(last.tier)
    assert promotions >= 5 and demotions >= 1
    assert final_tiers <= set(
        TIER_ORDER[TIER_ORDER.index("SILVER") : TIER_ORDER.index("MASTER") + 1]
    )
    assert len(final_tiers) >= 4, "the leaderboard has spread"
    # Opponents get one current snapshot each.
    opponents = {s.puuid for s in dataset.summoners if not s.is_tracked}
    per_opponent = Counter(s.puuid for s in dataset.snapshots if s.puuid in opponents)
    assert set(per_opponent) == opponents and set(per_opponent.values()) == {1}


def test_standing_for_value_round_trips() -> None:
    for value in (0, 99, 400, 1234, 2799, 2800, 3050):
        tier, rank, lp = standing_for_value(value)
        assert rank_value(tier, rank, lp) == value


# --- database --------------------------------------------------------------------------------


async def _count(factory: async_sessionmaker[AsyncSession], stmt: Any) -> int:
    async with factory() as session:
        return int((await session.scalar(stmt)) or 0)


async def _demo_counts(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    return {
        "matches": await _count(
            factory,
            select(func.count())
            .select_from(Match)
            .where(Match.match_id.startswith("DEMO_", autoescape=True)),
        ),
        "participants": await _count(
            factory,
            select(func.count())
            .select_from(MatchParticipant)
            .where(MatchParticipant.match_id.startswith("DEMO_", autoescape=True)),
        ),
        "summoners": await _count(
            factory,
            select(func.count())
            .select_from(Summoner)
            .where(Summoner.puuid.startswith("demo-", autoescape=True)),
        ),
        "tracked": await _count(
            factory,
            select(func.count())
            .select_from(Summoner)
            .where(Summoner.puuid.startswith("demo-", autoescape=True), Summoner.is_tracked),
        ),
        "snapshots": await _count(
            factory,
            select(func.count())
            .select_from(RankSnapshot)
            .where(RankSnapshot.puuid.startswith("demo-", autoescape=True)),
        ),
    }


async def test_seed_demo_counts(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    report = await seed_demo(settings, reset=False, now=NOW)
    expected = build_dataset(now=NOW)
    assert report.players == 8
    assert report.matches == 220
    assert report.participants == 2200
    assert report.rank_snapshots == len(expected.snapshots)
    assert report.opponents == len(expected.summoners) - 8
    assert report.scored_matches == 0  # no model in the test model_dir
    counts = await _demo_counts(session_factory)
    assert counts == {
        "matches": 220,
        "participants": 2200,
        "summoners": len(expected.summoners),
        "tracked": 8,
        "snapshots": len(expected.snapshots),
    }
    async with session_factory() as session:
        stored = await session.get(Match, "DEMO_1")
        assert stored is not None and stored.raw == expected.matches[0]
        hex_walker = (
            await session.scalars(select(Summoner).where(Summoner.game_name == "Hexwalker"))
        ).one()
        assert hex_walker.is_tracked and hex_walker.last_seen is not None
        newest = await session.scalar(
            select(func.max(MatchParticipant.game_start)).where(
                MatchParticipant.puuid == hex_walker.puuid
            )
        )
        assert hex_walker.last_seen == newest
        # Everything went through the real ingest path without events.
        assert await session.scalar(select(func.count()).select_from(BotEvent)) == 0


async def test_seed_demo_rerun_without_reset_is_idempotent(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    first = await seed_demo(settings, reset=False, matches=40, now=NOW)
    before = await _demo_counts(session_factory)
    second = await seed_demo(settings, reset=False, matches=40, now=NOW + timedelta(hours=3))
    assert first.matches == 40 and second.matches == 0
    assert second.participants == 0 and second.rank_snapshots == 0
    assert await _demo_counts(session_factory) == before


async def test_reset_removes_only_demo_data(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    fake_riot: FakeRiotClient,
) -> None:
    # Real data next to the demo data.
    ctx = IngestContext(
        settings=settings,
        session_factory=session_factory,
        riot=fake_riot,  # type: ignore[arg-type]
    )
    async with session_factory() as session:
        session.add(
            Summoner(
                puuid="real-puuid-1",
                game_name="Real Player",
                tag_line="NA1",
                platform="na1",
                is_tracked=True,
            )
        )
        await session.flush()
        session.add(
            RankSnapshot(
                puuid="real-puuid-1",
                queue_type="RANKED_SOLO_5x5",
                tier="GOLD",
                rank="II",
                lp=40,
                wins=10,
                losses=9,
                rank_value=rank_value("GOLD", "II", 40),
                taken_at=NOW - timedelta(days=1),
            )
        )
        raw = make_match_json("NA1_4242", [spec("real-puuid-1", "Real Player", "NA1")])
        await ingest_match_json(ctx, session, raw, enqueue_events=False)
        session.add(BotEvent(kind="new_match", payload={"puuid": "real-puuid-1"}))
        session.add(BotEvent(kind="new_match", payload={"puuid": "demo-stale", "match_id": "x"}))
        session.add(BotEvent(kind="great_game", payload={"match_id": "DEMO_3", "puuid": "p"}))
        await session.commit()

    first = await seed_demo(settings, reset=False, matches=30, now=NOW)
    assert first.matches == 30
    again = await seed_demo(settings, reset=True, matches=30, now=NOW)
    assert again.reset and again.deleted_matches == 30
    assert again.matches == 30 and again.participants == 300
    assert again.rank_snapshots == first.rank_snapshots

    # A reset with another seed leaves exactly the new dataset behind.
    other = await seed_demo(settings, reset=True, matches=25, seed=8, now=NOW)
    expected = build_dataset(matches=25, seed=8, now=NOW)
    counts = await _demo_counts(session_factory)
    assert other.matches == 25
    assert counts["matches"] == 25 and counts["participants"] == 250
    assert counts["summoners"] == len(expected.summoners)
    assert counts["snapshots"] == len(expected.snapshots)

    async with session_factory() as session:
        real = await session.get(Summoner, "real-puuid-1")
        assert real is not None and real.is_tracked
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RankSnapshot)
                .where(RankSnapshot.puuid == "real-puuid-1")
            )
            == 1
        )
        match = await session.get(Match, "NA1_4242")
        assert match is not None
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MatchParticipant)
                .where(MatchParticipant.match_id == "NA1_4242")
            )
            == 10
        )
        events = (await session.scalars(select(BotEvent))).all()
        assert [e.payload for e in events] == [{"puuid": "real-puuid-1"}]


async def test_clear_demo_removes_demo_data_and_keeps_real(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    fake_riot: FakeRiotClient,
) -> None:
    ctx = IngestContext(
        settings=settings,
        session_factory=session_factory,
        riot=fake_riot,  # type: ignore[arg-type]
    )
    async with session_factory() as session:
        raw = make_match_json("NA1_4343", [spec("real-puuid-2", "Real Two", "NA1")])
        await ingest_match_json(ctx, session, raw, enqueue_events=False)
        await session.commit()
    await seed_demo(settings, reset=False, matches=20, now=NOW)

    assert await seed_module.clear_demo(settings) == 20

    counts = await _demo_counts(session_factory)
    assert counts["matches"] == 0 and counts["summoners"] == 0 and counts["snapshots"] == 0
    async with session_factory() as session:
        assert await session.get(Match, "NA1_4343") is not None


class _ConstantScorer:
    """Stand-in for a loaded model: winners 0.75, losers 0.25."""

    version = "test-constant"
    feature_names: Sequence[str] = ()

    def score_match(
        self, game_duration_seconds: int, participants: Sequence[Mapping[str, Any]]
    ) -> dict[str, float]:
        return {p["puuid"]: 0.75 if p["win"] else 0.25 for p in participants}


async def test_seed_scores_matches_when_a_model_is_loaded(
    clean_db: None,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(seed_module, "_load_scorer", lambda _model_dir: _ConstantScorer())
    report = await seed_demo(settings, reset=True, matches=60, now=NOW)
    dataset = build_dataset(matches=60, now=NOW)
    remakes = {raw["metadata"]["matchId"] for raw in dataset.matches if _is_remake(raw)}
    assert report.scored_matches == 60 - len(remakes)
    async with session_factory() as session:
        rows = (
            await session.execute(
                select(MatchParticipant.match_id, MatchParticipant.ai_score, MatchParticipant.win)
            )
        ).all()
    for match_id, score, win in rows:
        if match_id in remakes:
            assert score is None
        else:
            assert score == (0.75 if win else 0.25)


def test_reserved_riot_ids_are_never_used() -> None:
    reserved = {riot_id_key("Hexwalker", "NA1"), riot_id_key("Señor Gank", "MX1")}
    dataset = build_dataset(now=NOW, reserved=reserved)
    keys = {riot_id_key(s.game_name, s.tag_line) for s in dataset.summoners}
    assert not keys & reserved
    names = {f"{s.game_name}#{s.tag_line}" for s in dataset.tracked}
    assert names == (TRACKED_NAMES - {"Hexwalker#NA1"}) | {"Hexwalker#DEMO"}
    for raw in dataset.matches:
        for p in _participants(raw):
            assert riot_id_key(p["riotIdGameName"], p["riotIdTagline"]) not in reserved


async def test_seed_never_impersonates_a_stored_account(
    clean_db: None, settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory() as session:
        session.add(
            Summoner(puuid="real-hex", game_name="hexwalker", tag_line="na1", platform="na1")
        )
        await session.commit()
    report = await seed_demo(settings, reset=True, matches=30, now=NOW)
    assert report.players == 8
    async with session_factory() as session:
        real = await session.get(Summoner, "real-hex")
        assert real is not None and not real.is_tracked
        assert (real.game_name, real.tag_line) == ("hexwalker", "na1")
        demo = (
            await session.scalars(
                select(Summoner).where(
                    Summoner.game_name == "Hexwalker", Summoner.puuid != "real-hex"
                )
            )
        ).one()
        assert demo.tag_line == "DEMO" and demo.is_tracked
        assert demo.puuid.startswith("demo-")
        assert (
            await session.scalar(
                select(func.count())
                .select_from(RankSnapshot)
                .where(RankSnapshot.puuid == demo.puuid)
            )
            or 0
        ) > 10


def _game_facts(ds: DemoDataset) -> list[tuple[Any, ...]]:
    return [
        (
            raw["metadata"]["matchId"],
            raw["info"]["queueId"],
            raw["info"]["gameDuration"],
            tuple(
                (p["puuid"], p["championId"], p["kills"], p["deaths"], p["assists"], p["win"])
                for p in _participants(raw)
            ),
        )
        for raw in ds.matches
    ]


def test_games_do_not_depend_on_the_time_of_day(dataset: DemoDataset) -> None:
    # NOW is 22:00 UTC; 03:17 the next morning is still before the 05:00 UTC anchor.
    same_evening = build_dataset(now=NOW + timedelta(hours=5, minutes=17))
    assert _game_facts(same_evening) == _game_facts(dataset)
    assert (
        same_evening.matches[0]["info"]["gameStartTimestamp"]
        == (dataset.matches[0]["info"]["gameStartTimestamp"])
    )
    days_later = build_dataset(now=NOW + timedelta(days=3, hours=2))
    assert _game_facts(days_later) == _game_facts(dataset)
    shift = (
        days_later.matches[-1]["info"]["gameStartTimestamp"]
        - dataset.matches[-1]["info"]["gameStartTimestamp"]
    )
    assert shift == 3 * 86_400_000
