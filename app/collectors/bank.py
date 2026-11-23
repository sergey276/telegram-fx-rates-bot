"""Сборщик курсов банка: периодический опрос REST с учётом ограничений API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence

from app.cache import QuoteStore
from app.domain import Quote
from app.providers.base import BaseProvider
from app.services.assets import AssetRegistry
from app.services.health import HealthRegistry
from app.utils.http import GeoBlockedError, ProviderError, RateLimitedError

log = logging.getLogger(__name__)

_MAX_BACKOFF = 1800.0

BankBatchHandler = Callable[[Sequence[Quote]], Awaitable[object]]


class BankCollector:
    def __init__(
        self,
        provider: BaseProvider,
        store: QuoteStore,
        health: HealthRegistry,
        assets: AssetRegistry,
        poll_seconds: int,
        on_batch: BankBatchHandler | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.health = health
        self.assets = assets
        self.name = provider.name
        self._poll = poll_seconds
        self._on_batch = on_batch
        self._task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._failures = 0

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"collector-{self.name}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def poke(self) -> None:
        self._wakeup.set()

    async def _run(self) -> None:
        while True:
            delay = await self._poll_once()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), timeout=delay)
            self._wakeup.clear()

    async def _poll_once(self) -> float:
        """Один опрос. Возвращает, через сколько секунд опрашивать снова."""
        if not self.health.is_enabled(self.name):
            return 30.0
        try:
            quotes = await self.provider.fetch_quotes()
        except RateLimitedError as exc:
            self.health.record_error(self.name, f"лимит запросов, пауза {exc.retry_after:.0f} с")
            return max(exc.retry_after, self._poll)
        except GeoBlockedError as exc:
            self.health.record_error(self.name, str(exc))
            return 600.0
        except ProviderError as exc:
            self._failures += 1
            delay = min(30.0 * 2 ** (self._failures - 1), _MAX_BACKOFF)
            self.health.record_error(self.name, f"{exc}. Повтор через {delay:.0f} с")
            return min(delay, self._poll)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("%s: непредвиденная ошибка", self.name)
            self.health.record_error(self.name, f"{type(exc).__name__}: {exc}")
            return 60.0

        self._failures = 0
        self.health.record_success(self.name)
        self.store.put_many(quotes)
        if self._on_batch is not None:
            tracked = [q for q in quotes if self.assets.is_tracked(q.symbol)]
            try:
                await self._on_batch(tracked)
            except Exception:
                log.exception("%s: не удалось сохранить курсы в БД", self.name)
        return float(self._poll)
