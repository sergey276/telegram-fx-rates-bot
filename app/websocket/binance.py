"""Binance: wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/...

Поток ``<symbol>@ticker`` содержит лучшие bid/ask с объёмами, последнюю цену и объём 24ч (обновление ~1 раз/с).
Keep-alive выполняют ping-фреймы сервера, на которые aiohttp отвечает автоматически.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from app.domain import Quote, SourceKind, utcnow
from app.utils.http import HttpClient
from app.utils.symbols import native_map, to_decimal
from app.websocket.base import BaseStream, StreamHooks, ms_to_dt


class BinanceStream(BaseStream):
    source = "binance"

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, ws_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._ws_url = ws_url.rstrip("/")
        self._native = native_map(self.symbols)

    async def connect_url(self) -> str:
        streams = "/".join(f"{native.lower()}@ticker" for native in self._native)
        return f"{self._ws_url}/stream?streams={streams}"

    def parse(self, text: str) -> list[Quote]:
        message = json.loads(text)
        data = message.get("data") if isinstance(message, dict) else None
        if not isinstance(data, dict) or data.get("e") != "24hrTicker":
            return []
        symbol = self._native.get(str(data.get("s", "")).upper())
        if symbol is None:
            return []
        return [
            Quote(
                source=self.source,
                symbol=symbol,
                kind=SourceKind.EXCHANGE,
                bid=to_decimal(data.get("b")),
                ask=to_decimal(data.get("a")),
                bid_size=to_decimal(data.get("B")),
                ask_size=to_decimal(data.get("A")),
                last=to_decimal(data.get("c")),
                volume_24h=to_decimal(data.get("v")),
                quote_volume_24h=to_decimal(data.get("q")),
                source_ts=ms_to_dt(data.get("E")),
                received_at=utcnow(),
            )
        ]
