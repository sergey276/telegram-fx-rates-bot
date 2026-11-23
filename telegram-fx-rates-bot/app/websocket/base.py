"""Базовый WebSocket-поток с автоматическим переподключением.

Подкласс описывает только протокол биржи: URL, сообщения подписки, keep-alive и разбор сообщений.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import aiohttp

from app.domain import Quote
from app.utils.http import HttpClient

log = logging.getLogger(__name__)


def noop(*_args: Any) -> None:
    return None


@dataclass(slots=True)
class StreamHooks:
    """Колбэки, через которые поток сообщает о событиях сборщику данных."""

    on_quote: Callable[[Quote], None] = noop
    on_connected: Callable[[], None] = noop
    on_disconnected: Callable[[str], None] = noop
    on_error: Callable[[str], None] = noop


def ms_to_dt(value: Any) -> datetime | None:
    try:
        ms = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC) if ms > 0 else None


def chunked(items: Sequence[Any], size: int) -> list[list[Any]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


@dataclass(slots=True)
class _Backoff:
    base: float = 1.0
    maximum: float = 60.0
    current: float = field(default=1.0)

    def next_delay(self) -> float:
        delay = self.current * random.uniform(0.8, 1.2)
        self.current = min(self.current * 2, self.maximum)
        return delay

    def reset(self) -> None:
        self.current = self.base


class BaseStream(ABC):
    source: str
    ping_interval: float | None = None  # прикладной ping (если протокол биржи его требует)
    idle_timeout: float = 90.0  # нет ни одного сообщения дольше — соединение считается зависшим
    stable_after: float = 60.0  # соединение дольше этого времени считается стабильным (сброс backoff)

    def __init__(self, symbols: Sequence[str], hooks: StreamHooks, http: HttpClient) -> None:
        self.symbols = list(symbols)
        self.hooks = hooks
        self.http = http
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    # ----- протокол биржи -----
    @abstractmethod
    async def connect_url(self) -> str: ...

    def subscribe_messages(self) -> list[Any]:
        """Сообщения подписки (dict/list -> JSON, str отправляется как есть)."""
        return []

    def ping_message(self) -> Any | None:
        return None

    @abstractmethod
    def parse(self, text: str) -> list[Quote]:
        """Разбирает сообщение. Служебные сообщения (pong, ack) должны давать пустой список."""

    def decode(self, msg: aiohttp.WSMessage) -> str | None:
        if msg.type == aiohttp.WSMsgType.TEXT:
            return str(msg.data)
        return None

    async def on_control(self, text: str, ws: aiohttp.ClientWebSocketResponse) -> bool:
        """Позволяет ответить на служебное сообщение (например, ``Ping`` -> ``Pong``). True — сообщение обработано."""
        return False

    # ----- жизненный цикл -----
    def start(self) -> asyncio.Task[None]:
        self._stopping = False
        self._task = asyncio.create_task(self.run(), name=f"ws-{self.source}")
        return self._task

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def run(self) -> None:
        backoff = _Backoff()
        loop = asyncio.get_running_loop()
        while not self._stopping:
            connected_at: float | None = None
            reason = "соединение закрыто"
            try:
                url = await self.connect_url()
                async with self.http.session.ws_connect(url, heartbeat=None, max_msg_size=0) as ws:
                    for message in self.subscribe_messages():
                        await ws.send_str(message if isinstance(message, str) else json.dumps(message))
                    connected_at = loop.time()
                    self.hooks.on_connected()
                    log.info("%s: WebSocket подключён (%d пар)", self.source, len(self.symbols))
                    await self._read_loop(ws)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                reason = f"{type(exc).__name__}: {exc}"
                log.warning("%s: ошибка WebSocket: %s", self.source, reason)
                self.hooks.on_error(reason)
            self.hooks.on_disconnected(reason)
            if connected_at is not None and loop.time() - connected_at >= self.stable_after:
                backoff.reset()
            delay = backoff.next_delay()
            log.info("%s: переподключение через %.1f с", self.source, delay)
            await asyncio.sleep(delay)

    async def _read_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        pinger = asyncio.create_task(self._ping_loop(ws)) if self.ping_interval else None
        try:
            while True:
                try:
                    msg = await ws.receive(timeout=self.idle_timeout)
                except TimeoutError:
                    raise ConnectionError(f"нет данных {self.idle_timeout:.0f} с") from None
                if msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.CLOSED):
                    raise ConnectionError(f"сервер закрыл соединение (код {ws.close_code})")
                if msg.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(f"ошибка сокета: {ws.exception()}")
                text = self.decode(msg)
                if text is None:
                    continue
                if await self.on_control(text, ws):
                    continue
                try:
                    quotes = self.parse(text)
                except Exception:  # одно битое сообщение не должно ронять соединение
                    log.exception("%s: не удалось разобрать сообщение: %.200s", self.source, text)
                    continue
                for quote in quotes:
                    self.hooks.on_quote(quote)
        finally:
            if pinger is not None:
                pinger.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pinger

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        assert self.ping_interval is not None
        while not ws.closed:
            await asyncio.sleep(self.ping_interval)
            message = self.ping_message()
            if message is None:
                continue
            await ws.send_str(message if isinstance(message, str) else json.dumps(message))
