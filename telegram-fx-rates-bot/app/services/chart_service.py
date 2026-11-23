"""Сборка данных для графика из истории цен и текущей котировки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.charts import ChartPoint, ChartRequest, compute_stats, render_chart_async
from app.charts.generator import ChartStats
from app.database import Database
from app.database.repositories import HistoryRepo
from app.domain import EXCHANGE_ORDER, Freshness, SourceKind, source_name, utcnow
from app.services.history import period_resolution, period_to_timedelta
from app.services.quotes import QuoteService

PERIODS = ("1h", "24h", "7d", "30d")
BANK_ORDER = ("monobank", "privatbank")
_MIN_POINTS = 2


@dataclass(slots=True)
class ChartResult:
    png: bytes
    stats: ChartStats
    covered: timedelta  # за какой отрезок периода реально есть данные
    requested: timedelta


class ChartService:
    def __init__(self, db: Database, quotes: QuoteService) -> None:
        self._db = db
        self._quotes = quotes

    async def sources_for(self, symbol: str) -> list[str]:
        async with self._db.session() as session:
            stored = await HistoryRepo(session, self._db.dialect).sources_for(symbol)
        enabled = [s for s in stored if self._quotes.health.is_enabled(s)]
        order = {name: i for i, name in enumerate((*EXCHANGE_ORDER, *BANK_ORDER))}
        return sorted(enabled, key=lambda s: order.get(s, 99))

    async def build(self, symbol: str, source: str, period: str, theme: str, lang: str, tz: str) -> ChartResult | None:
        """``None`` — данных для графика недостаточно."""
        requested = period_to_timedelta(period)
        since = utcnow() - requested
        async with self._db.session() as session:
            rows = await HistoryRepo(session, self._db.dialect).series(
                source, symbol, period_resolution(period), since
            )
        if len(rows) < _MIN_POINTS:
            return None
        is_bank = rows[-1].price_kind in ("mid", "cross") and (rows[-1].bid is not None or rows[-1].ask is not None)
        points = [ChartPoint(r.bucket_start, r.low, r.high, r.close, r.bid, r.ask) for r in rows]

        quote = self._quotes.store.get(source, symbol)
        current = None
        if quote is not None and self._quotes.freshness(quote) is Freshness.FRESH:
            if quote.kind is SourceKind.BANK:
                current = quote.mid or quote.cross_rate
            else:
                current = quote.last or quote.mid
        request = ChartRequest(
            symbol=symbol,
            source_name=source_name(source),
            period=period,
            points=points,
            price_kind=rows[-1].price_kind,
            current=current,
            is_bank=is_bank,
            theme=theme,
            lang=lang,
            tz=tz,
        )
        stats = compute_stats(request)
        assert stats is not None
        png = await render_chart_async(request)
        return ChartResult(png, stats, rows[-1].bucket_start - rows[0].bucket_start, requested)
