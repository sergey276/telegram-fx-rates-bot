"""Сборщик данных одной биржи: REST-загрузка + WebSocket + контроль актуальности + восстановление."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

from app.cache import QuoteStore
from app.config import Settings
from app.domain import Quote
from app.providers.base import ExchangeProvider
from app.services.assets import AssetRegistry
from app.services.health import HealthRegistry
from app.utils.http import GeoBlockedError, ProviderError, RateLimitedError
from app.websocket.base import BaseStream, StreamHooks

log = logging.getLogger(__name__)

_MAX_BACKOFF = 300.0


class ExchangeCollector:
    """Жизненный цикл:

    1. REST-загрузка всех отслеживаемых пар — так выясняется, какие из них реально торгуются на бирже;
    2. запуск WebSocket только по этим парам (с автоматическим переподключением внутри потока);
    3. сторожевой таймер: пары, по которым давно нет данных, обновляются через REST;
    4. периодическая REST-сверка всех пар (объём 24ч, появление новых листингов).
    """

    def __init__(
        self,
        provider: ExchangeProvider,
        store: QuoteStore,
        health: HealthRegistry,
        assets: AssetRegistry,
        settings: Settings,
    ) -> None:
        self.provider = provider
        self.store = store
        self.health = health
        self.assets = assets
        self.settings = settings
        self.name = provider.name
        self._listed: set[str] = set()
        self._unlisted: set[str] = set()
        self._stream: BaseStream | None = None
        self._stream_symbols: tuple[str, ...] = ()
        self._task: asyncio.Task[None] | None = None
        self._wakeup = asyncio.Event()
        self._rest_failures = 0
        self._blocked_until = 0.0
        self._last_sweep = 0.0

    # ----- управление -----
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name=f"collector-{self.name}")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._stop_stream()

    def poke(self) -> None:
        """Сообщает сборщику, что изменился список пар или статус источника."""
        self._wakeup.set()

    # ----- основной цикл -----
    async def _run(self) -> None:
        while True:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s: непредвиденная ошибка сборщика", self.name)
                self.health.record_error(self.name, "внутренняя ошибка сборщика (см. лог)")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wakeup.wait(), timeout=self.settings.stale_watchdog_seconds)
            self._wakeup.clear()

    async def _tick(self) -> None:
        if not self.health.is_enabled(self.name):
            await self._stop_stream()
            return

        symbols = self.assets.crypto
        now = time.monotonic()
        if now < self._blocked_until:
            return

        known = self._listed | self._unlisted
        new_symbols = [s for s in symbols if s not in known]
        sweep_due = now - self._last_sweep >= self.settings.rest_sweep_seconds

        if new_symbols and self._last_sweep:
            await self._rest_fetch(new_symbols, classify=True)
        elif sweep_due or not self._last_sweep:
            await self._rest_fetch(symbols, classify=True)
            self._last_sweep = time.monotonic()
        else:
            stale = self._stale_symbols()
            if stale:
                await self._rest_fetch(stale, classify=False)

        await self._ensure_stream()

    def _stale_symbols(self) -> list[str]:
        threshold = self.settings.crypto_fresh_seconds * 0.66
        stale = []
        for symbol in self._listed:
            if symbol not in self.assets.crypto:
                continue
            quote = self.store.get(self.name, symbol)
            if quote is None or quote.age_seconds() > threshold:
                stale.append(symbol)
        return stale

    # ----- REST -----
    async def _rest_fetch(self, symbols: list[str], classify: bool) -> None:
        if not symbols:
            return
        try:
            result = await self.provider.fetch_detailed(symbols)
        except RateLimitedError as exc:
            self._blocked_until = time.monotonic() + exc.retry_after
            self.health.record_error(self.name, f"лимит запросов: пауза {exc.retry_after:.0f} с ({exc})")
            return
        except GeoBlockedError as exc:
            self._blocked_until = time.monotonic() + 600
            self.health.record_error(self.name, f"{exc}. Следующая попытка через 10 минут")
            return
        except ProviderError as exc:
            self._rest_failures += 1
            delay = min(5.0 * 2 ** (self._rest_failures - 1), _MAX_BACKOFF)
            self._blocked_until = time.monotonic() + delay
            self.health.record_error(self.name, f"REST: {exc}. Повтор через {delay:.0f} с")
            return
        self._rest_failures = 0
        self.health.record_success(self.name)
        self.store.put_many(result.quotes)
        if result.failed:
            first = next(iter(result.failed.items()))
            self.health.record_error(self.name, f"REST: не удалось получить {', '.join(result.failed)}: {first[1]}")
        if classify:
            # Пара «не торгуется» только если биржа это явно сообщила; сбой запроса статус пары не меняет.
            for quote in result.quotes:
                self._listed.add(quote.symbol)
                self._unlisted.discard(quote.symbol)
            for symbol in result.not_listed:
                self._listed.discard(symbol)
                self._unlisted.add(symbol)
            self._unlisted &= set(self.assets.crypto)
            self.health.set_unlisted(self.name, self._unlisted)

    # ----- WebSocket -----
    async def _ensure_stream(self) -> None:
        if not self.settings.ws_enabled or not self.provider.supports_stream:
            return
        wanted = tuple(sorted(s for s in self._listed if s in self.assets.crypto))
        if not wanted:
            await self._stop_stream()
            return
        if self._stream is not None and wanted == self._stream_symbols:
            return
        await self._stop_stream()
        hooks = StreamHooks(
            on_quote=self._on_stream_quote,
            on_connected=lambda: self.health.set_ws(self.name, True),
            on_disconnected=self._on_stream_disconnected,
            on_error=lambda msg: self.health.record_error(self.name, f"WebSocket: {msg}"),
        )
        stream = self.provider.create_stream(wanted, hooks)
        if stream is None:
            return
        self._stream, self._stream_symbols = stream, wanted
        stream.start()
        log.info("%s: запущен WebSocket-поток по парам %s", self.name, ", ".join(wanted))

    async def _stop_stream(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None
            self._stream_symbols = ()
        self.health.set_ws(self.name, False)

    def _on_stream_quote(self, quote: Quote) -> None:
        self.store.put(quote)
        self.health.record_message(self.name)

    def _on_stream_disconnected(self, reason: str) -> None:
        self.health.set_ws(self.name, False)
        log.info("%s: WebSocket отключён (%s)", self.name, reason)
