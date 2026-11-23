"""OKX v5: GET /api/v5/market/ticker?instId=BTC-USDT."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import ProviderError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.okx import OkxStream

INSTRUMENT_NOT_FOUND = "51001"


def parse_okx_ticker(payload: Any, symbol: str, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"OKX: неожиданный ответ ({type(payload).__name__})")
    code = str(payload.get("code"))
    if code == INSTRUMENT_NOT_FOUND:
        return None
    if code != "0":
        raise ProviderError(f"OKX: code={code} {payload.get('msg')}")
    items = payload.get("data") or []
    if not items:
        return None
    item = items[0]
    return Quote(
        source="okx",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(item.get("bidPx")),
        ask=to_decimal(item.get("askPx")),
        bid_size=to_decimal(item.get("bidSz")),
        ask_size=to_decimal(item.get("askSz")),
        last=to_decimal(item.get("last")),
        volume_24h=to_decimal(item.get("vol24h")),
        quote_volume_24h=to_decimal(item.get("volCcy24h")),
        source_ts=ms_to_dt(item.get("ts")),
        received_at=now or utcnow(),
    )


class OkxProvider(ExchangeProvider):
    name = "okx"
    display_name = "OKX"

    async def fetch_one(self, symbol: str) -> Quote | None:
        payload = await self.http.get_json(
            f"{self.rest_url}/api/v5/market/ticker", params={"instId": to_native(symbol, "-")}, limiter=self.limiter
        )
        return parse_okx_ticker(payload, symbol)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> OkxStream:
        return OkxStream(symbols, hooks, self.http, self.ws_url)
