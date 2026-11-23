"""BingX public spot WebSocket.

Все сообщения приходят сжатыми gzip (binary). Сервер периодически шлёт ``Ping`` — нужно ответить ``Pong``.
Лучшие цены даёт ``<SYMBOL>@bookTicker``, последнюю цену — ``<SYMBOL>@lastPrice``; объёма в потоке нет (берётся из REST).
"""

from __future__ import annotations

import gzip
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import aiohttp

from app.domain import Quote, SourceKind, utcnow
from app.utils.http import HttpClient
from app.utils.symbols import native_map, to_decimal
from app.websocket.base import BaseStream, StreamHooks, ms_to_dt


@dataclass(slots=True)
class _State:
    bid: Decimal | None = None
    bid_size: Decimal | None = None
    ask: Decimal | None = None
    ask_size: Decimal | None = None
    last: Decimal | None = None


class BingxStream(BaseStream):
    source = "bingx"

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, ws_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._ws_url = ws_url
        self._native = native_map(self.symbols, sep="-")
        self._state: dict[str, _State] = {}

    async def connect_url(self) -> str:
        self._state = {}
        return self._ws_url

    def subscribe_messages(self) -> list[Any]:
        messages: list[Any] = []
        for native in self._native:
            for channel in ("bookTicker", "lastPrice"):
                messages.append({"id": uuid.uuid4().hex, "reqType": "sub", "dataType": f"{native}@{channel}"})
        return messages

    def decode(self, msg: aiohttp.WSMessage) -> str | None:
        if msg.type == aiohttp.WSMsgType.BINARY:
            try:
                return gzip.decompress(msg.data).decode("utf-8")
            except (OSError, EOFError, UnicodeDecodeError):
                return None
        if msg.type == aiohttp.WSMsgType.TEXT:
            return str(msg.data)
        return None

    async def on_control(self, text: str, ws: aiohttp.ClientWebSocketResponse) -> bool:
        if text == "Ping":
            await ws.send_str("Pong")
            return True
        return False

    def parse(self, text: str) -> list[Quote]:
        message = json.loads(text)
        if not isinstance(message, dict):
            return []
        if message.get("code") not in (0, None):
            self.hooks.on_error(f"BingX: code={message.get('code')} {message.get('msg')}")
            return []
        data = message.get("data")
        if not isinstance(data, dict):
            return []
        symbol = self._native.get(str(data.get("s")))
        if symbol is None:
            return []
        state = self._state.setdefault(symbol, _State())
        event = data.get("e")
        if event == "bookTicker":
            state.bid, state.bid_size = to_decimal(data.get("b")), to_decimal(data.get("B"))
            state.ask, state.ask_size = to_decimal(data.get("a")), to_decimal(data.get("A"))
        elif event == "lastPriceUpdate":
            state.last = to_decimal(data.get("c"))
        else:
            return []
        if state.bid is None or state.ask is None:
            return []
        return [
            Quote(
                source=self.source,
                symbol=symbol,
                kind=SourceKind.EXCHANGE,
                bid=state.bid,
                ask=state.ask,
                bid_size=state.bid_size,
                ask_size=state.ask_size,
                last=state.last,
                source_ts=ms_to_dt(data.get("E")) or ms_to_dt(message.get("timestamp")),
                received_at=utcnow(),
            )
        ]
