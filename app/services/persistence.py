"""Периодическое сохранение: снимки курсов бирж, изменения курсов банков, статус источников, очистка."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import timedelta
from decimal import Decimal

from app.cache import QuoteStore
from app.config import Settings
from app.database import Database
from app.database.repositories import AlertRepo, HistoryRepo, RatesRepo, StatusRepo
from app.domain import Quote, SourceKind, utcnow
from app.services.assets import AssetRegistry
from app.services.health import HealthRegistry

log = logging.getLogger(__name__)

_RateTuple = tuple[Decimal | None, Decimal | None, Decimal | None]


class PersistenceService:
    def __init__(
        self,
        db: Database,
        store: QuoteStore,
        assets: AssetRegistry,
        health: HealthRegistry,
        settings: Settings,
    ) -> None:
        self._db = db
        self._store = store
        self._assets = assets
        self._health = health
        self._settings = settings
        self._last_bank: dict[tuple[str, str], _RateTuple] = {}
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        async with self._db.session() as session:
            self._last_bank = await RatesRepo(session, self._db.dialect).last_bank_rates()
        self._tasks = [
            asyncio.create_task(self._loop(self._settings.exchange_rates_snapshot_seconds, self.snapshot_exchange_rates)),
            asyncio.create_task(self._loop(15, lambda: self._health.persist(self._db))),
            asyncio.create_task(self._loop(6 * 3600, self.cleanup, first_delay=300)),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.snapshot_exchange_rates()
        await self._health.persist(self._db)

    @staticmethod
    async def _loop(interval: float, action: Callable[[], Awaitable[object]], first_delay: float | None = None) -> None:
        await asyncio.sleep(first_delay if first_delay is not None else interval)
        while True:
            try:
                await action()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ошибка фоновой задачи сохранения")
            await asyncio.sleep(interval)

    async def snapshot_exchange_rates(self) -> None:
        quotes = [
            q
            for q in self._store.all()
            if q.kind is SourceKind.EXCHANGE and self._assets.is_tracked(q.symbol)
        ]
        if not quotes:
            return
        async with self._db.session() as session:
            await RatesRepo(session, self._db.dialect).upsert_exchange_rates(quotes)

    async def save_bank_quotes(self, quotes: Sequence[Quote]) -> int:
        """Записывает в ``bank_rates`` только изменившиеся курсы."""
        changed = [
            q for q in quotes if self._last_bank.get((q.source, q.symbol)) != (q.bid, q.ask, q.cross_rate)
        ]
        if not changed:
            return 0
        async with self._db.session() as session:
            await RatesRepo(session, self._db.dialect).add_bank_rates(changed)
        for q in changed:
            self._last_bank[(q.source, q.symbol)] = (q.bid, q.ask, q.cross_rate)
        return len(changed)

    async def cleanup(self) -> None:
        s = self._settings
        now = utcnow()
        async with self._db.session() as session:
            removed = await HistoryRepo(session, self._db.dialect).cleanup(
                timedelta(hours=s.history_1m_retention_hours), timedelta(days=s.history_1h_retention_days)
            )
            removed += await RatesRepo(session, self._db.dialect).cleanup_bank_rates(
                now - timedelta(days=s.bank_rates_retention_days)
            )
            removed += await AlertRepo(session).cleanup_history(now - timedelta(days=s.alert_history_retention_days))
            removed += await StatusRepo(session, self._db.dialect).cleanup_errors(
                now - timedelta(days=s.error_log_retention_days)
            )
        log.info("Очистка старых данных: удалено строк %d", removed)
