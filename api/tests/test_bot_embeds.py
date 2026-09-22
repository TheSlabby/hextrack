"""Embed builders (pure functions): copy, fields, footers, colours, links."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from hextrack.bot import embeds
from hextrack.bot.embeds import (
    ANSI_BOLD_GREEN,
    ANSI_BOLD_RED,
    ANSI_RED,
    ANSI_WHITE,
    BAD_GAME_COLOUR,
    DAILY_COLOUR,
    EMPTY_LEADERBOARD,
    GREAT_GAME_COLOUR,
    MEDALS,
    PLAYER_INFO_COLOUR,
    TIER_DOWN_COLOUR,
    TIER_UP_COLOUR,
    EmbedContext,
    GameEvent,
    LeaderboardEntry,
    PlayerRef,
    RankLine,
    TierChangeEvent,
)
from hextrack.riot.ddragon import CDN

VERSION = "16.18.1"
CTX = EmbedContext(public_url="https://hextrack.example", ddragon_version=VERSION)
PLAYER = PlayerRef(puuid="p1", game_name="Hex Walker", tag_line="NA1", profile_icon_id=4568)
GAME_START = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
SUMMONER_URL = "https://hextrack.example/summoner/na/Hex%20Walker-NA1"


def tier_event(**overrides: object) -> TierChangeEvent:
    payload: dict[str, object] = {
        "puuid": "p1",
        "game_name": "Hex Walker",
        "tag_line": "NA1",
        "queue_type": "RANKED_SOLO_5x5",
        "old_tier": "SILVER",
        "old_rank": "I",
        "new_tier": "GOLD",
        "new_rank": "IV",
        "lp": 12,
        "rank_value": 1212,
    }
    payload.update(overrides)
    return TierChangeEvent.model_validate(payload)


def game_event(**overrides: object) -> GameEvent:
    payload: dict[str, object] = {
        "puuid": "p1",
        "game_name": "Hex Walker",
        "tag_line": "NA1",
        "match_id": "NA1_5001",
        "queue_id": 420,
        "champion_id": 103,
        "champion_name": "Ahri",
        "win": True,
        "kills": 12,
        "deaths": 1,
        "assists": 9,
        "kda": 21.0,
        "ai_score": 0.826,
        "game_start": GAME_START.isoformat(),
        "game_duration": 1804,
    }
    payload.update(overrides)
    return GameEvent.model_validate(payload)


def fields(embed: object) -> dict[str, tuple[str, bool]]:
    return {f.name: (f.value, f.inline) for f in embed.fields}  # type: ignore[attr-defined]


# --- context ------------------------------------------------------------------------------


def test_summoner_url_uses_hextrack_slug_and_escapes_the_name() -> None:
    assert CTX.summoner_url("Hex Walker", "NA1") == SUMMONER_URL
    assert CTX.summoner_url("Faker-Fan", "KR1").endswith("/summoner/na/Faker-Fan-KR1")
    assert (
        CTX.summoner_url("Ünï", "EUW") == "https://hextrack.example/summoner/na/%C3%9Cn%C3%AF-EUW"
    )
    euw = EmbedContext(public_url="https://hextrack.example/", platform="euw1")
    assert euw.summoner_url("A", "B1") == "https://hextrack.example/summoner/euw/A-B1"


def test_asset_urls() -> None:
    assert CTX.profile_icon_url(4568) == f"{CDN}/{VERSION}/img/profileicon/4568.png"
    assert CTX.profile_icon_url(None) == f"{CDN}/{VERSION}/img/profileicon/29.png"
    assert CTX.champion_icon_url(103, "Ahri") == f"{CDN}/{VERSION}/img/champion/Ahri.png"
    keyed = EmbedContext(public_url="x", ddragon_version=VERSION, champion_keys={9: "Fiddlesticks"})
    assert keyed.champion_icon_url(9, "FiddleSticks") == (
        f"{CDN}/{VERSION}/img/champion/Fiddlesticks.png"
    )
    assert CTX.champion_icon_url(None, "") is None


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (None, None),
        ("https://cdn.example/emblems/", "https://cdn.example/emblems/gold.png"),
        ("https://cdn.example/emblems", "https://cdn.example/emblems/gold.png"),
        ("https://cdn.example/emblem-", "https://cdn.example/emblem-gold.png"),
    ],
)
def test_rank_emblem_url(base: str | None, expected: str | None) -> None:
    ctx = EmbedContext(public_url="x", rank_icon_base=base)
    assert ctx.rank_emblem_url("GOLD") == expected


# --- tier up / down -----------------------------------------------------------------------


def test_tier_up_embed() -> None:
    embed = embeds.tier_up(tier_event(), PLAYER, CTX)
    assert embed.title == "Ranked up to GOLD!"
    assert embed.colour is not None and embed.colour.value == TIER_UP_COLOUR == 0x6CBB3C
    assert embed.description == "Now **Gold IV 12 LP** in Ranked Solo/Duo"
    assert embed.author.name == "Hex Walker#NA1"
    assert embed.author.url == SUMMONER_URL
    assert embed.author.icon_url == f"{CDN}/{VERSION}/img/profileicon/4568.png"
    assert embed.image.url is None  # no HEXTRACK_RANK_ICON_BASE
    assert "op.gg" not in str(embed.to_dict())


def test_tier_up_embed_shows_emblem_when_configured() -> None:
    ctx = EmbedContext(public_url="https://h.example", rank_icon_base="https://cdn.example/r/")
    embed = embeds.tier_up(tier_event(new_tier="master", new_rank=None, lp=0), PLAYER, ctx)
    assert embed.title == "Ranked up to MASTER!"
    assert embed.description == "Now **Master 0 LP** in Ranked Solo/Duo"
    assert embed.image.url == "https://cdn.example/r/master.png"


def test_tier_down_embed_keeps_lpbot_copy() -> None:
    embed = embeds.tier_down(tier_event(new_tier="SILVER", new_rank="I", lp=75), PLAYER, CTX)
    assert embed.title == "Hex Walker#NA1 is a LOSER!"
    assert embed.description == "They just deranked to SILVER! LOL"
    assert embed.colour is not None and embed.colour.value == TIER_DOWN_COLOUR == 0x660000
    assert embed.author.url == SUMMONER_URL


def test_tier_down_embed_names_the_flex_queue() -> None:
    event = tier_event(queue_type="RANKED_FLEX_SR", new_tier="SILVER")
    embed = embeds.tier_down(event, PLAYER, CTX)
    assert embed.description == "They just deranked to SILVER in Ranked Flex! LOL"


def test_tier_down_title_escapes_markdown() -> None:
    player = PlayerRef(puuid="p", game_name="x_y_z", tag_line="NA1")
    assert embeds.tier_down(tier_event(), player, CTX).title == "x\\_y\\_z#NA1 is a LOSER!"


def test_tier_payload_validation() -> None:
    with pytest.raises(ValidationError):
        tier_event(new_tier="WOOD")
    with pytest.raises(ValidationError):
        TierChangeEvent.model_validate({"puuid": "p1"})
    assert tier_event(old_tier=None).old_tier is None


# --- great / bad game ---------------------------------------------------------------------


def test_great_game_embed() -> None:
    embed = embeds.great_game(game_event(), PLAYER, CTX)
    assert embed.title == "An AMAZING game! :O"
    assert embed.colour is not None and embed.colour.value == GREAT_GAME_COLOUR
    assert embed.description == (
        f"```ansi\n{ANSI_BOLD_GREEN}12{ANSI_WHITE} / 1{ANSI_WHITE} / 9\n```"
    )
    assert embed.thumbnail.url == f"{CDN}/{VERSION}/img/champion/Ahri.png"
    assert embed.author.name == "Hex Walker#NA1"
    assert embed.author.url == SUMMONER_URL
    assert fields(embed) == {
        "Champion": ("Ahri", True),
        "Result": ("Victory", True),
        "KDA": ("21.00", True),
        "Queue": ("Ranked Solo/Duo", True),
    }
    assert embed.footer.text == "AI Score: 83%"
    assert embed.timestamp == GAME_START
    assert embed.url == "https://hextrack.example/match/NA1_5001?player=Hex%20Walker-NA1"


def test_great_game_without_ai_score_has_no_footer() -> None:
    embed = embeds.great_game(game_event(ai_score=None), PLAYER, CTX)
    assert embed.footer.text is None
    assert "footer" not in embed.to_dict()


@pytest.mark.parametrize(
    ("score", "text"),
    [
        (0.0, "AI Score: 0%"),
        (0.625, "AI Score: 63%"),
        (0.994, "AI Score: 99%"),
        (1.0, "AI Score: 100%"),
    ],
)
def test_ai_score_footer_rounds_like_lpbot(score: float, text: str) -> None:
    assert embeds.ai_score_footer(score) == text


def test_ai_score_footer_ignores_missing_or_nan() -> None:
    assert embeds.ai_score_footer(None) is None
    assert embeds.ai_score_footer(float("nan")) is None


def test_bad_game_embed() -> None:
    event = game_event(kills=1, deaths=9, assists=2, kda=0.33, win=False, ai_score=0.12)
    embed = embeds.bad_game(event, PLAYER, CTX)
    assert embed.title == "What a TERRIBLE game! LOL"
    assert embed.colour is not None and embed.colour.value == BAD_GAME_COLOUR
    assert embed.description == f"```ansi\n{ANSI_WHITE}1 / {ANSI_RED}9{ANSI_WHITE} / 2\n```"
    assert fields(embed)["Result"] == ("Defeat", True)
    assert embed.footer.text == "AI Score: 12%"


def test_game_event_computes_kda_and_normalises_timestamps() -> None:
    event = game_event(kda=None, kills=10, deaths=0, assists=5, game_start="2026-03-01T20:00:00")
    assert event.kda_ratio == 15.0
    assert event.game_start == GAME_START
    assert embeds.great_game(event, PLAYER, CTX).fields[2].value == "15.00"


# --- daily leaderboard --------------------------------------------------------------------


def test_daily_leaderboard_orders_and_colours_entries() -> None:
    now = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
    entries = [
        LeaderboardEntry("Alpha#NA1", 50),
        LeaderboardEntry("Bravo#NA1", -20),
        LeaderboardEntry("Charlie#NA1", 120),
        LeaderboardEntry("Delta#NA1", 0),
        LeaderboardEntry("Echo#NA1", 5),
    ]
    embed = embeds.daily_leaderboard(entries, season_year=2026, timestamp=now)
    assert embed.title == "\N{TROPHY} Season 2026 Leaderboard"
    assert embed.colour is not None and embed.colour.value == DAILY_COLOUR == 0xFFD700
    assert embed.timestamp == now
    assert embed.description is not None
    lines = embed.description.split("\n")
    assert lines[0] == "```ansi" and lines[-1] == "```"
    assert lines[1:-1] == [
        f"{MEDALS[0]} {ANSI_BOLD_GREEN}+120 LP{ANSI_WHITE}   Charlie#NA1",
        f"{MEDALS[1]} {ANSI_BOLD_GREEN}+50 LP{ANSI_WHITE}   Alpha#NA1",
        f"{MEDALS[2]} {ANSI_BOLD_GREEN}+5 LP{ANSI_WHITE}   Echo#NA1",
        f"4. {ANSI_BOLD_RED}-20 LP{ANSI_WHITE}   Bravo#NA1",
    ]
    assert "Delta" not in embed.description


def test_daily_leaderboard_breaks_ties_by_name() -> None:
    ranked = embeds.rank_leaderboard(
        [LeaderboardEntry("zed#NA1", 10), LeaderboardEntry("Ann#NA1", 10)]
    )
    assert [e.name for e in ranked] == ["Ann#NA1", "zed#NA1"]


def test_daily_leaderboard_empty() -> None:
    embed = embeds.daily_leaderboard(
        [LeaderboardEntry("Delta#NA1", 0)], season_year=2026, timestamp=datetime.now(UTC)
    )
    assert embed.description == EMPTY_LEADERBOARD


def test_daily_leaderboard_stays_under_discord_limits() -> None:
    entries = [LeaderboardEntry(f"Player Number {i:03d}#NA1", 1000 - i) for i in range(400)]
    embed = embeds.daily_leaderboard(entries, season_year=2026, timestamp=datetime.now(UTC))
    assert embed.description is not None
    assert len(embed.description) <= 4096
    assert embed.description.endswith("\n```")
    assert "more" in embed.description.split("\n")[-2]


def test_daily_leaderboard_names_cannot_break_the_code_block() -> None:
    embed = embeds.daily_leaderboard(
        [LeaderboardEntry("evil```#NA1", 3)], season_year=2026, timestamp=datetime.now(UTC)
    )
    assert embed.description is not None
    assert embed.description.count("```") == 2


# --- /lp player info ----------------------------------------------------------------------


def rank_line(**overrides: object) -> RankLine:
    values: dict[str, object] = {
        "queue_type": "RANKED_SOLO_5x5",
        "tier": "GOLD",
        "rank": "II",
        "lp": 45,
        "wins": 30,
        "losses": 25,
        "taken_at": datetime(2026, 3, 9, 18, 0, tzinfo=UTC),
    }
    values.update(overrides)
    return RankLine(**values)  # type: ignore[arg-type]


def test_player_info_embed() -> None:
    embed = embeds.player_info(PLAYER, rank_line(), CTX)
    assert embed.title == "Solo/Duo Ranked Info"
    assert embed.colour is not None and embed.colour.value == PLAYER_INFO_COLOUR
    assert embed.description == "**Current Rank:** Gold II"
    assert fields(embed) == {
        "LP": ("45 LP", True),
        "W/L Record": ("30/25", True),
        "Winrate": ("55%", True),
    }
    assert embed.author.name == "Hex Walker#NA1"
    assert embed.author.url == SUMMONER_URL
    assert embed.author.icon_url == f"{CDN}/{VERSION}/img/profileicon/4568.png"
    assert embed.image.url is None
    assert embed.timestamp == datetime(2026, 3, 9, 18, 0, tzinfo=UTC)


def test_player_info_apex_tier_has_no_division() -> None:
    ctx = EmbedContext(public_url="https://h.example", rank_icon_base="https://cdn.example/r")
    embed = embeds.player_info(PLAYER, rank_line(tier="MASTER", rank="I", lp=212), ctx)
    assert embed.description == "**Current Rank:** Master"
    assert fields(embed)["LP"] == ("212 LP", True)
    assert embed.image.url == "https://cdn.example/r/master.png"


def test_player_info_without_games_or_rank() -> None:
    no_games = embeds.player_info(PLAYER, rank_line(wins=0, losses=0), CTX)
    assert fields(no_games)["Winrate"] == ("-", True)

    unranked = embeds.player_info(PLAYER, None, CTX)
    assert unranked.title == "Solo/Duo Ranked Info"
    assert unranked.description == "**Current Rank:** Unranked"
    assert unranked.fields == []
    assert unranked.image.url is None


def test_player_info_flex_title() -> None:
    embed = embeds.player_info(PLAYER, rank_line(queue_type="RANKED_FLEX_SR"), CTX)
    assert embed.title == "Flex Ranked Info"
