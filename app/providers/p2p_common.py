"""Общие типы P2P: объявление, банки, интерфейс площадки.

Площадки (Binance, Bybit, OKX, KuCoin, Bitget) не имеют официального публичного API для P2P — используются
публичные веб-эндпоинты их сайтов. Каждый адаптер приводит ответ к одному формату ``P2PAd``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from app.utils.symbols import to_decimal


class Side(StrEnum):
    """Сторона с точки зрения ПОЛЬЗОВАТЕЛЯ."""

    BUY = "BUY"  # вы покупаете криптовалюту (объявления продавцов): чем ниже цена, тем лучше
    SELL = "SELL"  # вы продаёте криптовалюту (объявления покупателей): чем выше цена, тем лучше


# ключ банка -> название
P2P_BANKS: dict[str, str] = {
    "monobank": "Monobank",
    "privatbank": "PrivatBank",
    "alliance": "Alliance",
    "sense": "Sense Bank",
    "abank": "A-Bank",
    "pumb": "PUMB",
}

# шаблоны названий способов оплаты (регистр не важен). У A-Bank нужна граница слова: иначе под него попадёт «Idea Bank».
BANK_PATTERNS: dict[str, re.Pattern[str]] = {
    "monobank": re.compile(r"mono[\s_\-]*bank", re.I),
    "privatbank": re.compile(r"privat", re.I),
    "alliance": re.compile(r"alliance", re.I),
    "sense": re.compile(r"sense", re.I),
    "abank": re.compile(r"(?<![a-z])a[\s_\-]*bank", re.I),
    "pumb": re.compile(r"pumb", re.I),
}

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}


def banks_in(*names: str) -> set[str]:
    """Какие из наших банков упомянуты в названиях способов оплаты (карта и IBAN считаются одним банком)."""
    return {bank for name in names for bank, pattern in BANK_PATTERNS.items() if pattern.search(name)}


@dataclass(frozen=True, slots=True)
class P2PAd:
    price: Decimal
    available: Decimal  # сколько криптовалюты доступно в объявлении
    min_amount: Decimal  # лимиты одной сделки в гривнах
    max_amount: Decimal
    month_orders: int  # число сделок объявителя за последний период (месяц / 30 дней)
    finish_rate: Decimal  # доля завершённых сделок, 0..1
    is_merchant: bool = False

    def fits(self, amount: Decimal) -> bool:
        """Объявление принимает сделку на ``amount`` гривен: в лимитах и хватает объёма."""
        return self.min_amount <= amount <= self.max_amount and self.available * self.price >= amount


def rate_fraction(value: Any) -> Decimal:
    """Доля 0..1: площадки отдают 0.97, 97 или строку «97.68%» (KuCoin)."""
    is_percent = isinstance(value, str) and value.strip().endswith("%")
    number = to_decimal(value.strip().rstrip("%") if isinstance(value, str) else value)
    if number is None or number < 0:
        return Decimal(0)
    return number / 100 if is_percent or number > 1 else number


class P2PPlatform(ABC):
    name: str
    display_name: str
    assets: tuple[str, ...] = ("USDT", "BTC", "ETH")

    @abstractmethod
    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        """Объявления за гривны, сгруппированные по банкам (ключи ``P2P_BANKS``). Без сортировки и отбора.

        Бросает ``ProviderError`` (в том числе ``RateLimitedError``), если площадка недоступна.
        """

    def supports(self, asset: str) -> bool:
        return asset in self.assets
