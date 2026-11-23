"""Асинхронный HTTP-клиент с ограничением частоты запросов и типизированными ошибками."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

log = logging.getLogger(__name__)


class ProviderError(Exception):
    """Источник недоступен или вернул неожиданный ответ."""


class RateLimitedError(ProviderError):
    """Источник ответил 429/418 — нужно подождать ``retry_after`` секунд."""

    def __init__(self, message: str, retry_after: float = 60.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class GeoBlockedError(ProviderError):
    """Доступ запрещён по региону / IP (HTTP 403/451)."""


class AsyncRateLimiter:
    """Токен-бакет: не более ``rate`` запросов в секунду, всплеск до ``burst``."""

    def __init__(self, rate: float, burst: int = 1) -> None:
        self._rate = rate
        self._capacity = float(max(burst, 1))
        self._tokens = self._capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self._rate)


class HttpClient:
    """Тонкая обёртка над aiohttp: таймауты, повторы на сетевых сбоях/5xx, разбор 429/451."""

    def __init__(self, timeout: float = 15.0, retries: int = 2) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout, connect=min(timeout, 10))
        self._retries = retries
        self._session: aiohttp.ClientSession | None = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                headers={"User-Agent": "fx-crypto-monitor-bot/1.0", "Accept": "application/json"},
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        limiter: AsyncRateLimiter | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request_json("GET", url, params=params, limiter=limiter, headers=headers)

    async def post_json(
        self,
        url: str,
        *,
        json: Any | None = None,
        limiter: AsyncRateLimiter | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        return await self._request_json("POST", url, json=json, limiter=limiter, headers=headers)

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        limiter: AsyncRateLimiter | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            if limiter is not None:
                await limiter.acquire()
            try:
                async with self.session.request(method, url, params=params, json=json, headers=headers) as resp:
                    if resp.status in (429, 418):
                        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                        raise RateLimitedError(f"HTTP {resp.status} от {_host(url)}", retry_after)
                    if resp.status in (403, 451):
                        raise GeoBlockedError(f"HTTP {resp.status} от {_host(url)} (доступ ограничен по региону/IP)")
                    if resp.status >= 500:
                        raise ProviderError(f"HTTP {resp.status} от {_host(url)}")
                    if resp.status >= 400:
                        body = (await resp.text())[:200]
                        # Для 4xx часто приходит JSON с кодом ошибки биржи — отдаём вызывающему коду.
                        try:
                            return await resp.json(content_type=None)
                        except (aiohttp.ContentTypeError, ValueError):
                            raise ProviderError(f"HTTP {resp.status} от {_host(url)}: {body}") from None
                    return await resp.json(content_type=None)
            except (RateLimitedError, GeoBlockedError):
                raise
            except (TimeoutError, aiohttp.ClientError, ProviderError, ValueError) as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(0.5 * (2**attempt))
        if isinstance(last_error, ProviderError):
            raise last_error
        raise ProviderError(f"{_host(url)}: {type(last_error).__name__}: {last_error}") from last_error


def _host(url: str) -> str:
    return url.split("/", 3)[2] if "//" in url else url


def _parse_retry_after(value: str | None) -> float:
    try:
        return max(1.0, float(value)) if value else 60.0
    except ValueError:
        return 60.0
