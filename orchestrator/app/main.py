"""FastAPI application entrypoint for the Ordinem orchestrator."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import close_pool, get_pool, run_migrations
from .routes import commit_plans, tickets

logger = logging.getLogger("ordinem.orchestrator")


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

app.include_router(tickets.router)
app.include_router(commit_plans.router)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "jira_configured": settings.jira_configured,
        "qwen_configured": settings.qwen_configured,
    }
