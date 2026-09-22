"""Engine and session factory helpers.

The web app, worker and bot use the async engine (asyncpg). The CLI's training and batch
commands can use :func:`make_sync_engine`, which swaps the driver to psycopg 3.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from hextrack.config import Settings, normalize_async_database_url


def to_sync_url(url: str) -> str:
    """Rewrite any postgres URL to use the psycopg (v3) sync driver."""
    return normalize_async_database_url(url).replace(
        "postgresql+asyncpg://", "postgresql+psycopg://", 1
    )


def make_async_engine(settings: Settings, **kwargs: object) -> AsyncEngine:
    """Create the application's async engine (asyncpg driver)."""
    options: dict[str, object] = {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 10}
    options.update(kwargs)
    return create_async_engine(normalize_async_database_url(settings.database_url), **options)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Session factory; ``expire_on_commit=False`` so ORM rows stay usable after commit."""
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def make_sync_engine(settings: Settings, **kwargs: object) -> Engine:
    """Create a synchronous engine (psycopg driver) for CLI / training code."""
    options: dict[str, object] = {"pool_pre_ping": True}
    options.update(kwargs)
    return create_engine(to_sync_url(settings.database_url), **options)


def make_sync_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Open a session, commit on success, roll back on error."""
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
