"""FastAPI dependencies and shared error plumbing for route modules.

Route modules should use the ``*Dep`` aliases, e.g.::

    async def get_thing(session: SessionDep, ctx: CtxDep) -> Thing: ...

Errors: raise :class:`ApiError` for JSON bodies shaped like
:class:`hextrack.api.schemas.ErrorResponse` (``{"detail", "code"}``); RiotError subclasses
raised anywhere are mapped by the handlers in :mod:`hextrack.main`.
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hextrack.api.schemas import ErrorResponse
from hextrack.config import Settings
from hextrack.hextrack_ai.inference import Scorer
from hextrack.ingest.context import IngestContext
from hextrack.riot.client import RiotClient
from hextrack.riot.ddragon import DDragon


class ApiError(Exception):
    """An error rendered as ``ErrorResponse`` JSON with the given status code."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.headers = headers

    def body(self) -> dict[str, Any]:
        return ErrorResponse(detail=self.detail, code=self.code).model_dump()


_ERROR_DESCRIPTIONS: dict[int, str] = {
    400: "Bad request",
    401: "Missing admin token",
    403: "Invalid admin token",
    404: "Not found",
    429: "Riot API rate limited (see Retry-After)",
    502: "Riot API unavailable",
    503: "Riot API key missing/rejected, or AI model not loaded",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """``responses=`` metadata declaring ErrorResponse bodies for the given status codes."""
    return {
        code: {"model": ErrorResponse, "description": _ERROR_DESCRIPTIONS.get(code, "Error")}
        for code in status_codes
    }


#: Errors any route that may call Riot can return.
RIOT_ERRORS: tuple[int, ...] = (429, 502, 503)

#: Pattern for free-text path and query parameters (Riot IDs, puuids, match ids, search
#: terms). No Riot identifier contains a control character, and a NUL byte reaches asyncpg
#: as invalid UTF-8, which fails the query with a 500 instead of simply matching nothing.
SAFE_TEXT: str = r"^[^\x00-\x1f\x7f]+$"


# --- app state accessors ---------------------------------------------------------------------


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Handlers commit explicitly; uncommitted work is rolled back
    when the session closes."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_ctx(request: Request) -> IngestContext:
    return request.app.state.ingest_ctx


def get_riot(request: Request) -> RiotClient:
    return request.app.state.riot


def get_ddragon(request: Request) -> DDragon:
    return request.app.state.ddragon


def get_scorer(request: Request) -> Scorer | None:
    """The loaded AI model, or None."""
    return getattr(request.app.state, "scorer", None)


def require_scorer(request: Request) -> Scorer:
    """The loaded AI model; 503 ``model_missing`` when none is loaded."""
    scorer = get_scorer(request)
    if scorer is None:
        raise ApiError(503, "AI model not loaded", "model_missing")
    return scorer


_bearer = HTTPBearer(auto_error=False, description="HEXTRACK_ADMIN_TOKEN")


def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """``Authorization: Bearer $HEXTRACK_ADMIN_TOKEN``: 401 when missing, 403 when wrong
    (or when no admin token is configured on the server)."""
    if credentials is None or not credentials.credentials:
        raise ApiError(
            401,
            "Admin token required",
            "unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = get_settings(request).admin_token
    if expected is None:
        raise ApiError(403, "Admin API is disabled (HEXTRACK_ADMIN_TOKEN not set)", "forbidden")
    if not secrets.compare_digest(credentials.credentials.encode(), expected.encode()):
        raise ApiError(403, "Invalid admin token", "forbidden")


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
CtxDep = Annotated[IngestContext, Depends(get_ctx)]
RiotDep = Annotated[RiotClient, Depends(get_riot)]
DDragonDep = Annotated[DDragon, Depends(get_ddragon)]
OptionalScorerDep = Annotated[Scorer | None, Depends(get_scorer)]
ScorerDep = Annotated[Scorer, Depends(require_scorer)]
AdminDep = Annotated[None, Depends(require_admin)]
