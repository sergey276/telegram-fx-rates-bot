"""Единый интерфейс провайдера котировок (банк или биржа)."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain import Quote, SourceKind
from app.utils.http import AsyncRateLimiter, GeoBlockedError, HttpClient, ProviderError, RateLimitedError

if TYPE_CHECKING:
    from app.websocket.base import BaseStream, StreamHooks

log = logging.getLogger(__name__)


class BaseProvider(ABC):
    """Каждый банк и каждая биржа — отдельный провайдер с одинаковым интерфейсом."""

    name: str
    display_name: str
    kind: SourceKind

    def __init__(self, http: HttpClient) -> None:
        self.http = http

    @abstractmethod
    async def fetch_quotes(self, symbols: Sequence[str] = ()) -> list[Quote]:
        """Запрашивает котировки по REST. Пары, которых нет у источника, просто отсутствуют в результате.

        Бросает ``ProviderError`` (и наследников), если источник недоступен.
        """

    def create_stream(self, symbols: Sequence[str], hooks: StreamHooks) -> BaseStream | None:
        """WebSocket-поток для источника или ``None``, если потока нет."""
        return None

    @property
    def supports_stream(self) -> bool:
        return False


@dataclass(slots=True)
class FetchResult:
    quotes: list[Quote] = field(default_factory=list)
    not_listed: set[str] = field(default_factory=set)
    failed: dict[str, Exception] = field(default_factory=dict)


class ExchangeProvider(BaseProvider, ABC):
    """Биржа: котировки запрашиваются по одной паре (массовые эндпоинты тяжёлые и медленные)."""

    kind = SourceKind.EXCHANGE
    concurrency = 4

    def __init__(self, http: HttpClient, rest_url: str, limiter: AsyncRateLimiter, ws_url: str = "") -> None:
        super().__init__(http)
        self.rest_url = rest_url.rstrip("/")
        self.ws_url = ws_url
        self.limiter = limiter

    @abstractmethod
    async def fetch_one(self, symbol: str) -> Quote | None:
        """Одна пара. ``None`` — пара не торгуется на бирже. Ошибки — через исключения."""

    async def fetch_detailed(self, symbols: Sequence[str]) -> FetchResult:
        """Как ``fetch_quotes``, но различает «пары нет на бирже» и «запрос по паре не удался»."""
        semaphore = asyncio.Semaphore(self.concurrency)

        async def guarded(symbol: str) -> Quote | None:
            async with semaphore:
                return await self.fetch_one(symbol)

        results = await asyncio.gather(*(guarded(s) for s in symbols), return_exceptions=True)
        outcome = FetchResult()
        for symbol, result in zip(symbols, results, strict=True):
            if isinstance(result, (RateLimitedError, GeoBlockedError)):
                raise result  # проблема всего источника, а не одной пары
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                outcome.failed[symbol] = result if isinstance(result, Exception) else ProviderError(repr(result))
                log.debug("%s %s: %s", self.name, symbol, result)
            elif result is not None and result.has_price:
                outcome.quotes.append(result)
            else:
                outcome.not_listed.add(symbol)
        if outcome.failed and not outcome.quotes and not outcome.not_listed:
            first = next(iter(outcome.failed.values()))
            raise first if isinstance(first, ProviderError) else ProviderError(f"{type(first).__name__}: {first}")
        return outcome

    async def fetch_quotes(self, symbols: Sequence[str] = ()) -> list[Quote]:
        return (await self.fetch_detailed(symbols)).quotes


QuoteHandler = Callable[[Quote], None]
AsyncQuoteHandler = Callable[[Quote], Awaitable[None]]
