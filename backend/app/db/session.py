import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.base import Base


class DatabaseManager:
    """Manages async SQLAlchemy engine, schema initialization, and session factory."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        engine_kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in database_url:
                engine_kwargs["poolclass"] = StaticPool

        self.engine: AsyncEngine = create_async_engine(database_url, **engine_kwargs)
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        self._init_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Create database tables idempotently."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            # Import models so metadata is populated before create_all.
            from app.db import models as _models  # noqa: F401

            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            self._initialized = True

    async def dispose(self) -> None:
        """Dispose underlying SQLAlchemy engine connections."""
        await self.engine.dispose()

    async def ping(self) -> bool:
        """Check database connectivity with a lightweight SELECT 1 probe."""
        await self.initialize()
        async with self.session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True


def get_app_settings(request: Request) -> Settings:
    """Resolve app settings from FastAPI state with fallback to cached settings."""
    settings = getattr(request.app.state, "settings", None)
    if isinstance(settings, Settings):
        return settings
    return get_settings()


def get_db_manager(request: Request) -> DatabaseManager:
    """Resolve DatabaseManager from FastAPI app state, lazily creating if absent."""
    db = getattr(request.app.state, "db", None)
    if isinstance(db, DatabaseManager):
        return db
    settings = get_app_settings(request)
    db = DatabaseManager(settings.database_url)
    request.app.state.db = db
    return db


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a transactional async database session for request handlers."""
    db = get_db_manager(request)
    await db.initialize()
    async with db.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
