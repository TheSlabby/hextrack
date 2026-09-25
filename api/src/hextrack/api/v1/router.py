"""Assembles the /api/v1 router from the route modules."""

from __future__ import annotations

from fastapi import APIRouter

from hextrack.api.v1 import (
    ai,
    health,
    insights,
    leaderboard,
    live,
    matches,
    meta,
    records,
    roster,
    search,
    squad,
    summoners,
)

API_PREFIX = "/api/v1"


def build_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    for module in (
        health,
        meta,
        search,
        summoners,
        ai,
        insights,
        matches,
        leaderboard,
        roster,
        squad,
        live,
        records,
    ):
        router.include_router(module.router)
    return router
