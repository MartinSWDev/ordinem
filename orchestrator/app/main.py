"""FastAPI application entrypoint for the Ordinem orchestrator.

Each island is a self-contained package under app/islands/ that exposes one or
more FastAPI routers; this module wires the shared core (db/migrations) and
registers every island's routers. See docs/ARCHITECTURE.md for the pattern.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import close_pool, get_pool, run_migrations
from app.islands.calendar.router import router as calendar_router
from app.islands.review.router import router as review_router
from app.islands.tickets.commit_plans import router as commit_plans_router
from app.islands.tickets.projects import router as projects_router
from app.islands.tickets.router import router as tickets_router
from app.islands.todos.router import router as todos_router

logger = logging.getLogger("ordinem.orchestrator")

# Every island's routers, grouped by island for readability.
ISLAND_ROUTERS = [
    tickets_router,
    projects_router,
    commit_plans_router,
    review_router,
    calendar_router,
    todos_router,
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    applied = await run_migrations()
    if applied:
        logger.info("applied migrations: %s", ", ".join(applied))
    app.state.pool = await get_pool()
    try:
        yield
    finally:
        await close_pool()


app = FastAPI(
    title="Ordinem Orchestrator",
    version="0.1.0",
    summary="Jira ticket -> AI agent -> reviewed diff pipeline.",
    lifespan=lifespan,
)

for _router in ISLAND_ROUTERS:
    app.include_router(_router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "jira_configured": settings.jira_configured,
        "qwen_configured": settings.qwen_configured,
    }
