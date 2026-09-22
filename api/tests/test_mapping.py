import copy
from datetime import UTC, datetime

import pytest

from hextrack.db.models import Match, MatchParticipant
from hextrack.ingest.mapping import (
    InvalidMatchPayload,
    is_scorable,
    map_match,
    patch_from_version,
    pings_total,
)
from tests.factories import make_match_json, spec


def test_sample_maps_completely(match_sample):
    mapped = map_match(match_sample)
    m = mapped.match
    assert mapped.match_id == "NA1_5391847262"
    assert m["queue_id"] == 420
    assert m["game_mode"] == "CLASSIC"
    assert m["patch"] == "16.17"
    assert m["game_duration"] == 1837
    assert m["game_start"] == datetime(2026, 9, 12, 20, 30, 45, 123000, tzinfo=UTC)
    assert m["game_start"].tzinfo is not None
    assert m["end_of_game_result"] == "GameComplete"
    assert m["remake"] is False
    assert m["platform_id"] == "NA1"
    assert m["raw"] == match_sample
    assert len(mapped.participants) == 10
    assert [p["participant_id"] for p in mapped.participants] == list(range(1, 11))

    ahri = mapped.participants[2]
    assert ahri["riot_id_game_name"] == "mid or feed"
    assert ahri["riot_id_tagline"] == "4200"
    assert ahri["champion_name"] == "Ahri" and ahri["champion_id"] == 103
    assert ahri["team_position"] == "MIDDLE"
    assert ahri["team_id"] == 100 and ahri["win"] is True
    assert (ahri["kills"], ahri["deaths"], ahri["assists"]) == (11, 2, 8)
    assert ahri["items"] == [3152, 3020, 4645, 3089, 3135, 1082, 3340]
    assert ahri["vision_wards_bought"] == 3
    assert ahri["game_start"] == m["game_start"]
    assert ahri["queue_id"] == 420
    assert ahri["match_id"] == "NA1_5391847262"
    assert ahri["first_blood_kill"] is True
    assert ahri["primary_rune_id"] == 8112 and ahri["secondary_style_id"] == 8300
    # hold 0 + getBack 0 + onMyWay 2 + needVision 1 + enemyMissing 8 + enemyVision 0
    assert ahri["pings_total"] == 11
    assert "ai_score" not in ahri


def test_mapped_columns_exist_on_tables(match_sample):
    mapped = map_match(match_sample)
    match_cols = set(Match.__table__.columns.keys())
    part_cols = set(MatchParticipant.__table__.columns.keys())
    assert set(mapped.match) <= match_cols
    for row in mapped.participants:
        assert set(row) <= part_cols
    # every NOT NULL participant column without a default is produced by the mapper
    required = {
        c.name
        for c in MatchParticipant.__table__.columns
        if not c.nullable and c.default is None and c.server_default is None
    }
    assert required <= set(mapped.participants[0])


def test_pings_count_each_field_once():
    p = {
        "holdPings": 1,
        "getBackPings": 2,
        "onMyWayPings": 3,
        "needVisionPings": 4,
        "enemyMissingPings": 5,
        "enemyVisionPings": 6,
        "commandPings": 100,
    }
    assert pings_total(p) == 21
    assert pings_total({}) == 0
    assert pings_total({"holdPings": None, "getBackPings": 2}) == 2


def test_riot_id_fallback_to_summoner_name(match_sample):
    raw = copy.deepcopy(match_sample)
    p = raw["info"]["participants"][0]
    del p["riotIdGameName"]
    del p["riotIdTagline"]
    p["summonerName"] = "Old Name"
    row = map_match(raw).participants[0]
    assert row["riot_id_game_name"] == "Old Name"
    assert row["riot_id_tagline"] is None


def test_missing_stats_default_to_zero(match_sample):
    raw = copy.deepcopy(match_sample)
    p = raw["info"]["participants"][0]
    for key in ("visionWardsBoughtInGame", "holdPings", "item3", "perks", "teamPosition"):
        p.pop(key)
    row = map_match(raw).participants[0]
    assert row["vision_wards_bought"] == 0
    assert row["items"][3] == 0 and len(row["items"]) == 7
    assert row["primary_rune_id"] is None
    assert row["team_position"] == "UNKNOWN"


@pytest.mark.parametrize(
    "payload",
    [
        {"status": {"message": "Rate limit exceeded", "status_code": 429}},
        {"status": {"message": "Data not found - match file not found", "status_code": 404}},
        {},
        {"metadata": {"matchId": "NA1_1"}},
        {"metadata": {}, "info": {}},
        [],
        "not a match",
    ],
)
def test_rejects_error_bodies_and_garbage(payload):
    with pytest.raises(InvalidMatchPayload):
        map_match(payload)


def test_rejects_missing_required_fields(match_sample):
    for path in (
        ("metadata", "matchId"),
        ("info", "gameVersion"),
        ("info", "gameStartTimestamp"),
        ("info", "participants"),
        ("info", "queueId"),
    ):
        raw = copy.deepcopy(match_sample)
        del raw[path[0]][path[1]]
        with pytest.raises(InvalidMatchPayload):
            map_match(raw)
    for key in ("puuid", "teamId", "championId", "win", "kills"):
        raw = copy.deepcopy(match_sample)
        del raw["info"]["participants"][4][key]
        with pytest.raises(InvalidMatchPayload, match=key):
            map_match(raw)


def test_classic_requires_ten_participants(match_sample):
    raw = copy.deepcopy(match_sample)
    raw["info"]["participants"] = raw["info"]["participants"][:9]
    with pytest.raises(InvalidMatchPayload, match="10 participants"):
        map_match(raw)


def test_other_modes_allow_other_sizes():
    raw = make_match_json("NA1_77", game_mode="CHERRY", queue_id=1700)
    raw["info"]["participants"] = raw["info"]["participants"][:8]
    mapped = map_match(raw)
    assert len(mapped.participants) == 8
    assert not is_scorable(mapped.match)


def test_duplicate_puuids_rejected(match_sample):
    raw = copy.deepcopy(match_sample)
    raw["info"]["participants"][1]["puuid"] = raw["info"]["participants"][0]["puuid"]
    with pytest.raises(InvalidMatchPayload, match="duplicate"):
        map_match(raw)


def test_wrong_types_rejected(match_sample):
    raw = copy.deepcopy(match_sample)
    raw["info"]["participants"][0]["kills"] = "seven"
    with pytest.raises(InvalidMatchPayload):
        map_match(raw)


def test_patch_from_version():
    assert patch_from_version("16.17.712.5021") == "16.17"
    assert patch_from_version("9.3.1") == "9.3"
    with pytest.raises(InvalidMatchPayload):
        patch_from_version("garbage")


def test_legacy_millisecond_duration():
    raw = make_match_json("NA1_5", duration_s=1800)
    del raw["info"]["gameEndTimestamp"]
    raw["info"]["gameDuration"] = 1_800_000
    assert map_match(raw).match["game_duration"] == 1800


def test_is_scorable_rules():
    base = {"game_mode": "CLASSIC", "end_of_game_result": "GameComplete", "game_duration": 1800}
    assert is_scorable(base)
    assert not is_scorable({**base, "game_mode": "ARAM"})
    assert not is_scorable({**base, "end_of_game_result": "Abort_Unexpected"})
    assert is_scorable({**base, "end_of_game_result": None, "game_duration": 301})
    assert not is_scorable({**base, "end_of_game_result": None, "game_duration": 300})
    assert not is_scorable({**base, "remake": True})


def test_remake_detection():
    mapped = map_match(make_match_json("NA1_9", duration_s=200, remake=True))
    assert mapped.match["remake"] is True
    assert not is_scorable(mapped.match)


def test_short_games_are_remakes_even_without_the_early_surrender_flag():
    """Match history and the season stats have always counted a game under five minutes as
    a remake; ingestion has to agree, or those games get an AI Score and fire bot events
    while being labelled "Remake" everywhere else."""
    mapped = map_match(make_match_json("NA1_10", duration_s=215, end_of_game_result="GameComplete"))
    assert mapped.match["remake"] is True
    assert not is_scorable(mapped.match)
    assert map_match(make_match_json("NA1_11", duration_s=301)).match["remake"] is False


def test_arena_subteams_and_placements_are_stored():
    """Arena packs eight two-player subteams into teamId 100/200, so the duo a player was
    actually on only exists in playerSubteamId."""
    raw = make_match_json("NA1_78", game_mode="CHERRY", queue_id=1700, duration_s=900)
    raw["info"]["participants"] = raw["info"]["participants"][:8]
    for index, participant in enumerate(raw["info"]["participants"]):
        participant["teamId"] = 100 if index < 4 else 200
        participant["playerSubteamId"] = index // 2 + 1
        participant["placement"] = index + 1
    mapped = map_match(raw)
    assert [p["player_subteam_id"] for p in mapped.participants] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert [p["placement"] for p in mapped.participants] == list(range(1, 9))
    # Summoner's Rift payloads carry 0 for both, which is not a subteam.
    rift = map_match(make_match_json("NA1_79"))
    assert all(p["player_subteam_id"] is None for p in rift.participants)
    assert all(p["placement"] is None for p in rift.participants)


def test_factory_output_maps():
    raw = make_match_json(
        "NA1_42",
        [spec("me", "Me", "NA1", kills=15, deaths=0, assists=3, position="JUNGLE")],
        queue_id=440,
        winning_team=200,
    )
    mapped = map_match(raw)
    me = mapped.participants[0]
    assert me["puuid"] == "me" and me["kills"] == 15 and me["deaths"] == 0
    assert me["team_position"] == "JUNGLE"
    assert me["win"] is False and mapped.participants[9]["win"] is True
    assert mapped.match["queue_id"] == 440
    assert is_scorable(mapped.match)
    assert len({p["puuid"] for p in mapped.participants}) == 10
    teams = raw["info"]["teams"]
    assert [t["teamId"] for t in teams] == [100, 200]
    assert teams[0]["objectives"]["champion"]["kills"] == sum(
        p["kills"] for p in raw["info"]["participants"][:5]
    )
