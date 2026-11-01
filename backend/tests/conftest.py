"""Shared fixtures: a real SQLite database per test, because the repository's rules live in its SQL."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

# Set before any `app` import: the settings are read once, and must never point a test run at /data.
os.environ.setdefault("BRICKSEEKER_DATA_DIR", tempfile.mkdtemp(prefix="brickseeker-tests-"))

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture
async def session(tmp_path) -> AsyncIterator[AsyncSession]:  # noqa: ANN001 - pytest fixture
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db_session:
        yield db_session
    await engine.dispose()


@pytest.fixture
async def client(session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """The real routes over the test database. No lifespan, so no scheduler and no browser."""

    async def test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = test_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.clear()
