"""Binance Spot: GET /api/v3/ticker/24hr?symbol=BTCUSDT (bid/ask + qty, last, объём 24ч)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import ProviderError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.binance import BinanceStream

INVALID_SYMBOL_CODE = -1121


def parse_binance_ticker(payload: Any, symbol: str, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"Binance: неожиданный ответ ({type(payload).__name__})")
    if payload.get("code") == INVALID_SYMBOL_CODE:
        return None
    if "code" in payload and "lastPrice" not in payload:
        raise ProviderError(f"Binance: {payload.get('code')} {payload.get('msg')}")
    return Quote(
        source="binance",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(payload.get("bidPrice")),
        ask=to_decimal(payload.get("askPrice")),
        bid_size=to_decimal(payload.get("bidQty")),
        ask_size=to_decimal(payload.get("askQty")),
        last=to_decimal(payload.get("lastPrice")),
        volume_24h=to_decimal(payload.get("volume")),
        quote_volume_24h=to_decimal(payload.get("quoteVolume")),
        source_ts=ms_to_dt(payload.get("closeTime")),
        received_at=now or utcnow(),
    )


class BinanceProvider(ExchangeProvider):
    name = "binance"
    display_name = "Binance"

    async def fetch_one(self, symbol: str) -> Quote | None:
        payload = await self.http.get_json(
            f"{self.rest_url}/api/v3/ticker/24hr", params={"symbol": to_native(symbol)}, limiter=self.limiter
        )
        return parse_binance_ticker(payload, symbol)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> BinanceStream:
        return BinanceStream(symbols, hooks, self.http, self.ws_url)
