"""Bitget v2 public WebSocket, канал ``ticker`` (instType=SPOT).

Keep-alive: текстовое ``ping`` каждые 30 с -> ответ ``pong``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.utils.http import HttpClient
from app.utils.symbols import native_map, to_decimal
from app.websocket.base import BaseStream, StreamHooks, chunked, ms_to_dt


class BitgetStream(BaseStream):
    source = "bitget"
    ping_interval = 25.0

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, ws_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._ws_url = ws_url
        self._native = native_map(self.symbols)

    async def connect_url(self) -> str:
        return self._ws_url

    def subscribe_messages(self) -> list[Any]:
        args = [{"instType": "SPOT", "channel": "ticker", "instId": native} for native in self._native]
        return [{"op": "subscribe", "args": part} for part in chunked(args, 50)]

    def ping_message(self) -> Any:
        return "ping"

    def parse(self, text: str) -> list[Quote]:
        if text == "pong":
            return []
        message = json.loads(text)
        if not isinstance(message, dict):
            return []
        if message.get("event") == "error":
            self.hooks.on_error(f"Bitget: {message.get('code')} {message.get('msg')}")
            return []
        if (message.get("arg") or {}).get("channel") != "ticker":
            return []
        quotes: list[Quote] = []
        for item in message.get("data") or []:
            symbol = self._native.get(str(item.get("instId")))
            if symbol is None:
                continue
            quotes.append(
                Quote(
                    source=self.source,
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
                    received_at=utcnow(),
                )
            )
        return quotes
