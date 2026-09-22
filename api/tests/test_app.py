"""App wiring: error mapping, admin auth, SPA fallback."""

from pathlib import Path

import httpx
from asgi_lifespan import LifespanManager
from fastapi import APIRouter

from hextrack.api.deps import AdminDep, ScorerDep
from hextrack.config import Settings
from hextrack.main import create_app
from hextrack.riot.errors import (
    RiotForbidden,
    RiotKeyMissing,
    RiotNotFound,
    RiotRateLimited,
    RiotUnavailable,
)


def _app_with_probe(settings: Settings):
    app = create_app(settings)
    probe = APIRouter()
    errors = {
        "key": RiotKeyMissing(),
        "forbidden": RiotForbidden("expired", status=403),
        "rate": RiotRateLimited(retry_after=7.2),
        "down": RiotUnavailable("boom", status=503),
        "missing": RiotNotFound("no such account", status=404),
    }

    @probe.get("/api/v1/_probe/{kind}")
    async def raise_riot(kind: str) -> dict:
        raise errors[kind]

    @probe.get("/api/v1/_admin")
    async def admin_only(_admin: AdminDep) -> dict:
        return {"ok": True}

    @probe.get("/api/v1/_model")
    async def model_only(scorer: ScorerDep) -> dict:
        return {"ok": True}

    app.include_router(probe)
    return app


async def test_riot_error_mapping(settings):
    app = _app_with_probe(settings)
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/api/v1/_probe/key")
            assert r.status_code == 503 and r.json()["code"] == "riot_key"
            r = await c.get("/api/v1/_probe/forbidden")
            assert r.status_code == 503 and r.json()["code"] == "riot_key"
            r = await c.get("/api/v1/_probe/rate")
            assert r.status_code == 429 and r.json()["code"] == "riot_rate_limited"
            assert r.headers["Retry-After"] == "7"
            r = await c.get("/api/v1/_probe/down")
            assert r.status_code == 502 and r.json()["code"] == "riot_unavailable"
            r = await c.get("/api/v1/_probe/missing")
            assert r.status_code == 404 and r.json()["code"] == "not_found"

            r = await c.get("/api/v1/_admin")
            assert r.status_code == 401 and r.json()["code"] == "unauthorized"
            r = await c.get("/api/v1/_admin", headers={"Authorization": "Bearer nope"})
            assert r.status_code == 403 and r.json()["code"] == "forbidden"
            r = await c.get(
                "/api/v1/_admin", headers={"Authorization": f"Bearer {settings.admin_token}"}
            )
            assert r.status_code == 200

            r = await c.get("/api/v1/_model")
            assert r.status_code == 503
            assert r.json() == {"detail": "AI model not loaded", "code": "model_missing"}


async def test_spa_fallback(settings, tmp_path: Path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    app = create_app(settings.model_copy(update={"web_dist": dist}))
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            r = await c.get("/summoner/na/Hex%20Walker-NA1")
            assert r.status_code == 200 and "root" in r.text
            assert (await c.get("/")).status_code == 200
            assert (await c.get("/assets/app.js")).text == "console.log(1)"
            assert (await c.get("/favicon.svg")).text == "<svg/>"
            assert (await c.get("/../../etc/passwd")).status_code in (200, 404)
            r = await c.get("/api/v1/nope")
            assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
            assert (await c.get("/api/v1/health")).json()["db_ok"] is True
