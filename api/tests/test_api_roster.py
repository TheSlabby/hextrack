"""GET/PUT/DELETE /roster."""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import quote

import pytest
from sqlalchemy import select

from hextrack.db.models import Summoner
from hextrack.ingest import roster
from hextrack.riot.errors import RiotUnavailable
from tests.test_api_support import add_summoner


def roster_url(game_name: str, tag_line: str) -> str:
    return f"/api/v1/roster/{quote(game_name, safe='')}/{quote(tag_line, safe='')}"


async def test_list_roster_is_public_and_sorted(client, session):
    await add_summoner(
        session, "p-b", "bravo", "NA1", tracked=True, tracked_since=datetime(2026, 2, 1, tzinfo=UTC)
    )
    await add_summoner(session, "p-a", "Alpha", "NA1", tracked=True, profile_icon_id=7)
    await add_summoner(session, "p-u", "Untracked", "NA1")
    await session.commit()
    resp = await client.get("/api/v1/roster")
    assert resp.status_code == 200
    body = resp.json()
    assert [e["game_name"] for e in body] == ["Alpha", "bravo"]
    assert body[0] == {
        "puuid": "p-a",
        "game_name": "Alpha",
        "tag_line": "NA1",
        "tracked_since": body[0]["tracked_since"],
        "profile_icon_id": 7,
    }
    assert datetime.fromisoformat(body[1]["tracked_since"]) == datetime(2026, 2, 1, tzinfo=UTC)


@pytest.mark.parametrize("method", ["put", "delete"])
async def test_roster_writes_require_admin(client, method):
    url = roster_url("Hex Walker", "NA1")
    resp = await client.request(method.upper(), url)
    assert resp.status_code == 401 and resp.json()["code"] == "unauthorized"
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    resp = await client.request(method.upper(), url, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 403 and resp.json()["code"] == "forbidden"


async def test_add_roster_entry(client, session, admin_headers, monkeypatch):
    calls: list[str] = []
    since = datetime(2026, 9, 21, 12, tzinfo=UTC)

    async def fake_add(ctx, s, riot_id):
        calls.append(riot_id)
        summoner = Summoner(
            puuid="p-hex",
            game_name="Hex Walker",
            tag_line="NA1",
            platform="na1",
            profile_icon_id=4568,
            is_tracked=True,
            tracked_since=since,
        )
        s.add(summoner)
        await s.flush()
        return summoner

    monkeypatch.setattr(roster, "add_to_roster", fake_add)
    resp = await client.put(roster_url("Hex  Walker", "NA1"), headers=admin_headers)
    assert resp.status_code == 200, resp.text
    assert calls == ["Hex Walker#NA1"]
    assert resp.json() == {
        "puuid": "p-hex",
        "game_name": "Hex Walker",
        "tag_line": "NA1",
        "tracked_since": "2026-09-21T12:00:00Z",
        "profile_icon_id": 4568,
    }
    # Committed by the route: visible to other sessions and the public list.
    assert await session.scalar(select(Summoner.is_tracked).where(Summoner.puuid == "p-hex"))
    listed = (await client.get("/api/v1/roster")).json()
    assert [e["puuid"] for e in listed] == ["p-hex"]


async def test_add_roster_entry_unicode(client, admin_headers, monkeypatch):
    calls: list[str] = []

    async def fake_add(ctx, s, riot_id):
        calls.append(riot_id)
        summoner = Summoner(
            puuid="p-uni", game_name="Ünïcode", tag_line="ÉUW", platform="na1", is_tracked=True
        )
        s.add(summoner)
        await s.flush()
        return summoner

    monkeypatch.setattr(roster, "add_to_roster", fake_add)
    resp = await client.put(roster_url("Ünïcode", "ÉUW"), headers=admin_headers)
    assert resp.status_code == 200
    assert calls == ["Ünïcode#ÉUW"]


async def test_add_roster_entry_errors(client, admin_headers, monkeypatch):
    async def unknown(ctx, s, riot_id):
        raise roster.RosterError(f"no Riot account {riot_id}")

    monkeypatch.setattr(roster, "add_to_roster", unknown)
    resp = await client.put(roster_url("Nobody", "NA1"), headers=admin_headers)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"
    assert "Nobody#NA1" in resp.json()["detail"]

    resp = await client.put(roster_url("Nobody", "X"), headers=admin_headers)
    assert resp.status_code == 400 and resp.json()["code"] == "invalid_riot_id"

    async def riot_down(ctx, s, riot_id):
        raise RiotUnavailable("down", status=503)

    monkeypatch.setattr(roster, "add_to_roster", riot_down)
    resp = await client.put(roster_url("Nobody", "NA1"), headers=admin_headers)
    assert resp.status_code == 502 and resp.json()["code"] == "riot_unavailable"


async def test_remove_roster_entry(client, session, admin_headers, monkeypatch):
    await add_summoner(session, "p-hex", "Hex Walker", "NA1", tracked=True)
    await session.commit()
    calls: list[str] = []

    async def fake_remove(s, riot_id):
        calls.append(riot_id)
        summoner = await s.scalar(select(Summoner).where(Summoner.game_name == "Hex Walker"))
        if summoner is None or not summoner.is_tracked:
            return False
        summoner.is_tracked = False
        return True

    monkeypatch.setattr(roster, "remove_from_roster", fake_remove)
    resp = await client.delete(roster_url("hex walker", "na1"), headers=admin_headers)
    assert resp.status_code == 204 and resp.content == b""
    assert calls == ["hex walker#na1"]
    assert (await client.get("/api/v1/roster")).json() == []

    resp = await client.delete(roster_url("hex walker", "na1"), headers=admin_headers)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found"
