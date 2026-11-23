"""Диагностика источников без Telegram и без БД.

    python -m app.tools.check_sources                # REST всех источников
    python -m app.tools.check_sources --ws 10        # + WebSocket 10 секунд
    python -m app.tools.check_sources --pairs BTC/USDT,ETH/USDT
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Callable

from app.config import Settings
from app.domain import Quote, SourceKind
from app.providers import build_providers
from app.utils.http import HttpClient
from app.utils.symbols import asset_kind
from app.websocket.base import StreamHooks


def _fmt(q: Quote) -> str:
    parts = [f"bid={q.bid}", f"ask={q.ask}"]
    if q.kind is SourceKind.EXCHANGE:
        parts += [f"last={q.last}", f"vol24h={q.volume_24h}"]
    elif q.cross_rate is not None:
        parts.append(f"cross={q.cross_rate}")
    if q.missing_fields():
        parts.append(f"нет: {','.join(q.missing_fields())}")
    return " ".join(parts)


async def check(settings: Settings, pairs: list[str], ws_seconds: int) -> int:
    http = HttpClient(settings.http_timeout_seconds)
    providers = build_providers(settings, http)
    crypto = [p for p in pairs if asset_kind(p) == "crypto"]
    fiat = [p for p in pairs if asset_kind(p) == "fiat"]
    failures = 0
    listed: dict[str, list[str]] = {}
    try:
        for name, provider in providers.items():
            symbols = fiat if provider.kind is SourceKind.BANK else crypto
            started = time.perf_counter()
            try:
                quotes = await provider.fetch_quotes(symbols)
            except Exception as exc:
                failures += 1
                print(f"[FAIL] {name:<10} {type(exc).__name__}: {exc}")
                continue
            print(f"[ OK ] {name:<10} {len(quotes)}/{len(symbols)} пар за {time.perf_counter() - started:.1f}с")
            got = {q.symbol for q in quotes}
            listed[name] = [s for s in symbols if s in got]
            for q in quotes:
                print(f"         {q.symbol:<10} {_fmt(q)}")
            for symbol in symbols:
                if symbol not in got:
                    print(f"         {symbol:<10} — нет на источнике / нет стакана")

        if ws_seconds > 0:
            print(f"\nWebSocket, {ws_seconds} с:")
            counts: dict[str, int] = {}
            errors: dict[str, str] = {}
            streams = []

            def count_quote(q: Quote) -> None:
                counts[q.source] = counts.get(q.source, 0) + 1

            def error_recorder(source: str) -> Callable[[str], None]:
                def record(message: str) -> None:
                    errors[source] = message

                return record

            for name, provider in providers.items():
                if not provider.supports_stream or not listed.get(name):
                    continue
                hooks = StreamHooks(on_quote=count_quote, on_error=error_recorder(name))
                stream = provider.create_stream(listed[name], hooks)
                if stream is not None:
                    streams.append(stream)
                    stream.start()
            await asyncio.sleep(ws_seconds)
            for stream in streams:
                await stream.stop()
            for stream in streams:
                n = counts.get(stream.source, 0)
                status = "OK  " if n else "FAIL"
                failures += 0 if n else 1
                print(f"[{status}] {stream.source:<10} сообщений-котировок: {n}  {errors.get(stream.source, '')}")
    finally:
        await http.close()
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ws", type=int, default=0, help="секунды проверки WebSocket (0 — не проверять)")
    parser.add_argument("--pairs", default="BTC/USDT,ETH/USDT,TON/USDT,USD/UAH,EUR/UAH,GBP/UAH")
    args = parser.parse_args()
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    failures = asyncio.run(check(Settings(), pairs, args.ws))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
