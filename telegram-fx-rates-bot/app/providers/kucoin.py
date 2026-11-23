"""KuCoin Spot: level1 стакан (bid/ask + объёмы, last) и /market/stats (объём 24ч)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import GeoBlockedError, ProviderError, RateLimitedError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.kucoin import KucoinStream

log = logging.getLogger(__name__)


def parse_kucoin_level1(payload: Any, symbol: str, stats: Any = None, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"KuCoin: неожиданный ответ ({type(payload).__name__})")
    if str(payload.get("code")) != "200000":
        raise ProviderError(f"KuCoin: code={payload.get('code')} {payload.get('msg')}")
    data = payload.get("data")
    if not data:  # data: null — пары нет на бирже
        return None
    stats_data = stats.get("data") if isinstance(stats, dict) and str(stats.get("code")) == "200000" else None
    stats_data = stats_data or {}
    return Quote(
        source="kucoin",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(data.get("bestBid")),
        ask=to_decimal(data.get("bestAsk")),
        bid_size=to_decimal(data.get("bestBidSize")),
        ask_size=to_decimal(data.get("bestAskSize")),
        last=to_decimal(data.get("price")),
        volume_24h=to_decimal(stats_data.get("vol")),
        quote_volume_24h=to_decimal(stats_data.get("volValue")),
        source_ts=ms_to_dt(data.get("time")),
        received_at=now or utcnow(),
    )


class KucoinProvider(ExchangeProvider):
    name = "kucoin"
    display_name = "KuCoin"

    async def fetch_one(self, symbol: str) -> Quote | None:
        native = to_native(symbol, "-")
        level1 = await self.http.get_json(
            f"{self.rest_url}/api/v1/market/orderbook/level1", params={"symbol": native}, limiter=self.limiter
        )
        if isinstance(level1, dict) and not level1.get("data"):
            return None
        stats: Any = None
        try:
            stats = await self.http.get_json(
                f"{self.rest_url}/api/v1/market/stats", params={"symbol": native}, limiter=self.limiter
            )
        except (RateLimitedError, GeoBlockedError):
            raise
        except ProviderError as exc:  # объём — вспомогательные данные, цены важнее
            log.debug("kucoin stats %s: %s", symbol, exc)
        return parse_kucoin_level1(level1, symbol, stats)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> KucoinStream:
        return KucoinStream(symbols, hooks, self.http, self.rest_url)
