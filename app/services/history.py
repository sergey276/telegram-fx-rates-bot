"""Агрегация потока котировок в минутные и часовые свечи.

Сообщения WebSocket приходят десятки раз в секунду — в БД они не пишутся. Каждая котировка лишь обновляет
текущую минутную свечу в памяти (O(1)); завершённые свечи сбрасываются в БД пачкой раз в
``history_flush_seconds``. Одновременно строится часовая свеча (для графиков за 7 и 30 дней).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from app.database import Database
from app.database.repositories import Candle, HistoryRepo
from app.domain import Quote, utcnow
from app.services.assets import AssetRegistry

log = logging.getLogger(__name__)

_MAX_PENDING = 20_000  # защита памяти, если БД долго недоступна


def floor_minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


class _Bucket:
    __slots__ = ("ask", "bid", "close", "high", "kind", "low", "open", "samples", "start")

    def __init__(self, start: datetime, price: Decimal, kind: str, bid: Decimal | None, ask: Decimal | None) -> None:
        self.start = start
        self.kind = kind
        self.open = self.high = self.low = self.close = price
        self.bid, self.ask = bid, ask
        self.samples = 1

    def add(self, price: Decimal, kind: str, bid: Decimal | None, ask: Decimal | None) -> None:
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        self.kind = kind
        self.bid, self.ask = bid, ask
        self.samples += 1


class HistoryAggregator:
    def __init__(self, db: Database, assets: AssetRegistry, flush_seconds: float = 30.0) -> None:
        self._db = db
        self._assets = assets
        self._flush_seconds = flush_seconds
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._pending: list[Candle] = []
        self._task: asyncio.Task[None] | None = None

    # ----- приём котировок (синхронно, горячий путь) -----
    def on_quote(self, quote: Quote) -> None:
        if not self._assets.is_tracked(quote.symbol):
            return
        priced = quote.history_price
        if priced is None:
            return
        price, kind = priced
        key = (quote.source, quote.symbol)
        minute = floor_minute(quote.received_at)
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = _Bucket(minute, price, kind, quote.bid, quote.ask)
        elif minute > bucket.start:
            self._close(key, bucket)
            self._buckets[key] = _Bucket(minute, price, kind, quote.bid, quote.ask)
        elif minute == bucket.start:
            bucket.add(price, kind, quote.bid, quote.ask)
        # minute < bucket.start: запоздавшая котировка, не искажаем историю

    def _close(self, key: tuple[str, str], bucket: _Bucket) -> None:
        self._pending.append(
            Candle(
                source=key[0],
                symbol=key[1],
                resolution="1m",
                bucket_start=bucket.start,
                price_kind=bucket.kind,
                open=bucket.open,
                high=bucket.high,
                low=bucket.low,
                close=bucket.close,
                bid=bucket.bid,
                ask=bucket.ask,
                samples=bucket.samples,
            )
        )

    # ----- сброс в БД -----
    async def flush(self, final: bool = False) -> int:
        """Сохраняет завершённые минутные свечи (при ``final`` — и незавершённые) и их часовые агрегаты."""
        current_minute = floor_minute(utcnow())
        for key, bucket in list(self._buckets.items()):
            if final or bucket.start < current_minute:
                self._close(key, bucket)
                del self._buckets[key]
        if not self._pending:
            return 0
        minutes, self._pending = self._pending, []
        candles = [*minutes, *self._hourly(minutes)]
        try:
            async with self._db.session() as session:
                await HistoryRepo(session, self._db.dialect).upsert_candles(candles)
        except Exception:
            log.exception("не удалось сохранить историю цен (%d свечей), повторю позже", len(minutes))
            self._pending = (minutes + self._pending)[-_MAX_PENDING:]
            return 0
        return len(minutes)

    @staticmethod
    def _hourly(minutes: list[Candle]) -> list[Candle]:
        hours: dict[tuple[str, str, datetime], Candle] = {}
        for c in sorted(minutes, key=lambda x: x.bucket_start):
            key = (c.source, c.symbol, floor_hour(c.bucket_start))
            h = hours.get(key)
            if h is None:
                hours[key] = Candle(
                    c.source, c.symbol, "1h", key[2], c.price_kind, c.open, c.high, c.low, c.close, c.bid, c.ask, c.samples
                )
            else:
                h.high, h.low = max(h.high, c.high), min(h.low, c.low)
                h.close, h.bid, h.ask, h.price_kind = c.close, c.bid, c.ask, c.price_kind
                h.samples += c.samples
        return list(hours.values())

    # ----- фоновая задача -----
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="history-flush")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.flush(final=True)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._flush_seconds)
            await self.flush()


def period_to_timedelta(period: str) -> timedelta:
    return {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}[
        period
    ]


def period_resolution(period: str) -> str:
    """1h/24h — минутные свечи, 7d/30d — часовые."""
    return "1m" if period in ("1h", "24h") else "1h"
