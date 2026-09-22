"""Assembles the /api/v1 router from the route modules."""

from __future__ import annotations

from fastapi import APIRouter

from hextrack.api.v1 import ai, health, leaderboard, matches, meta, roster, search, summoners

API_PREFIX = "/api/v1"


def build_router() -> APIRouter:
    router = APIRouter(prefix=API_PREFIX)
    for module in (health, meta, search, summoners, ai, matches, leaderboard, roster):
        router.include_router(module.router)
    return router
