"""Хранилище актуальных котировок: память процесса + запись в Redis.

Чтение всегда идёт из памяти (мгновенно, бот не блокируется). Redis нужен, чтобы после перезапуска
сразу показать последние известные курсы (с пометкой об устаревании) и для внешних потребителей.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable, Iterable

from redis.asyncio import Redis

from app.domain import Freshness, Quote, SourceKind

log = logging.getLogger(__name__)

REDIS_HASH = "fx:quotes"


class QuoteStore:
    def __init__(
        self,
        redis: Redis | None = None,
        crypto_fresh_seconds: float = 45,
        bank_fresh_seconds: float = 900,
        stale_factor: int = 4,
        redis_flush_seconds: float = 1.0,
    ) -> None:
        self._redis = redis
        self._quotes: dict[str, Quote] = {}
        self._dirty: set[str] = set()
        self._listeners: list[Callable[[Quote], None]] = []
        self._disabled: set[str] = set()
        self._fresh = {SourceKind.EXCHANGE: crypto_fresh_seconds, SourceKind.BANK: bank_fresh_seconds}
        self._stale_factor = stale_factor
        self._flush_seconds = redis_flush_seconds
        self._flush_task: asyncio.Task[None] | None = None

    # ----- запись -----
    def put(self, quote: Quote) -> bool:
        """Сохраняет котировку. Возвращает False, если она отброшена (пустая или старее имеющейся)."""
        if not quote.has_price:
            return False
        previous = self._quotes.get(quote.key)
        if previous is not None and quote.received_at < previous.received_at:
            return False
        quote = quote.with_volume_from(previous)
        self._quotes[quote.key] = quote
        self._dirty.add(quote.key)
        for listener in self._listeners:
            try:
                listener(quote)
            except Exception:
                log.exception("ошибка слушателя котировок")
        return True

    def put_many(self, quotes: Iterable[Quote]) -> int:
        return sum(1 for q in quotes if self.put(q))

    def add_listener(self, listener: Callable[[Quote], None]) -> None:
        self._listeners.append(listener)

    # ----- чтение -----
    def get(self, source: str, symbol: str) -> Quote | None:
        if source in self._disabled:
            return None
        return self._quotes.get(f"{source}|{symbol}")

    def for_symbol(self, symbol: str, include_disabled: bool = False) -> list[Quote]:
        return [
            q
            for q in self._quotes.values()
            if q.symbol == symbol and (include_disabled or q.source not in self._disabled)
        ]

    def for_source(self, source: str) -> list[Quote]:
        return [q for q in self._quotes.values() if q.source == source]

    def all(self) -> list[Quote]:
        return [q for q in self._quotes.values() if q.source not in self._disabled]

    def freshness(self, quote: Quote) -> Freshness:
        return quote.freshness(self._fresh[quote.kind], self._stale_factor)

    def fresh_seconds(self, kind: SourceKind) -> float:
        return self._fresh[kind]

    def usable(self, quotes: Iterable[Quote]) -> list[Quote]:
        """Только свежие котировки — для сравнений, арбитража и уведомлений."""
        return [q for q in quotes if self.freshness(q) is Freshness.FRESH]

    def set_disabled(self, sources: Iterable[str]) -> None:
        self._disabled = set(sources)

    # ----- Redis -----
    async def warm_from_redis(self) -> int:
        if self._redis is None:
            return 0
        try:
            raw = await self._redis.hgetall(REDIS_HASH)  # type: ignore[misc]
        except Exception as exc:
            log.error("Не удалось прочитать кеш из Redis: %s", exc)
            return 0
        loaded = 0
        for key, payload in raw.items():
            try:
                quote = Quote.model_validate_json(payload)
            except ValueError:
                continue
            self._quotes.setdefault(key, quote)  # без listeners: это старые данные, они не должны попадать в историю
            loaded += 1
        log.info("Из Redis загружено котировок: %d", loaded)
        return loaded

    def start(self) -> None:
        if self._redis is not None and self._flush_task is None:
            self._flush_task = asyncio.create_task(self._flush_loop(), name="store-redis-flush")

    async def stop(self) -> None:
        if self._flush_task is not None:
            self._flush_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flush_task
            self._flush_task = None
        await self.flush()

    async def flush(self) -> None:
        if self._redis is None or not self._dirty:
            return
        keys, self._dirty = self._dirty, set()
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.hset(REDIS_HASH, key, self._quotes[key].model_dump_json())
                await pipe.execute()
        except Exception as exc:
            self._dirty |= keys
            log.error("Запись в Redis не удалась: %s", exc)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self._flush_seconds)
            await self.flush()
