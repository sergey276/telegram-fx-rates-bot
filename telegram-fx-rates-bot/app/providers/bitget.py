"""Bitget v2 Spot: GET /api/v2/spot/market/tickers?symbol=BTCUSDT."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import ExchangeProvider
from app.utils.http import ProviderError
from app.utils.symbols import to_decimal, to_native
from app.websocket.base import StreamHooks, ms_to_dt
from app.websocket.bitget import BitgetStream

SYMBOL_NOT_EXIST = "40034"


def parse_bitget_ticker(payload: Any, symbol: str, now: datetime | None = None) -> Quote | None:
    if not isinstance(payload, dict):
        raise ProviderError(f"Bitget: неожиданный ответ ({type(payload).__name__})")
    code = str(payload.get("code"))
    if code == SYMBOL_NOT_EXIST:
        return None
    if code != "00000":
        raise ProviderError(f"Bitget: code={code} {payload.get('msg')}")
    items = payload.get("data") or []
    if not items:
        return None
    item = items[0]
    return Quote(
        source="bitget",
        symbol=symbol,
        kind=SourceKind.EXCHANGE,
        bid=to_decimal(item.get("bidPr")),
        ask=to_decimal(item.get("askPr")),
        bid_size=to_decimal(item.get("bidSz")),
        ask_size=to_decimal(item.get("askSz")),
        last=to_decimal(item.get("lastPr")),
        volume_24h=to_decimal(item.get("baseVolume")),
        quote_volume_24h=to_decimal(item.get("quoteVolume")),
        source_ts=ms_to_dt(item.get("ts")),
        received_at=now or utcnow(),
    )


class BitgetProvider(ExchangeProvider):
    name = "bitget"
    display_name = "Bitget"

    async def fetch_one(self, symbol: str) -> Quote | None:
        payload = await self.http.get_json(
            f"{self.rest_url}/api/v2/spot/market/tickers", params={"symbol": to_native(symbol)}, limiter=self.limiter
        )
        return parse_bitget_ticker(payload, symbol)

    @property
    def supports_stream(self) -> bool:
        return True

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> BitgetStream:
        return BitgetStream(symbols, hooks, self.http, self.ws_url)
