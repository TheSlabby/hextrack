"""GET /meta."""

from __future__ import annotations

import asyncio
from datetime import datetime

from hextrack.api.v1 import meta
from hextrack.riot.ddragon import CDN, FALLBACK_VERSION
from tests.fakes import install_fakes
from tests.test_api_support import FakeDDragon, StubScorer


async def test_meta(app, client, settings):
    ddragon = FakeDDragon("16.19.1")
    app.state.ddragon = ddragon
    resp = await client.get("/api/v1/meta")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ddragon_version"] == "16.19.1" and ddragon.calls == 1
    assert body["ddragon_cdn"] == CDN
    assert body["platform"] == "na1" and body["region"] == "americas"
    assert datetime.fromisoformat(body["season_start"]) == settings.season_start
    assert body["model_version"] is None and body["model_trained_at"] is None
    assert body["queues"]["420"] == "Ranked Solo/Duo"
    assert body["queues"]["440"] == "Ranked Flex"
    assert all(key.isdigit() for key in body["queues"])


async def test_meta_falls_back_when_ddragon_fails(app, client):
    app.state.ddragon = FakeDDragon(error=RuntimeError("offline"))
    body = (await client.get("/api/v1/meta")).json()
    assert body["ddragon_version"] == FALLBACK_VERSION

    app.state.ddragon = FakeDDragon(version="")
    body = (await client.get("/api/v1/meta")).json()
    assert body["ddragon_version"] == FALLBACK_VERSION


async def test_meta_times_out_slow_ddragon(app, client, monkeypatch):
    class SlowDDragon(FakeDDragon):
        async def latest_version(self) -> str:
            await asyncio.sleep(5)
            return "never"

    monkeypatch.setattr(meta, "DDRAGON_TIMEOUT_SECONDS", 0.05)
    app.state.ddragon = SlowDDragon()
    body = (await client.get("/api/v1/meta")).json()
    assert body["ddragon_version"] == FALLBACK_VERSION


async def test_meta_reports_loaded_model(app, client):
    app.state.ddragon = FakeDDragon()
    install_fakes(app, scorer=StubScorer("20260901-1200"))
    body = (await client.get("/api/v1/meta")).json()
    assert body["model_version"] == "20260901-1200"
    assert body["model_trained_at"].startswith("2026-09-01T12:00:00")
