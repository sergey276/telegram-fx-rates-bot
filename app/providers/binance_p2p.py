"""Binance P2P: ``POST https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search`` (публичный веб-эндпоинт, не официальный API).

``tradeType`` в запросе — с точки зрения пользователя: ``BUY`` — вы покупаете (в ответе объявления продавцов).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from app.providers.p2p_common import BROWSER_HEADERS, P2P_BANKS, P2PAd, P2PPlatform, Side, rate_fraction
from app.utils.http import AsyncRateLimiter, HttpClient, ProviderError
from app.utils.symbols import to_decimal

URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
SUCCESS_CODE = "000000"

# банк -> идентификаторы способов оплаты Binance P2P (карта и IBAN), сняты с живого ответа; несколько значений = «любой из»
BINANCE_PAY_TYPES: dict[str, tuple[str, ...]] = {
    "monobank": ("Monobank", "Monobankiban"),
    "privatbank": ("PrivatBank", "PrivatBankIBAN"),
    "alliance": ("alliancecard",),
    "sense": ("SenseSuperApp",),
    "abank": ("ABank", "AbankIBAN"),
    "pumb": ("PUMBBank",),
}


def parse_ads(payload: Any) -> list[P2PAd]:
    """Разбирает ответ ``adv/search``. Объявления с некорректными числами пропускаются."""
    if not isinstance(payload, dict):
        raise ProviderError(f"Binance P2P: неожиданный ответ ({type(payload).__name__})")
    if payload.get("code") != SUCCESS_CODE:
        raise ProviderError(f"Binance P2P: code={payload.get('code')} {payload.get('message')}")
    ads: list[P2PAd] = []
    for item in payload.get("data") or []:
        adv, user = item.get("adv") or {}, item.get("advertiser") or {}
        price = to_decimal(adv.get("price"))
        available = to_decimal(adv.get("tradableQuantity"))
        low, high = to_decimal(adv.get("minSingleTransAmount")), to_decimal(adv.get("maxSingleTransAmount"))
        if price is None or price <= 0 or available is None or low is None or high is None:
            continue
        ads.append(
            P2PAd(price, available, low, high, int(user.get("monthOrderCount") or 0),
                  rate_fraction(user.get("monthFinishRate")), user.get("userType") == "merchant")
        )
    return ads


class BinanceP2P(P2PPlatform):
    name = "binance"
    display_name = "Binance"

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._limiter = AsyncRateLimiter(rate=4, burst=4)

    async def _one(self, asset: str, side: Side, pay_types: tuple[str, ...], amount: Decimal) -> list[P2PAd]:
        body: dict[str, Any] = {
            "fiat": "UAH", "page": 1, "rows": 20, "tradeType": side.value, "asset": asset, "countries": [],
            "proMerchantAds": False, "shieldMerchantAds": False, "publisherType": None, "payTypes": list(pay_types),
            "classifies": ["mass", "profession"], "transAmount": str(amount),  # фильтр по сумме — на стороне Binance
        }
        payload = await self._http.post_json(URL, json=body, limiter=self._limiter, headers=BROWSER_HEADERS)
        return parse_ads(payload)

    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        banks = list(P2P_BANKS)
        results = await asyncio.gather(*(self._one(asset, side, BINANCE_PAY_TYPES[b], amount) for b in banks))
        return dict(zip(banks, results, strict=True))
