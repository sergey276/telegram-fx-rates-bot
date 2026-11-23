"""Подключение к БД и фабрика сессий."""

from __future__ import annotations

import logging
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import exc as sa_exc
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database.models import Base

log = logging.getLogger(__name__)


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        self.url = url
        kwargs: dict[str, object] = {"echo": echo}
        if url.startswith("sqlite"):
            warnings.filterwarnings("ignore", category=sa_exc.SAWarning, message=".*Decimal.*")
            if ":memory:" in url or url.endswith("sqlite+aiosqlite://"):
                kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})
        else:
            kwargs.update(pool_size=10, max_overflow=10, pool_pre_ping=True, pool_recycle=1800)
        self.engine: AsyncEngine = create_async_engine(url, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Сессия с автоматическим commit при успехе и rollback при исключении."""
        async with self.sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def create_all(self) -> None:
        """Только для тестов/SQLite. В production схема создаётся миграциями Alembic."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def ping(self) -> bool:
        from sqlalchemy import text

        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as exc:
            log.error("БД недоступна: %s", exc)
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()


def insert_for(dialect: str):  # noqa: ANN201
    """``INSERT ... ON CONFLICT`` для PostgreSQL и SQLite (одинаковый API)."""
    return postgresql.insert if dialect == "postgresql" else sqlite.insert
