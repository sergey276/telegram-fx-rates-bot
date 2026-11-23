"""HTTP-клиент и переподключение WebSocket — на настоящих локальных серверах."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from decimal import Decimal

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.domain import Quote, SourceKind
from app.utils.http import (
    AsyncRateLimiter,
    GeoBlockedError,
    HttpClient,
    ProviderError,
    RateLimitedError,
)
from app.websocket import base as ws_base
from app.websocket.base import BaseStream, StreamHooks


@pytest.fixture
async def server_factory():
    servers: list[TestServer] = []

    async def make(app: web.Application) -> TestServer:
        server = TestServer(app)
        await server.start_server()
        servers.append(server)
        return server

    yield make
    for server in servers:
        await server.close()


# --------------------------------------------------------------------------- HTTP
async def test_http_ok_and_json_error_body_on_4xx(server_factory):
    async def ok(_r):
        return web.json_response({"a": 1})

    async def binance_like(_r):
        return web.json_response({"code": -1121, "msg": "Invalid symbol."}, status=400)

    app = web.Application()
    app.add_routes([web.get("/ok", ok), web.get("/bad", binance_like)])
    server = await server_factory(app)
    http = HttpClient(timeout=5)
    try:
        assert await http.get_json(str(server.make_url("/ok"))) == {"a": 1}
        # тело ошибки биржи отдаётся вызывающему коду (он решает, что это «пара не найдена»)
        assert await http.get_json(str(server.make_url("/bad"))) == {"code": -1121, "msg": "Invalid symbol."}
    finally:
        await http.close()


async def test_http_429_raises_rate_limited_with_retry_after(server_factory):
    async def limited(_r):
        return web.Response(status=429, headers={"Retry-After": "42"})

    app = web.Application()
    app.add_routes([web.get("/x", limited)])
    server = await server_factory(app)
    http = HttpClient(timeout=5)
    try:
        with pytest.raises(RateLimitedError) as exc:
            await http.get_json(str(server.make_url("/x")))
        assert exc.value.retry_after == 42
    finally:
        await http.close()


@pytest.mark.parametrize("status", [403, 451])
async def test_http_geo_block_is_a_distinct_error(server_factory, status):
    async def blocked(_r):
        return web.Response(status=status)

    app = web.Application()
    app.add_routes([web.get("/x", blocked)])
    server = await server_factory(app)
    http = HttpClient(timeout=5)
    try:
        with pytest.raises(GeoBlockedError):
            await http.get_json(str(server.make_url("/x")))
    finally:
        await http.close()


async def test_http_retries_5xx_then_succeeds(server_factory):
    calls = {"n": 0}

    async def flaky(_r):
        calls["n"] += 1
        if calls["n"] < 3:
            return web.Response(status=503)
        return web.json_response({"ok": True})

    app = web.Application()
    app.add_routes([web.get("/x", flaky)])
    server = await server_factory(app)
    http = HttpClient(timeout=5, retries=2)
    try:
        assert await http.get_json(str(server.make_url("/x"))) == {"ok": True}
        assert calls["n"] == 3
    finally:
        await http.close()


async def test_http_gives_up_after_retries_with_provider_error(server_factory):
    async def down(_r):
        return web.Response(status=500)

    app = web.Application()
    app.add_routes([web.get("/x", down)])
    server = await server_factory(app)
    http = HttpClient(timeout=5, retries=1)
    try:
        with pytest.raises(ProviderError, match="500"):
            await http.get_json(str(server.make_url("/x")))
    finally:
        await http.close()


async def test_http_timeout_and_connection_refused_become_provider_error(server_factory):
    async def slow(_r):
        await asyncio.sleep(3)
        return web.json_response({})

    app = web.Application()
    app.add_routes([web.get("/slow", slow)])
    server = await server_factory(app)
    http = HttpClient(timeout=0.3, retries=0)
    try:
        with pytest.raises(ProviderError):
            await http.get_json(str(server.make_url("/slow")))
        with pytest.raises(ProviderError):
            await http.get_json("http://127.0.0.1:1/never")
    finally:
        await http.close()


async def test_http_invalid_json_is_provider_error(server_factory):
    async def html(_r):
        return web.Response(text="<html>maintenance</html>", content_type="text/html")

    app = web.Application()
    app.add_routes([web.get("/x", html)])
    server = await server_factory(app)
    http = HttpClient(timeout=5, retries=0)
    try:
        with pytest.raises(ProviderError):
            await http.get_json(str(server.make_url("/x")))
    finally:
        await http.close()


async def test_rate_limiter_spaces_requests():
    limiter = AsyncRateLimiter(rate=20, burst=1)  # не чаще 20 запросов/с
    started = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.monotonic() - started
    assert elapsed >= 0.18  # 4 интервала по 0.05 с


async def test_rate_limiter_burst_is_immediate():
    limiter = AsyncRateLimiter(rate=1, burst=5)
    started = time.monotonic()
    for _ in range(5):
        await limiter.acquire()
    assert time.monotonic() - started < 0.2


# --------------------------------------------------------------------------- WebSocket
class EchoStream(BaseStream):
    """Минимальный поток для проверки общей логики: сообщение {"p": цена} -> котировка."""

    source = "fake"
    ping_interval = 0.15

    def __init__(self, url: str, hooks: StreamHooks, http: HttpClient, idle_timeout: float = 5.0):
        super().__init__(["BTC/USDT"], hooks, http)
        self._url = url
        self.idle_timeout = idle_timeout

    async def connect_url(self) -> str:
        return self._url

    def subscribe_messages(self):
        return [{"op": "subscribe", "args": ["x"]}]

    def ping_message(self):
        return "ping"

    def parse(self, text: str):
        if text == "pong":
            return []
        data = json.loads(text)
        if "bad" in data:
            raise ValueError("boom")  # битое сообщение не должно ронять соединение
        return [Quote(source="fake", symbol="BTC/USDT", kind=SourceKind.EXCHANGE, bid=Decimal(data["p"]),
                      ask=Decimal(data["p"]) + 1, received_at=datetime.now(UTC))]


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch):
    monkeypatch.setattr(ws_base._Backoff, "next_delay", lambda self: 0.05)


async def wait_for(predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_stream_reconnects_after_server_drops_connection_and_resubscribes(server_factory):
    state = {"connections": 0, "subscribes": 0}

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        state["connections"] += 1
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT and json.loads(msg.data).get("op") == "subscribe":
                state["subscribes"] += 1
                await ws.send_str(json.dumps({"p": str(100 + state["connections"])}))
                await ws.close()  # сервер обрывает соединение после первого сообщения
        return ws

    app = web.Application()
    app.add_routes([web.get("/ws", ws_handler)])
    server = await server_factory(app)
    quotes, events = [], []
    hooks = StreamHooks(on_quote=quotes.append, on_connected=lambda: events.append("up"),
                        on_disconnected=lambda r: events.append("down"))
    http = HttpClient()
    stream = EchoStream(f"ws://127.0.0.1:{server.port}/ws", hooks, http)
    stream.start()
    try:
        assert await wait_for(lambda: len(quotes) >= 3), "поток не переподключился"
    finally:
        await stream.stop()
        await http.close()
    assert state["connections"] >= 3 and state["subscribes"] >= 3  # каждый раз заново подписываемся
    assert events.count("up") >= 3 and events.count("down") >= 2
    assert [q.bid for q in quotes[:3]] == [Decimal(101), Decimal(102), Decimal(103)]


async def test_stream_reconnects_when_server_goes_silent(server_factory):
    state = {"connections": 0}

    async def silent(request):
        ws = web.WebSocketResponse(autoping=False)
        await ws.prepare(request)
        state["connections"] += 1
        await asyncio.sleep(3)  # ни одного сообщения, включая pong
        return ws

    app = web.Application()
    app.add_routes([web.get("/ws", silent)])
    server = await server_factory(app)
    errors: list[str] = []
    http = HttpClient()
    stream = EchoStream(f"ws://127.0.0.1:{server.port}/ws", StreamHooks(on_error=errors.append), http, idle_timeout=0.3)
    stream.start()
    try:
        assert await wait_for(lambda: state["connections"] >= 2), "зависшее соединение не переоткрыто"
    finally:
        await stream.stop()
        await http.close()
    assert any("нет данных" in e for e in errors)


async def test_stream_sends_application_pings_and_survives_bad_messages(server_factory):
    received: list[str] = []

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({"bad": 1}))  # parse() бросит исключение
        await ws.send_str(json.dumps({"p": "50"}))
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                received.append(msg.data)
                if msg.data == "ping":
                    await ws.send_str("pong")
        return ws

    app = web.Application()
    app.add_routes([web.get("/ws", ws_handler)])
    server = await server_factory(app)
    quotes: list[Quote] = []
    http = HttpClient()
    stream = EchoStream(f"ws://127.0.0.1:{server.port}/ws", StreamHooks(on_quote=quotes.append), http)
    stream.start()
    try:
        assert await wait_for(lambda: received.count("ping") >= 2), "keep-alive ping не отправляется"
    finally:
        await stream.stop()
        await http.close()
    assert [q.bid for q in quotes] == [Decimal(50)]  # после битого сообщения поток продолжил работу


async def test_stream_survives_connection_refused_and_recovers(server_factory):
    http = HttpClient()
    errors: list[str] = []
    quotes: list[Quote] = []
    state = {"up": False}
    port_holder = {}

    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(json.dumps({"p": "7"}))
        async for _ in ws:
            pass
        return ws

    # занимаем порт, чтобы сразу знать адрес, затем освобождаем: первое подключение будет отклонено
    probe = TestServer(web.Application())
    await probe.start_server()
    port_holder["port"] = probe.port
    await probe.close()

    stream = EchoStream(f"ws://127.0.0.1:{port_holder['port']}/ws", StreamHooks(on_error=errors.append, on_quote=quotes.append), http)
    stream.start()
    try:
        assert await wait_for(lambda: len(errors) >= 2)  # сервера нет — поток повторяет попытки, а не падает
        app = web.Application()
        app.add_routes([web.get("/ws", ws_handler)])
        server = TestServer(app, port=port_holder["port"])
        await server.start_server()
        state["up"] = True
        try:
            assert await wait_for(lambda: len(quotes) >= 1), "поток не восстановился после появления сервера"
        finally:
            await server.close()
    finally:
        await stream.stop()
        await http.close()


async def test_stop_cancels_stream_cleanly(server_factory):
    async def ws_handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for _ in ws:
            pass
        return ws

    app = web.Application()
    app.add_routes([web.get("/ws", ws_handler)])
    server = await server_factory(app)
    http = HttpClient()
    stream = EchoStream(f"ws://127.0.0.1:{server.port}/ws", StreamHooks(), http)
    task = stream.start()
    await asyncio.sleep(0.3)
    await stream.stop()
    assert task.done()
    await http.close()
