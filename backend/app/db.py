"""Async SQLAlchemy engine + session plumbing over SQLite.

WAL is enabled on every connection: the app has one writer (the API) and several readers
(scheduler ticks, the price batch, the UI polling), and the default rollback journal would make
them block each other for the duration of a scrape.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import settings
from .models import Base

engine = create_async_engine(
    settings.sqlalchemy_url,
    echo=False,
    future=True,
    # SQLite + asyncio: a pooled connection held across tasks is the classic source of
    # "cannot operate on a closed database" under concurrency. NullPool opens per session,
    # which SQLite handles fine at this app's request volume.
    poolclass=NullPool,
    connect_args={"check_same_thread": False, "timeout": 30},
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("PRAGMA optimize"))


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """For background work (scheduler, price batch) that has no request to hang a dependency off."""
    async with SessionLocal() as session:
        yield session
