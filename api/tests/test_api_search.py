"""GET /search."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from tests.test_api_support import add_rank, add_summoner

T0 = datetime(2026, 3, 1, tzinfo=UTC)


async def seed(session) -> None:
    await add_summoner(session, "p-hexwalker", "Hex Walker", "NA1")
    await add_summoner(session, "p-hexy", "hexy", "EUW", tracked=True)
    await add_summoner(session, "p-texas", "Walker Texas", "NA1")
    await add_summoner(session, "p-other", "Other", "NA1")
    await add_summoner(session, "p-uni", "Ünïcode Náme", "ÉUW")
    await add_summoner(session, "p-pct", "100%_Real", "NA1")
    # A deleted account whose Riot ID was parked by ingestion is not searchable.
    await add_summoner(session, "p-gone", "Hex Walker", "NA1~p-gone12")
    await add_rank(session, "p-hexwalker", "RANKED_SOLO_5x5", "GOLD", "III", 12, taken_at=T0)
    await add_rank(
        session,
        "p-hexwalker",
        "RANKED_SOLO_5x5",
        "GOLD",
        "II",
        40,
        taken_at=T0 + timedelta(days=1),
    )
    await add_rank(session, "p-hexwalker", "RANKED_FLEX_SR", "DIAMOND", "I", 3, taken_at=T0)
    await add_rank(session, "p-hexy", "RANKED_SOLO_5x5", "CHALLENGER", None, 1200, taken_at=T0)
    await session.commit()


async def search(client, q: str, **params) -> list[dict]:
    extra = "".join(f"&{k}={v}" for k, v in params.items())
    resp = await client.get(f"/api/v1/search?q={quote(q, safe='')}{extra}")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_search_tracked_first_then_prefix(client, session):
    await seed(session)
    results = await search(client, "hex")
    assert [r["puuid"] for r in results] == ["p-hexy", "p-hexwalker"]
    hexy, walker = results
    assert hexy["is_tracked"] is True
    assert hexy["solo_tier"] == "CHALLENGER" and hexy["solo_rank"] is None
    assert walker == {
        "puuid": "p-hexwalker",
        "game_name": "Hex Walker",
        "tag_line": "NA1",
        "profile_icon_id": 29,
        "summoner_level": 100,
        "is_tracked": False,
        "solo_tier": "GOLD",  # latest solo snapshot, flex ignored
        "solo_rank": "II",
    }


async def test_search_contains_is_case_insensitive(client, session):
    await seed(session)
    results = await search(client, "WALKER")
    # Both contain "walker"; the prefix match comes first.
    assert [r["puuid"] for r in results] == ["p-texas", "p-hexwalker"]
    assert [r["puuid"] for r in await search(client, "ex wal")] == ["p-hexwalker"]
    assert await search(client, "zzz") == []


async def test_search_by_riot_id(client, session):
    await seed(session)
    assert [r["puuid"] for r in await search(client, "hex walker#na1")] == ["p-hexwalker"]
    assert [r["puuid"] for r in await search(client, "Walker#NA")] == ["p-hexwalker"]
    assert [r["puuid"] for r in await search(client, "hexy#euw")] == ["p-hexy"]
    # A tag alone does not match every player on that tag.
    assert await search(client, "NA1") == []


async def test_search_unicode_and_like_escaping(client, session):
    await seed(session)
    assert [r["puuid"] for r in await search(client, "ÜNÏCODE")] == ["p-uni"]
    assert [r["puuid"] for r in await search(client, "náme#éuw")] == ["p-uni"]
    assert [r["puuid"] for r in await search(client, "%")] == ["p-pct"]
    assert [r["puuid"] for r in await search(client, "_")] == ["p-pct"]


async def test_search_limit_and_validation(client, session):
    await seed(session)
    assert len(await search(client, "e", limit=2)) == 2
    assert (await client.get("/api/v1/search?q=")).status_code == 422
    assert (await client.get("/api/v1/search?q=a&limit=21")).status_code == 422
    assert await search(client, "#") == []
