"""KuCoin public WebSocket.

Адрес сервера и временный токен выдаёт ``POST /api/v1/bullet-public``; интервал ping задаёт сервер
(``pingInterval``). Топик ``/market/ticker:BTC-USDT,ETH-USDT`` содержит bid/ask с объёмами и последнюю цену,
но не содержит объёма 24ч — он обновляется из REST.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.utils.http import HttpClient, ProviderError
from app.utils.symbols import native_map, to_decimal
from app.websocket.base import BaseStream, StreamHooks, chunked, ms_to_dt

TOPIC_PREFIX = "/market/ticker:"


class KucoinStream(BaseStream):
    source = "kucoin"

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient, rest_url: str) -> None:
        super().__init__(symbols, hooks, http)
        self._rest_url = rest_url.rstrip("/")
        self._native = native_map(self.symbols, sep="-")
        self._ping_ms = 18000

    async def connect_url(self) -> str:
        payload = await self.http.post_json(f"{self._rest_url}/api/v1/bullet-public")
        if not isinstance(payload, dict) or str(payload.get("code")) != "200000":
            raise ProviderError(f"KuCoin bullet-public: {payload}")
        data = payload["data"]
        server = data["instanceServers"][0]
        self._ping_ms = int(server.get("pingInterval", 18000))
        self.ping_interval = max(5.0, self._ping_ms / 1000 * 0.8)
        return f"{server['endpoint']}?token={data['token']}&connectId={uuid.uuid4().hex}"

    def subscribe_messages(self) -> list[Any]:
        return [
            {
                "id": uuid.uuid4().hex,
                "type": "subscribe",
                "topic": TOPIC_PREFIX + ",".join(part),
                "privateChannel": False,
                "response": True,
            }
            for part in chunked(list(self._native), 50)
        ]

    def ping_message(self) -> Any:
        return {"id": uuid.uuid4().hex, "type": "ping"}

    def parse(self, text: str) -> list[Quote]:
        message = json.loads(text)
        if not isinstance(message, dict):
            return []
        if message.get("type") == "error":
            self.hooks.on_error(f"KuCoin: {message.get('code')} {message.get('data')}")
            return []
        if message.get("type") != "message" or message.get("subject") != "trade.ticker":
            return []
        topic = str(message.get("topic", ""))
        symbol = self._native.get(topic.removeprefix(TOPIC_PREFIX))
        data = message.get("data") or {}
        if symbol is None:
            return []
        return [
            Quote(
                source=self.source,
                symbol=symbol,
                kind=SourceKind.EXCHANGE,
                bid=to_decimal(data.get("bestBid")),
                ask=to_decimal(data.get("bestAsk")),
                bid_size=to_decimal(data.get("bestBidSize")),
                ask_size=to_decimal(data.get("bestAskSize")),
                last=to_decimal(data.get("price")),
                source_ts=ms_to_dt(data.get("time")),
                received_at=utcnow(),
            )
        ]
