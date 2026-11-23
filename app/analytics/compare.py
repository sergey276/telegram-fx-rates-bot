"""Сравнение котировок между источниками.

Сравниваются только однородные показатели: для бирж — выбранная метрика (last / bid / ask) всех бирж,
для банков — курс покупки и курс продажи отдельно. Устаревшие котировки показываются с предупреждением,
но не участвуют в расчёте минимума/максимума.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from app.domain import Freshness, Quote

FreshnessFn = Callable[[Quote], Freshness]


class Metric(StrEnum):
    LAST = "last"
    BID = "bid"
    ASK = "ask"

    def value_of(self, quote: Quote) -> Decimal | None:
        return getattr(quote, self.value)


@dataclass(slots=True)
class CompareRow:
    quote: Quote
    value: Decimal
    freshness: Freshness

    @property
    def source(self) -> str:
        return self.quote.source


@dataclass(slots=True)
class Comparison:
    symbol: str
    metric: Metric
    rows: list[CompareRow] = field(default_factory=list)  # по возрастанию значения; без EXPIRED
    expired: list[Quote] = field(default_factory=list)  # котировки без актуальных данных
    without_metric: list[Quote] = field(default_factory=list)  # у источника нет этого показателя

    @property
    def fresh_rows(self) -> list[CompareRow]:
        return [r for r in self.rows if r.freshness is Freshness.FRESH]

    @property
    def lowest(self) -> CompareRow | None:
        fresh = self.fresh_rows
        return fresh[0] if fresh else None

    @property
    def highest(self) -> CompareRow | None:
        fresh = self.fresh_rows
        return fresh[-1] if fresh else None

    @property
    def diff(self) -> Decimal | None:
        if len(self.fresh_rows) < 2:
            return None
        return self.highest.value - self.lowest.value  # type: ignore[union-attr]

    @property
    def diff_pct(self) -> Decimal | None:
        diff = self.diff
        if diff is None or self.lowest is None or self.lowest.value == 0:
            return None
        return diff / self.lowest.value * 100

    @property
    def has_stale(self) -> bool:
        return any(r.freshness is not Freshness.FRESH for r in self.rows) or bool(self.expired)


def compare_exchanges(symbol: str, quotes: Iterable[Quote], metric: Metric, freshness: FreshnessFn) -> Comparison:
    result = Comparison(symbol=symbol, metric=metric)
    for quote in quotes:
        if quote.symbol != symbol:
            continue
        state = freshness(quote)
        value = metric.value_of(quote)
        if state is Freshness.EXPIRED:
            result.expired.append(quote)
        elif value is None:
            result.without_metric.append(quote)
        else:
            result.rows.append(CompareRow(quote, value, state))
    result.rows.sort(key=lambda r: (r.value, r.source))
    return result


@dataclass(slots=True)
class BankComparison:
    symbol: str
    quotes: list[Quote]  # банки с покупкой и продажей, по алфавиту
    cross_only: list[Quote]  # только кросс-курс: покупка/продажа недоступны
    expired: list[Quote]
    freshness: dict[str, Freshness]

    def _fresh(self) -> list[Quote]:
        return [q for q in self.quotes if self.freshness[q.source] is Freshness.FRESH]

    @property
    def best_for_selling(self) -> Quote | None:
        """Где клиенту выгоднее ПРОДАТЬ валюту банку: максимальный курс покупки банка."""
        candidates = [q for q in self._fresh() if q.bid is not None]
        return max(candidates, key=lambda q: q.bid, default=None)  # type: ignore[arg-type,return-value]

    @property
    def best_for_buying(self) -> Quote | None:
        """Где клиенту выгоднее КУПИТЬ валюту у банка: минимальный курс продажи банка."""
        candidates = [q for q in self._fresh() if q.ask is not None]
        return min(candidates, key=lambda q: q.ask, default=None)  # type: ignore[arg-type,return-value]

    @property
    def buy_diff(self) -> Decimal | None:
        values = [q.bid for q in self._fresh() if q.bid is not None]
        return max(values) - min(values) if len(values) >= 2 else None

    @property
    def sell_diff(self) -> Decimal | None:
        values = [q.ask for q in self._fresh() if q.ask is not None]
        return max(values) - min(values) if len(values) >= 2 else None


def compare_banks(symbol: str, quotes: Iterable[Quote], freshness: FreshnessFn) -> BankComparison:
    with_rates: list[Quote] = []
    cross_only: list[Quote] = []
    expired: list[Quote] = []
    states: dict[str, Freshness] = {}
    for quote in quotes:
        if quote.symbol != symbol:
            continue
        states[quote.source] = freshness(quote)
        if states[quote.source] is Freshness.EXPIRED:
            expired.append(quote)
        elif quote.bid is None and quote.ask is None:
            cross_only.append(quote)
        else:
            with_rates.append(quote)
    with_rates.sort(key=lambda q: q.source)
    return BankComparison(symbol, with_rates, cross_only, expired, states)
