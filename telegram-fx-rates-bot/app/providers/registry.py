"""Сборка провайдеров по настройкам."""

from __future__ import annotations

from app.config import Settings
from app.providers.base import BaseProvider
from app.providers.binance import BinanceProvider
from app.providers.bingx import BingxProvider
from app.providers.bitget import BitgetProvider
from app.providers.bybit import BybitProvider
from app.providers.kucoin import KucoinProvider
from app.providers.monobank import MonobankProvider
from app.providers.okx import OkxProvider
from app.providers.privatbank import PrivatBankProvider
from app.utils.http import AsyncRateLimiter, HttpClient

# Запросов в секунду на источник — заметно ниже опубликованных лимитов бирж.
_EXCHANGE_RATES = {"binance": 10, "bybit": 8, "okx": 5, "bitget": 8, "bingx": 5, "kucoin": 8}


def build_providers(settings: Settings, http: HttpClient) -> dict[str, BaseProvider]:
    def limiter(name: str) -> AsyncRateLimiter:
        rate = _EXCHANGE_RATES[name]
        return AsyncRateLimiter(rate=rate, burst=rate)

    all_providers: dict[str, BaseProvider] = {
        "monobank": MonobankProvider(http, settings.monobank_url),
        "privatbank": PrivatBankProvider(http, settings.privatbank_url, settings.privatbank_coursid),
        "binance": BinanceProvider(http, settings.binance_rest_url, limiter("binance"), settings.binance_ws_url),
        "bybit": BybitProvider(http, settings.bybit_rest_url, limiter("bybit"), settings.bybit_ws_url),
        "okx": OkxProvider(http, settings.okx_rest_url, limiter("okx"), settings.okx_ws_url),
        "bitget": BitgetProvider(http, settings.bitget_rest_url, limiter("bitget"), settings.bitget_ws_url),
        "bingx": BingxProvider(http, settings.bingx_rest_url, limiter("bingx"), settings.bingx_ws_url),
        "kucoin": KucoinProvider(http, settings.kucoin_rest_url, limiter("kucoin")),
    }
    return {name: p for name, p in all_providers.items() if name in settings.enabled_sources}
