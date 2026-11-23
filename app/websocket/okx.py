"""OKX v5 public WebSocket, канал ``tickers``.

Порт 8443 выводится из эксплуатации (уведомление сервера), используется стандартный 443.
Keep-alive: текстовое сообщение ``ping`` -> ответ ``pong`` (сервер закрывает соединение после 30 с тишины).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.utils.http import HttpClient
from app.utils.symbols import native_map, to_decimal
from app.websocket.base import BaseStream, StreamHooks, chunked, ms_to_dt


class OkxStream(BaseStream):
    source = "okx"
    ping_interval = 20.0

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, ws_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._ws_url = ws_url
        self._native = native_map(self.symbols, sep="-")

    async def connect_url(self) -> str:
        return self._ws_url

    def subscribe_messages(self) -> list[Any]:
        args = [{"channel": "tickers", "instId": native} for native in self._native]
        return [{"op": "subscribe", "args": part} for part in chunked(args, 20)]

    def ping_message(self) -> Any:
        return "ping"

    def parse(self, text: str) -> list[Quote]:
        if text == "pong":
            return []
        message = json.loads(text)
        if not isinstance(message, dict):
            return []
        if message.get("event") == "error":
            self.hooks.on_error(f"OKX: {message.get('code')} {message.get('msg')}")
            return []
        if (message.get("arg") or {}).get("channel") != "tickers":
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
                    bid=to_decimal(item.get("bidPx")),
                    ask=to_decimal(item.get("askPx")),
                    bid_size=to_decimal(item.get("bidSz")),
                    ask_size=to_decimal(item.get("askSz")),
                    last=to_decimal(item.get("last")),
                    volume_24h=to_decimal(item.get("vol24h")),
                    quote_volume_24h=to_decimal(item.get("volCcy24h")),
                    source_ts=ms_to_dt(item.get("ts")),
                    received_at=utcnow(),
                )
            )
        return quotes
