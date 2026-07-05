"""FastAPI dependencies: the connection pool and settings."""

from __future__ import annotations

import asyncpg
from fastapi import Request

from .config import Settings, get_settings


async def get_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def get_config() -> Settings:
    return get_settings()
