"""Bybit v5 public spot WebSocket.

Топик ``tickers.<SYMBOL>`` в споте НЕ содержит bid/ask (проверено на живом соединении), поэтому лучшие цены
берутся из ``orderbook.1.<SYMBOL>``, а последняя цена и объём — из ``tickers``. Состояние по паре объединяется.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

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
    volume: Decimal | None = None
    quote_volume: Decimal | None = None


class BybitStream(BaseStream):
    source = "bybit"
    ping_interval = 20.0

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, ws_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._ws_url = ws_url
        self._native = native_map(self.symbols)
        self._state: dict[str, _State] = {}

    async def connect_url(self) -> str:
        self._state = {}  # после переподключения старые bid/ask недействительны
        return self._ws_url

    def subscribe_messages(self) -> list[Any]:
        # Одна пара — один запрос: Bybit отклоняет весь запрос, если в нём есть неизвестный символ.
        return [
            {"op": "subscribe", "args": [f"tickers.{native}", f"orderbook.1.{native}"]} for native in self._native
        ]

    def ping_message(self) -> Any:
        return {"op": "ping"}

    def parse(self, text: str) -> list[Quote]:
        message = json.loads(text)
        if isinstance(message, dict) and message.get("success") is False:
            self.hooks.on_error(f"Bybit: {message.get('op')} отклонён: {message.get('ret_msg')}")
            return []
        topic = message.get("topic") if isinstance(message, dict) else None
        data = message.get("data") if isinstance(message, dict) else None
        if not topic or not isinstance(data, dict):
            return []
        if topic.startswith("tickers."):
            native = data.get("symbol")
            state = self._state.setdefault(str(native), _State())
            state.last = to_decimal(data.get("lastPrice")) or state.last
            state.volume = to_decimal(data.get("volume24h")) or state.volume
            state.quote_volume = to_decimal(data.get("turnover24h")) or state.quote_volume
        elif topic.startswith("orderbook.1."):
            native = data.get("s")
            state = self._state.setdefault(str(native), _State())
            self._apply_book(state, data, snapshot=message.get("type") == "snapshot")
        else:
            return []
        symbol = self._native.get(str(native))
        if symbol is None or state.bid is None or state.ask is None:
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
                volume_24h=state.volume,
                quote_volume_24h=state.quote_volume,
                source_ts=ms_to_dt(message.get("ts")),
                received_at=utcnow(),
            )
        ]

    @staticmethod
    def _apply_book(state: _State, data: dict[str, Any], snapshot: bool) -> None:
        if snapshot:
            state.bid = state.bid_size = state.ask = state.ask_size = None
        for side, price_attr, size_attr in (("b", "bid", "bid_size"), ("a", "ask", "ask_size")):
            levels = data.get(side) or []
            if not levels:
                continue
            price, size = to_decimal(levels[0][0]), to_decimal(levels[0][1])
            if size is None or size == 0:  # уровень удалён — ждём следующий снимок
                setattr(state, price_attr, None)
                setattr(state, size_attr, None)
            else:
                setattr(state, price_attr, price)
                setattr(state, size_attr, size)
