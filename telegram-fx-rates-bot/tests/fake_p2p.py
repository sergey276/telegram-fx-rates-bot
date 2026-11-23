"""Поддельные P2P-площадки для тестов: предсказуемые цены по банкам."""

from __future__ import annotations

import asyncio
from decimal import Decimal as D

from app.providers.p2p_common import P2P_BANKS, P2PAd, P2PPlatform, Side
from app.utils.http import ProviderError, RateLimitedError

# площадка -> (цены покупки по банкам, цены продажи по банкам)
PRICES: dict[str, tuple[dict[str, str], dict[str, str]]] = {
    "binance": (
        {"monobank": "47.42", "privatbank": "47.50", "alliance": "47.69", "sense": "47.69", "abank": "47.43", "pumb": "47.43"},
        {"monobank": "48.73", "privatbank": "49.19", "alliance": "48.30", "sense": "48.20", "abank": "48.64", "pumb": "48.65"},
    ),
    "bybit": (
        {"monobank": "47.19", "privatbank": "47.30", "sense": "47.60", "abank": "47.25", "pumb": "47.31"},
        {"monobank": "47.35", "privatbank": "47.40", "sense": "47.10", "abank": "47.20", "pumb": "47.25"},
    ),
    "okx": (
        {"monobank": "46.80", "privatbank": "46.95", "sense": "47.20", "abank": "46.85", "pumb": "46.90"},
        {"monobank": "49.15", "privatbank": "49.31", "sense": "48.50", "abank": "49.00", "pumb": "49.05"},
    ),
    "kucoin": ({"monobank": "48.29", "privatbank": "48.30"}, {"monobank": "45.12", "privatbank": "45.01"}),
    "bitget": ({"monobank": "47.66", "privatbank": "47.67"}, {"monobank": "47.10", "privatbank": "47.02"}),
}


def ad(price: str, orders: int = 500, rate: str = "0.99", low: str = "500", high: str = "50000", qty: str = "1000") -> P2PAd:
    return P2PAd(D(price), D(qty), D(low), D(high), orders, D(rate), True)


class FakePlatform(P2PPlatform):
    def __init__(self, name: str, display: str | None = None) -> None:
        self.name = name
        self.display_name = display or name.capitalize()
        self.calls: list[tuple[str, str, D]] = []
        self.error: Exception | None = None
        self.delay = 0.0

    async def fetch(self, asset: str, side: Side, amount: D) -> dict[str, list[P2PAd]]:
        self.calls.append((asset, side.value, amount))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        buy, sell = PRICES[self.name]
        table = buy if side is Side.BUY else sell
        scale = D(1) if asset == "USDT" else D(60000)
        result: dict[str, list[P2PAd]] = {}
        for bank, price in table.items():
            base = D(price) * scale
            better = base - 1 if side is Side.BUY else base + 1  # «лучшая» цена у ненадёжного объявителя — должна отсеяться
            result[bank] = [
                ad(str(better), orders=3, rate="0.50"),
                ad(str(base + (D("0.2") if side is Side.BUY else D("-0.2")))),
                ad(str(base)),
                ad(str(base - 5 if side is Side.BUY else base + 5), low="100000", high="200000"),  # не подходит под сумму
            ]
        return result


def fake_platforms() -> list[FakePlatform]:
    return [FakePlatform(n, d) for n, d in (("binance", "Binance"), ("bybit", "Bybit"), ("okx", "OKX"), ("kucoin", "KuCoin"), ("bitget", "Bitget"))]


assert set(P2P_BANKS) >= {b for t in PRICES.values() for side in t for b in side}
_ = (ProviderError, RateLimitedError)
