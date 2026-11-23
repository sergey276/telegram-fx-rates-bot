"""Единая модель котировки.

Банковский курс, последняя цена сделки и лучшие цены стакана — разные показатели, поэтому они
хранятся в разных полях и никогда не подменяют друг друга:

* ``bid``  — лучшая цена покупки (у банка: курс, по которому банк *покупает* валюту у клиента);
* ``ask``  — лучшая цена продажи (у банка: курс, по которому банк *продаёт* валюту клиенту);
* ``last`` — цена последней сделки (только у бирж);
* ``cross_rate`` — кросс-курс (только у банков, если нет покупки/продажи).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class SourceKind(StrEnum):
    BANK = "bank"
    EXCHANGE = "exchange"


class Freshness(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


def utcnow() -> datetime:
    return datetime.now(UTC)


class Quote(BaseModel):
    """Нормализованная котировка одного источника по одной паре (``BTC/USDT``, ``USD/UAH``)."""

    model_config = ConfigDict(frozen=True)

    source: str
    symbol: str
    kind: SourceKind
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    cross_rate: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    volume_24h: Decimal | None = None
    quote_volume_24h: Decimal | None = None
    source_ts: datetime | None = None
    received_at: datetime

    @field_validator("bid", "ask", "last", "cross_rate", mode="after")
    @classmethod
    def _positive_price(cls, value: Decimal | None) -> Decimal | None:
        # Биржи отдают 0 для пустого стакана / неторгуемой пары — это «нет данных», а не цена.
        if value is None or not value.is_finite() or value <= 0:
            return None
        return value

    @field_validator("bid_size", "ask_size", "volume_24h", "quote_volume_24h", mode="after")
    @classmethod
    def _non_negative(cls, value: Decimal | None) -> Decimal | None:
        if value is None or not value.is_finite() or value < 0:
            return None
        return value

    @field_validator("source_ts", "received_at", mode="after")
    @classmethod
    def _aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @property
    def key(self) -> str:
        return f"{self.source}|{self.symbol}"

    @property
    def has_price(self) -> bool:
        return any(v is not None for v in (self.bid, self.ask, self.last, self.cross_rate))

    @property
    def mid(self) -> Decimal | None:
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return None

    @property
    def spread(self) -> Decimal | None:
        if self.bid is not None and self.ask is not None:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> Decimal | None:
        mid = self.mid
        spread = self.spread
        if mid is None or spread is None or mid == 0:
            return None
        return spread / mid * 100

    @property
    def history_price(self) -> tuple[Decimal, str] | None:
        """Цена для графиков и (цена, вид): ``last`` у бирж, середина bid/ask у банков."""
        if self.kind is SourceKind.EXCHANGE:
            if self.last is not None:
                return self.last, "last"
            if self.mid is not None:
                return self.mid, "mid"
            return None
        if self.mid is not None:
            return self.mid, "mid"
        if self.cross_rate is not None:
            return self.cross_rate, "cross"
        return None

    def age_seconds(self, now: datetime | None = None) -> float:
        return max(0.0, ((now or utcnow()) - self.received_at).total_seconds())

    def freshness(self, fresh_seconds: float, stale_factor: int = 4, now: datetime | None = None) -> Freshness:
        age = self.age_seconds(now)
        if age <= fresh_seconds:
            return Freshness.FRESH
        if age <= fresh_seconds * stale_factor:
            return Freshness.STALE
        return Freshness.EXPIRED

    def missing_fields(self) -> list[str]:
        """Какие показатели источник не предоставил (для явного сообщения пользователю)."""
        if self.kind is SourceKind.BANK:
            expected = {"bid": self.bid, "ask": self.ask, "source_ts": self.source_ts}
        else:
            expected = {
                "bid": self.bid,
                "ask": self.ask,
                "last": self.last,
                "volume_24h": self.volume_24h,
                "source_ts": self.source_ts,
            }
        return [name for name, value in expected.items() if value is None]

    def with_volume_from(self, previous: Quote | None) -> Quote:
        """Переносит медленно меняющийся объём 24ч из предыдущей котировки (цены никогда не переносятся)."""
        if previous is None or self.volume_24h is not None:
            return self
        if previous.volume_24h is None and previous.quote_volume_24h is None:
            return self
        return self.model_copy(
            update={
                "volume_24h": previous.volume_24h,
                "quote_volume_24h": self.quote_volume_24h or previous.quote_volume_24h,
            }
        )


SOURCE_NAMES = {
    "monobank": "Monobank",
    "privatbank": "PrivatBank",
    "binance": "Binance",
    "bybit": "Bybit",
    "okx": "OKX",
    "bitget": "Bitget",
    "bingx": "BingX",
    "kucoin": "KuCoin",
}
EXCHANGE_ORDER = ("binance", "bybit", "okx", "bitget", "bingx", "kucoin")


def source_name(source: str) -> str:
    return SOURCE_NAMES.get(source, source)
