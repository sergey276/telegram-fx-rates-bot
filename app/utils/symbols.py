"""Работа с символами пар и валютами."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

# ISO 4217: числовой код -> буквенный (Monobank кодирует валюты числами).
ISO_NUMERIC_TO_ALPHA: dict[int, str] = {
    980: "UAH", 840: "USD", 978: "EUR", 826: "GBP", 985: "PLN", 756: "CHF", 203: "CZK",
    124: "CAD", 392: "JPY", 36: "AUD", 156: "CNY", 949: "TRY", 348: "HUF", 578: "NOK",
    752: "SEK", 208: "DKK", 946: "RON", 975: "BGN", 981: "GEL", 51: "AMD", 944: "AZN",
    498: "MDL", 643: "RUB", 933: "BYN", 398: "KZT", 702: "SGD", 344: "HKD", 376: "ILS",
    784: "AED", 818: "EGP", 356: "INR", 410: "KRW", 458: "MYR", 764: "THB",
    986: "BRL", 484: "MXN", 710: "ZAR", 554: "NZD", 352: "ISK", 191: "HRK", 417: "KGS",
    860: "UZS", 972: "TJS", 934: "TMT", 504: "MAD", 788: "TND", 682: "SAR",
}

FIAT_CODES = frozenset(ISO_NUMERIC_TO_ALPHA.values())
CRYPTO_QUOTES = ("USDT", "USDC", "BTC", "ETH")

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}/[A-Z0-9]{2,12}$")


class InvalidSymbol(ValueError):
    pass


def normalize_symbol(raw: str) -> str:
    """``btc-usdt`` / ``BTCUSDT`` / ``btc/usdt`` -> ``BTC/USDT``. Бросает InvalidSymbol."""
    text = raw.strip().upper().replace("-", "/").replace("_", "/").replace(" ", "")
    if "/" not in text:
        for quote in (*CRYPTO_QUOTES, *sorted(FIAT_CODES)):
            if text.endswith(quote) and len(text) > len(quote):
                text = f"{text[: -len(quote)]}/{quote}"
                break
    if not _SYMBOL_RE.match(text):
        raise InvalidSymbol(raw)
    return text


def split_symbol(symbol: str) -> tuple[str, str]:
    base, _, quote = symbol.partition("/")
    return base, quote


def is_fiat_pair(symbol: str) -> bool:
    base, quote = split_symbol(symbol)
    return base in FIAT_CODES and quote in FIAT_CODES


def asset_kind(symbol: str) -> str:
    return "fiat" if is_fiat_pair(symbol) else "crypto"


def to_native(symbol: str, sep: str = "") -> str:
    """``BTC/USDT`` -> ``BTCUSDT`` (sep="") или ``BTC-USDT`` (sep="-")."""
    base, quote = split_symbol(symbol)
    return f"{base}{sep}{quote}"


def native_map(symbols: list[str] | tuple[str, ...], sep: str = "", upper: bool = True) -> dict[str, str]:
    """Словарь {родной символ биржи: внутренний символ}."""
    mapping = {}
    for symbol in symbols:
        native = to_native(symbol, sep)
        mapping[native if upper else native.lower()] = symbol
    return mapping


def to_decimal(value: Any) -> Decimal | None:
    """Безопасное преобразование ответа API в Decimal; пустые значения -> None."""
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None
