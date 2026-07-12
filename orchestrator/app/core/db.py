"""Database access: a shared asyncpg pool and a tiny migration runner.

Migrations are plain .sql files in migrations/, applied in filename order and
tracked in a schema_migrations table so re-running is a no-op. Everything runs
inside the schema named by settings.db_schema (default "work").
"""

from __future__ import annotations

import json
from pathlib import Path

import asyncpg

from .config import get_settings

# app/core/db.py -> orchestrator/migrations
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Per-connection setup: register a json codec so jsonb columns round-trip
    as Python objects. (search_path is pinned via server_settings on the pool.)"""
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=1,
            max_size=10,
            init=_init_connection,
            # Pin the work schema at the protocol level for every connection.
            server_settings={"search_path": settings.db_schema},
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def run_migrations() -> list[str]:
    """Apply any unapplied .sql migrations. Returns the names applied this run."""
    settings = get_settings()
    schema = settings.db_schema

    # A bootstrap connection that does NOT pin search_path (the schema may not
    # exist yet). We create the schema, then the tracking table, then apply.
    conn = await asyncpg.connect(settings.database_url)
    applied: list[str] = []
    try:
        await conn.execute(f'create schema if not exists "{schema}"')
        await conn.execute(f'set search_path to "{schema}"')
        await conn.execute(
            """
            create table if not exists schema_migrations (
              name text primary key,
              applied_at timestamptz not null default now()
            )
            """
        )
        done = {
            r["name"]
            for r in await conn.fetch("select name from schema_migrations")
        }
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            sql = path.read_text()
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "insert into schema_migrations (name) values ($1)", path.name
                )
            applied.append(path.name)
    finally:
        await conn.close()
    return applied
