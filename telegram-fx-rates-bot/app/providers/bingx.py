"""BingX Spot: GET /openApi/spot/v1/ticker/24hr?symbol=BTC-USDT&timestamp=<ms>."""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import ProviderError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.bingx import BingxStream

SYMBOL_NOT_FOUND = 100204


def parse_bingx_ticker(payload: Any, symbol: str, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"BingX: неожиданный ответ ({type(payload).__name__})")
    code = payload.get("code")
    if code == SYMBOL_NOT_FOUND:
        return None
    if code != 0:
        raise ProviderError(f"BingX: code={code} {payload.get('msg')}")
    items = payload.get("data") or []
    if not items:
        return None
    item = items[0]
    return Quote(
        source="bingx",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(item.get("bidPrice")),
        ask=to_decimal(item.get("askPrice")),
        bid_size=to_decimal(item.get("bidQty")),
        ask_size=to_decimal(item.get("askQty")),
        last=to_decimal(item.get("lastPrice")),
        volume_24h=to_decimal(item.get("volume")),
        quote_volume_24h=to_decimal(item.get("quoteVolume")),
        source_ts=ms_to_dt(item.get("closeTime")),
        received_at=now or utcnow(),
    )


class BingxProvider(ExchangeProvider):
    name = "bingx"
    display_name = "BingX"

    async def fetch_one(self, symbol: str) -> Quote | None:
        payload = await self.http.get_json(
            f"{self.rest_url}/openApi/spot/v1/ticker/24hr",
            params={"symbol": to_native(symbol, "-"), "timestamp": int(time.time() * 1000)},
            limiter=self.limiter,
        )
        return parse_bingx_ticker(payload, symbol)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> BingxStream:
        return BingxStream(symbols, hooks, self.http, self.ws_url)
