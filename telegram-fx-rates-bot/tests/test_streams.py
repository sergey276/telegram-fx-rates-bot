"""Разбор реальных WebSocket-сообщений каждой биржи."""

from __future__ import annotations

import gzip
from decimal import Decimal

import aiohttp

from app.utils.http import HttpClient
from app.websocket.base import StreamHooks
from app.websocket.binance import BinanceStream
from app.websocket.bingx import BingxStream
from app.websocket.bitget import BitgetStream
from app.websocket.bybit import BybitStream
from app.websocket.kucoin import KucoinStream
from app.websocket.okx import OkxStream
from tests.conftest import load_lines

HTTP = HttpClient()
HOOKS = StreamHooks()


def feed(stream, lines):
    out = []
    for line in lines:
        out += stream.parse(line)
    return out


def test_binance_ticker_stream():
    quotes = feed(BinanceStream(["BTC/USDT", "ETH/USDT"], HOOKS, HTTP, "wss://x"), load_lines("ws_binance.jsonl"))
    assert [q.symbol for q in quotes] == ["BTC/USDT"]  # bookTicker другого потока игнорируется
    q = quotes[0]
    assert q.bid == Decimal("61499.99") and q.ask == Decimal("61500.00")
    assert q.bid_size == Decimal("1.19048") and q.volume_24h == Decimal("19548.72721")
    assert q.source_ts is not None


async def test_binance_url_lists_streams():
    url = await BinanceStream(["BTC/USDT", "ETH/USDT"], HOOKS, HTTP, "wss://h:9443").connect_url()
    assert url == "wss://h:9443/stream?streams=btcusdt@ticker/ethusdt@ticker"


def test_bybit_merges_ticker_and_orderbook():
    stream = BybitStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    lines = load_lines("ws_bybit.jsonl")
    assert stream.parse(lines[1]) == []  # tickers без стакана — котировку ещё не выдаём
    quotes = feed(stream, lines[2:])
    assert len(quotes) == 2
    q = quotes[-1]
    assert q.bid == Decimal("61519.4") and q.ask == Decimal("61520.5")
    assert q.last == Decimal("61519.5") and q.volume_24h == Decimal("12724.023326")


def test_bybit_subscribes_per_symbol_so_one_bad_pair_cannot_break_the_rest():
    stream = BybitStream(["BTC/USDT", "TON/USDT"], HOOKS, HTTP, "wss://x")
    messages = stream.subscribe_messages()
    assert [m["args"] for m in messages] == [
        ["tickers.BTCUSDT", "orderbook.1.BTCUSDT"],
        ["tickers.TONUSDT", "orderbook.1.TONUSDT"],
    ]


def test_bybit_rejected_subscription_is_reported_not_swallowed():
    errors: list[str] = []
    stream = BybitStream(["TON/USDT"], StreamHooks(on_error=errors.append), HTTP, "wss://x")
    rejected = '{"success":false,"ret_msg":"Invalid symbol :[tickers.TONUSDT]","conn_id":"x","op":"subscribe"}'
    assert stream.parse(rejected) == []
    assert errors and "TONUSDT" in errors[0]


def test_bybit_delta_removal_waits_for_snapshot():
    stream = BybitStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    feed(stream, load_lines("ws_bybit.jsonl")[2:])
    delta = '{"topic":"orderbook.1.BTCUSDT","ts":1,"type":"delta","data":{"s":"BTCUSDT","b":[["61519.4","0"]],"a":[]}}'
    assert stream.parse(delta) == []


def test_okx_ticker_and_pong():
    stream = OkxStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    quotes = feed(stream, load_lines("ws_okx.jsonl"))
    assert len(quotes) == 1 and quotes[0].bid == Decimal("61524.2") and quotes[0].ask == Decimal("61524.3")
    assert stream.parse("pong") == []


def test_okx_error_event_reported():
    errors: list[str] = []
    stream = OkxStream(["BTC/USDT"], StreamHooks(on_error=errors.append), HTTP, "wss://x")
    assert stream.parse('{"event":"error","code":"60012","msg":"Invalid request"}') == []
    assert errors and "60012" in errors[0]


def test_bitget_ticker():
    stream = BitgetStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    quotes = feed(stream, load_lines("ws_bitget.jsonl"))
    assert len(quotes) == 1
    assert quotes[0].bid == Decimal("61541.68") and quotes[0].ask == Decimal("61541.69")
    assert quotes[0].volume_24h == Decimal("7229.836814")
    assert stream.parse("pong") == []


def test_kucoin_ticker_ignores_welcome_and_ack():
    stream = KucoinStream(["BTC/USDT"], HOOKS, HTTP, "https://x")
    quotes = feed(stream, load_lines("ws_kucoin.jsonl"))
    assert len(quotes) == 1
    assert quotes[0].symbol == "BTC/USDT" and quotes[0].bid == Decimal("61533.3") and quotes[0].volume_24h is None


def test_kucoin_subscribe_joins_symbols_in_topic():
    stream = KucoinStream(["BTC/USDT", "ETH/USDT"], HOOKS, HTTP, "https://x")
    (message,) = stream.subscribe_messages()
    assert message["topic"] == "/market/ticker:BTC-USDT,ETH-USDT"


def test_bingx_merges_last_price_and_book():
    stream = BingxStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    lines = load_lines("ws_bingx.jsonl")
    assert stream.parse(lines[0]) == []
    assert stream.parse(lines[1]) == []  # lastPrice без стакана
    quotes = stream.parse(lines[2])
    assert len(quotes) == 1
    assert quotes[0].bid == Decimal("61514.87") and quotes[0].ask == Decimal("61514.88")
    assert quotes[0].last == Decimal("61514.87") and quotes[0].ask_size == Decimal("0.006231")


def test_bingx_decodes_gzip_binary_frames():
    stream = BingxStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    payload = gzip.compress(load_lines("ws_bingx.jsonl")[2].encode())
    msg = aiohttp.WSMessage(aiohttp.WSMsgType.BINARY, payload, None)
    text = stream.decode(msg)
    assert text is not None and "bookTicker" in text
    assert stream.decode(aiohttp.WSMessage(aiohttp.WSMsgType.BINARY, b"not gzip", None)) is None


async def test_bingx_answers_ping_with_pong():
    sent: list[str] = []

    class FakeWs:
        async def send_str(self, data: str) -> None:
            sent.append(data)

    stream = BingxStream(["BTC/USDT"], HOOKS, HTTP, "wss://x")
    assert await stream.on_control("Ping", FakeWs()) is True  # type: ignore[arg-type]
    assert sent == ["Pong"]
    assert await stream.on_control("{}", FakeWs()) is False  # type: ignore[arg-type]
