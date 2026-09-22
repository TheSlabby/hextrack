"""Shared pytest fixtures.

Database: each pytest session creates its own throwaway database
``hextrack_test_<8 hex>`` (several agents/CI jobs may run concurrently), builds the schema
with ``Base.metadata.create_all`` and drops it ``WITH (FORCE)`` at the end. The admin
connection comes from ``HEXTRACK_TEST_ADMIN_URL`` or, failing that, ``DATABASE_URL`` /
the dev default (the role must be allowed to CREATE DATABASE).

Fixtures:

* ``settings``: Settings for the test DB, no Riot key, empty tmp model dir, no web dist,
  admin token ``TEST_ADMIN_TOKEN``.
* ``engine`` / ``session_factory`` (session-scoped), ``session`` (function-scoped, all
  tables truncated first).
* ``fake_riot``: a fresh :class:`tests.fakes.FakeRiotClient`.
* ``app`` (lifespan running, fake Riot installed, DB truncated) and ``client``
  (``httpx.AsyncClient`` over ASGI). Use ``tests.fakes.install_fakes(app, scorer=...)`` to
  swap the scorer or Riot client.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import psycopg
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from hextrack.config import DEFAULT_DATABASE_URL, Settings, normalize_async_database_url
from hextrack.db import models  # noqa: F401  (register tables)
from hextrack.db.base import Base
from hextrack.db.engine import make_async_engine, make_session_factory
from hextrack.db.models import ALL_TABLES
from tests.fakes import FakeRiotClient, install_fakes

TEST_ADMIN_TOKEN = "test-admin-token"
FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _admin_url() -> str:
    url = (
        os.environ.get("HEXTRACK_TEST_ADMIN_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    return normalize_async_database_url(url)


def _libpq(url: str) -> str:
    """SQLAlchemy URL -> libpq conninfo for psycopg."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def test_database_url() -> Iterator[str]:
    """Create a unique database for this pytest session and drop it afterwards."""
    admin = _admin_url()
    name = f"hextrack_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(_libpq(admin), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_url(admin).set(database=name).render_as_string(hide_password=False)
    finally:
        with psycopg.connect(_libpq(admin), autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture(scope="session")
async def engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = make_async_engine(
        Settings(database_url=test_database_url, _env_file=None),  # type: ignore[call-arg]
        pool_size=5,
        max_overflow=5,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture(scope="session")
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return make_session_factory(engine)


async def truncate_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(ALL_TABLES)} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def clean_db(engine: AsyncEngine) -> None:
    """Empty every table before the test."""
    await truncate_all(engine)


@pytest.fixture
async def session(
    clean_db: None, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def settings(test_database_url: str, engine: AsyncEngine, tmp_path: Path) -> Settings:
    """Depends on ``engine`` so the schema exists before any app starts."""
    model_dir = tmp_path / "artifacts"
    model_dir.mkdir()
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=test_database_url,
        riot_api_key=None,
        model_dir=model_dir,
        web_dist=tmp_path / "web-dist-missing",
        admin_token=TEST_ADMIN_TOKEN,
        discord_token=None,
        discord_broadcast_channel_id=None,
        cors_origins=["http://localhost:5173"],
        run_worker_in_process=False,
    )


@pytest.fixture
def fake_riot(settings: Settings) -> FakeRiotClient:
    return FakeRiotClient(settings)


@pytest.fixture
async def app(
    clean_db: None, settings: Settings, fake_riot: FakeRiotClient
) -> AsyncIterator[FastAPI]:
    from hextrack.main import create_app

    application = create_app(settings)
    async with LifespanManager(application):
        install_fakes(application, riot=fake_riot)
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest.fixture
def admin_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_ADMIN_TOKEN}"}


@pytest.fixture
def match_sample() -> dict:
    import json

    return json.loads((FIXTURES_DIR / "match_sample.json").read_text())
