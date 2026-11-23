"""P2P-раздел: сравнение цен покупки/продажи криптовалюты за гривны по площадкам и банкам."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.domain import utcnow
from app.providers.p2p_common import P2P_BANKS, P2PAd, P2PPlatform, Side
from app.utils.http import ProviderError, RateLimitedError

log = logging.getLogger(__name__)

ASSETS = ("USDT", "BTC", "ETH")
AMOUNTS = (1000, 5000, 10000, 50000)  # суммы сделки в гривнах: объявления фильтруются под выбранную сумму
DEFAULT_AMOUNT = 5000
MIN_MONTH_ORDERS = 20  # защита от новичков и мошенников
MIN_FINISH_RATE = Decimal("0.90")
TOP_ADS = 5
CACHE_TTL = 60.0
MAX_STALE = 600.0  # при сбое площадки показываем прошлые данные не старше 10 минут (с пометкой)
PLATFORM_TIMEOUT = 25.0
MIN_BLOCK = 60.0


@dataclass(slots=True)
class PlatformData:
    """Результат одной площадки: лучшие объявления по банкам и сторонам."""

    fetched_at: datetime
    offers: dict[str, dict[Side, list[P2PAd]]] = field(default_factory=dict)
    error: str | None = None
    stale: bool = False  # показаны прошлые данные, потому что обновить не удалось

    @property
    def has_data(self) -> bool:
        return any(ads for sides in self.offers.values() for ads in sides.values())

    def best(self, bank: str, side: Side) -> P2PAd | None:
        ads = self.offers.get(bank, {}).get(side) or []
        return ads[0] if ads else None


@dataclass(slots=True)
class P2PBoard:
    asset: str
    amount: int
    fetched_at: datetime
    platforms: dict[str, PlatformData]
    names: dict[str, str]  # ключ площадки -> название

    # ----- лучшее среди площадок для банка -----
    def best_for_bank(self, bank: str, side: Side) -> tuple[str, P2PAd] | None:
        found: list[tuple[str, P2PAd]] = []
        for platform, data in self.platforms.items():
            ad = data.best(bank, side)
            if ad is not None:
                found.append((platform, ad))
        if not found:
            return None
        return min(found, key=lambda x: x[1].price) if side is Side.BUY else max(found, key=lambda x: x[1].price)

    # ----- лучшее среди банков для площадки -----
    def best_for_platform(self, platform: str, side: Side) -> tuple[str, P2PAd] | None:
        data = self.platforms[platform]
        found: list[tuple[str, P2PAd]] = []
        for bank in P2P_BANKS:
            ad = data.best(bank, side)
            if ad is not None:
                found.append((bank, ad))
        if not found:
            return None
        return min(found, key=lambda x: x[1].price) if side is Side.BUY else max(found, key=lambda x: x[1].price)

    def _overall(self, side: Side) -> tuple[str, str, P2PAd] | None:
        found: list[tuple[str, str, P2PAd]] = []
        for platform, data in self.platforms.items():
            for bank in P2P_BANKS:
                ad = data.best(bank, side)
                if ad is not None:
                    found.append((platform, bank, ad))
        if not found:
            return None
        return min(found, key=lambda x: x[2].price) if side is Side.BUY else max(found, key=lambda x: x[2].price)

    def cheapest_buy(self) -> tuple[str, str, P2PAd] | None:
        """(площадка, банк, объявление) с самой низкой ценой покупки среди всех площадок и банков."""
        return self._overall(Side.BUY)

    def richest_sell(self) -> tuple[str, str, P2PAd] | None:
        return self._overall(Side.SELL)

    def cross_pct(self) -> Decimal | None:
        buy, sell = self.cheapest_buy(), self.richest_sell()
        if buy is None or sell is None:
            return None
        return (sell[2].price - buy[2].price) / buy[2].price * 100

    def top_ads(self, bank: str, side: Side, limit: int = TOP_ADS) -> list[tuple[str, P2PAd]]:
        """Лучшие объявления банка среди ВСЕХ площадок (площадка, объявление)."""
        merged = [(p, ad) for p, d in self.platforms.items() for ad in d.offers.get(bank, {}).get(side, [])]
        merged.sort(key=lambda x: x[1].price, reverse=side is Side.SELL)
        return merged[:limit]

    @property
    def has_data(self) -> bool:
        return any(d.has_data for d in self.platforms.values())

    @property
    def failed(self) -> list[str]:
        """Площадки, которые не ответили и для которых нет даже прошлых данных."""
        return [p for p, d in self.platforms.items() if d.error and not d.has_data]

    @property
    def stale(self) -> list[str]:
        return [p for p, d in self.platforms.items() if d.stale]


def select_ads(ads: Sequence[P2PAd], side: Side, amount: Decimal) -> list[P2PAd]:
    """Оставляет объявления, подходящие под сумму, от надёжных объявителей; лучшие цены первыми."""
    good = [
        a for a in ads
        if a.fits(amount) and a.month_orders >= MIN_MONTH_ORDERS and a.finish_rate >= MIN_FINISH_RATE
    ]
    good.sort(key=lambda a: a.price, reverse=side is Side.SELL)
    return good[:TOP_ADS]


class P2PService:
    def __init__(self, platforms: Sequence[P2PPlatform], ttl: float = CACHE_TTL) -> None:
        self._platforms = {p.name: p for p in platforms}
        self._ttl = ttl
        self._cache: dict[tuple[str, str, int], tuple[float, PlatformData]] = {}
        self._blocked_until: dict[str, float] = {}
        self._locks: dict[tuple[str, int], asyncio.Lock] = {}

    @property
    def names(self) -> dict[str, str]:
        return {k: p.display_name for k, p in self._platforms.items()}

    async def board(self, asset: str = "USDT", amount: int = DEFAULT_AMOUNT, force: bool = False) -> P2PBoard:
        if asset not in ASSETS or amount not in AMOUNTS:
            raise ValueError("недопустимые параметры P2P")
        lock = self._locks.setdefault((asset, amount), asyncio.Lock())
        async with lock:  # одновременные запросы пользователей делят один обход площадок
            names = list(self._platforms)
            results = await asyncio.gather(*(self._platform(n, asset, amount, force) for n in names))
            return P2PBoard(asset, amount, utcnow(), dict(zip(names, results, strict=True)), self.names)

    async def _platform(self, name: str, asset: str, amount: int, force: bool) -> PlatformData:
        key = (name, asset, amount)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and not force and now - cached[0] < self._ttl:
            return cached[1]
        platform = self._platforms[name]
        if not platform.supports(asset):
            return PlatformData(utcnow(), error="актив не поддерживается")
        if now < self._blocked_until.get(name, 0):
            return self._fallback(cached, "лимит запросов площадки")
        try:
            data = await asyncio.wait_for(self._fetch(platform, asset, amount), PLATFORM_TIMEOUT)
        except RateLimitedError as exc:
            self._blocked_until[name] = time.monotonic() + max(MIN_BLOCK, exc.retry_after)
            log.warning("P2P %s: лимит запросов, пауза", name)
            return self._fallback(cached, "лимит запросов площадки")
        except (ProviderError, TimeoutError) as exc:
            log.warning("P2P %s: %s", name, exc or "таймаут")
            return self._fallback(cached, str(exc) or "таймаут")
        except Exception as exc:  # неожиданный формат ответа не должен ронять раздел целиком
            log.exception("P2P %s: непредвиденная ошибка", name)
            return self._fallback(cached, f"{type(exc).__name__}")
        if not data.has_data and cached and cached[1].has_data:
            return self._fallback(cached, "пустой ответ")
        self._cache[key] = (time.monotonic(), data)
        return data

    @staticmethod
    def _fallback(cached: tuple[float, PlatformData] | None, error: str) -> PlatformData:
        if cached and time.monotonic() - cached[0] < MAX_STALE and cached[1].has_data:
            old = cached[1]
            return PlatformData(old.fetched_at, old.offers, error=error, stale=True)
        return PlatformData(utcnow(), error=error)

    @staticmethod
    async def _fetch(platform: P2PPlatform, asset: str, amount: int) -> PlatformData:
        value = Decimal(amount)
        buy, sell = await asyncio.gather(platform.fetch(asset, Side.BUY, value), platform.fetch(asset, Side.SELL, value))
        offers = {
            bank: {Side.BUY: select_ads(buy.get(bank, []), Side.BUY, value), Side.SELL: select_ads(sell.get(bank, []), Side.SELL, value)}
            for bank in P2P_BANKS
        }
        return PlatformData(utcnow(), offers)
