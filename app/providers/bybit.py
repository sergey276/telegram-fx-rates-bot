"""Bybit v5 Spot: GET /v5/market/tickers?category=spot&symbol=BTCUSDT."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import ProviderError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.bybit import BybitStream

NOT_SUPPORTED_SYMBOL = 10001


def parse_bybit_ticker(payload: Any, symbol: str, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"Bybit: неожиданный ответ ({type(payload).__name__})")
    ret_code = payload.get("retCode")
    if ret_code == NOT_SUPPORTED_SYMBOL:
        return None
    if ret_code != 0:
        raise ProviderError(f"Bybit: retCode={ret_code} {payload.get('retMsg')}")
    items = (payload.get("result") or {}).get("list") or []
    if not items:
        return None
    item = items[0]
    return Quote(
        source="bybit",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(item.get("bid1Price")),
        ask=to_decimal(item.get("ask1Price")),
        bid_size=to_decimal(item.get("bid1Size")),
        ask_size=to_decimal(item.get("ask1Size")),
        last=to_decimal(item.get("lastPrice")),
        volume_24h=to_decimal(item.get("volume24h")),
        quote_volume_24h=to_decimal(item.get("turnover24h")),
        source_ts=ms_to_dt(payload.get("time")),
        received_at=now or utcnow(),
    )


class BybitProvider(ExchangeProvider):
    name = "bybit"
    display_name = "Bybit"

    async def fetch_one(self, symbol: str) -> Quote | None:
        payload = await self.http.get_json(
            f"{self.rest_url}/v5/market/tickers",
            params={"category": "spot", "symbol": to_native(symbol)},
            limiter=self.limiter,
        )
        return parse_bybit_ticker(payload, symbol)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> BybitStream:
        return BybitStream(symbols, hooks, self.http, self.ws_url)
