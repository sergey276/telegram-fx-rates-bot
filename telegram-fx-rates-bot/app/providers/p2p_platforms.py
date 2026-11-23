"""P2P-адаптеры Bybit, OKX, KuCoin и Bitget (публичные веб-эндпоинты сайтов, формат проверен живыми запросами).

Все четыре ответа приводятся к ``P2PAd``; разбор вынесен в чистые функции ``parse_*`` для тестов на реальных образцах.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.providers.p2p_common import (
    BROWSER_HEADERS,
    P2PAd,
    P2PPlatform,
    Side,
    banks_in,
    rate_fraction,
)
from app.utils.http import AsyncRateLimiter, HttpClient, ProviderError
from app.utils.symbols import to_decimal


def _ad(price: Any, available: Any, low: Any, high: Any, orders: Any, rate: Any, merchant: bool = False) -> P2PAd | None:
    p, a, lo, hi = to_decimal(price), to_decimal(available), to_decimal(low), to_decimal(high)
    if p is None or p <= 0 or a is None or lo is None or hi is None:
        return None
    try:
        count = int(float(orders or 0))
    except (TypeError, ValueError):
        count = 0
    return P2PAd(p, a, lo, hi, count, rate_fraction(rate), merchant)


# --------------------------------------------------------------------------- Bybit
BYBIT_PAYMENT_IDS: dict[str, tuple[str, ...]] = {  # id способов оплаты из queryAllPaymentList (карта и IBAN)
    "monobank": ("43", "659"),
    "privatbank": ("60", "660", "661"),
    "sense": ("623",),
    "abank": ("1",),
    "pumb": ("61",),
}  # Alliance в списке способов оплаты Bybit для UAH отсутствует


def parse_bybit(payload: Any) -> list[P2PAd]:
    if not isinstance(payload, dict):
        raise ProviderError(f"Bybit P2P: неожиданный ответ ({type(payload).__name__})")
    if payload.get("ret_code") != 0:
        raise ProviderError(f"Bybit P2P: ret_code={payload.get('ret_code')} {payload.get('ret_msg')}")
    ads = (
        _ad(i.get("price"), i.get("lastQuantity"), i.get("minAmount"), i.get("maxAmount"),
            i.get("recentOrderNum"), i.get("recentExecuteRate"), i.get("userType") == "ORG")
        for i in (payload.get("result") or {}).get("items") or []
    )
    return [a for a in ads if a is not None]


class BybitP2P(P2PPlatform):
    name = "bybit"
    display_name = "Bybit"
    URL = "https://api2.bybit.com/fiat/otc/item/online"

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._limiter = AsyncRateLimiter(rate=3, burst=3)

    async def _one(self, asset: str, side: Side, ids: tuple[str, ...], amount: Decimal) -> list[P2PAd]:
        body = {
            "userId": "", "tokenId": asset, "currencyId": "UAH", "payment": list(ids),
            "side": "1" if side is Side.BUY else "0",  # 1 — вы покупаете, 0 — продаёте
            "size": "20", "page": "1", "amount": str(amount), "authMaker": False, "canTrade": False,
        }
        return parse_bybit(await self._http.post_json(self.URL, json=body, limiter=self._limiter, headers=BROWSER_HEADERS))

    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        banks = list(BYBIT_PAYMENT_IDS)
        results = await asyncio.gather(*(self._one(asset, side, BYBIT_PAYMENT_IDS[b], amount) for b in banks))
        return dict(zip(banks, results, strict=True))


# --------------------------------------------------------------------------- OKX
def parse_okx(payload: Any, side: Side) -> dict[str, list[P2PAd]]:
    """OKX отдаёт все объявления одним ответом с названиями способов оплаты — группируем по банкам сами."""
    if not isinstance(payload, dict):
        raise ProviderError(f"OKX P2P: неожиданный ответ ({type(payload).__name__})")
    if payload.get("code") != 0:
        raise ProviderError(f"OKX P2P: code={payload.get('code')} {payload.get('msg') or payload.get('error_message')}")
    key = "sell" if side is Side.BUY else "buy"  # у OKX список назван по стороне МЕРЧАНТА
    grouped: dict[str, list[P2PAd]] = defaultdict(list)
    for item in (payload.get("data") or {}).get(key) or []:
        ad = _ad(item.get("price"), item.get("availableAmount"), item.get("quoteMinAmountPerOrder"),
                 item.get("quoteMaxAmountPerOrder"), item.get("completedOrderQuantity"), item.get("completedRate"))
        if ad is None:
            continue
        for bank in banks_in(*[str(m) for m in item.get("paymentMethods") or []]):
            grouped[bank].append(ad)
    return dict(grouped)


class OkxP2P(P2PPlatform):
    name = "okx"
    display_name = "OKX"
    URL = "https://www.okx.com/v3/c2c/tradingOrders/books"

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._limiter = AsyncRateLimiter(rate=2, burst=2)

    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        params = {
            "quoteCurrency": "UAH", "baseCurrency": asset.lower(), "side": "sell" if side is Side.BUY else "buy",
            "paymentMethod": "all", "userType": "all", "showTrade": "false", "showFollow": "false",
            "showAlreadyTraded": "false", "isAbleFilter": "false",
        }
        payload = await self._http.get_json(self.URL, params=params, limiter=self._limiter, headers=BROWSER_HEADERS)
        return parse_okx(payload, side)


# --------------------------------------------------------------------------- KuCoin
def parse_kucoin(payload: Any) -> dict[str, list[P2PAd]]:
    if not isinstance(payload, dict):
        raise ProviderError(f"KuCoin P2P: неожиданный ответ ({type(payload).__name__})")
    if not payload.get("success"):
        raise ProviderError(f"KuCoin P2P: code={payload.get('code')} {payload.get('msg')}")
    grouped: dict[str, list[P2PAd]] = defaultdict(list)
    for item in payload.get("items") or []:
        ad = _ad(item.get("floatPrice"), item.get("currencyBalanceQuantity"), item.get("limitMinQuote"),
                 item.get("limitMaxQuote"), item.get("dealOrderNum"), item.get("dealOrderRate"))
        if ad is None:
            continue
        codes = [str(p.get("payTypeCode") or "") for p in item.get("adPayTypes") or []]
        for bank in banks_in(*codes):
            grouped[bank].append(ad)
    return dict(grouped)


class KucoinP2P(P2PPlatform):
    name = "kucoin"
    display_name = "KuCoin"
    URL = "https://www.kucoin.com/_api/otc/ad/list"
    MAX_PAGES = 3
    PAGE_SIZE = 30

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        self._limiter = AsyncRateLimiter(rate=2, burst=2)

    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        grouped: dict[str, list[P2PAd]] = defaultdict(list)
        for page in range(1, self.MAX_PAGES + 1):
            params = {
                "currency": asset, "legal": "UAH", "side": "SELL" if side is Side.BUY else "BUY",  # сторона мерчанта
                "page": str(page), "pageSize": str(self.PAGE_SIZE), "status": "PUTUP", "lang": "en_US",
            }
            payload = await self._http.get_json(self.URL, params=params, limiter=self._limiter, headers=BROWSER_HEADERS)
            for bank, ads in parse_kucoin(payload).items():
                grouped[bank] += ads
            if len(payload.get("items") or []) < self.PAGE_SIZE:
                break
        return dict(grouped)


# --------------------------------------------------------------------------- Bitget
def parse_bitget(payload: Any) -> tuple[dict[str, list[P2PAd]], bool]:
    """Возвращает (объявления по банкам, есть ли следующая страница)."""
    if not isinstance(payload, dict):
        raise ProviderError(f"Bitget P2P: неожиданный ответ ({type(payload).__name__})")
    if payload.get("code") != "00000":
        raise ProviderError(f"Bitget P2P: code={payload.get('code')} {payload.get('msg')}")
    data = payload.get("data") or {}
    grouped: dict[str, list[P2PAd]] = defaultdict(list)
    for item in data.get("dataList") or []:
        ad = _ad(item.get("price"), item.get("lastAmount"), item.get("minAmount"), item.get("maxAmount"),
                 item.get("thirtyTunoverNum"), item.get("thirtyCompletionRate"), bool(item.get("certifiedMerchant")))
        if ad is None:
            continue
        names = [str(m.get("paymethodName") or "") for m in item.get("paymethodInfo") or []]
        for bank in banks_in(*names):
            grouped[bank].append(ad)
    return dict(grouped), bool(data.get("hasNextPage"))


class BitgetP2P(P2PPlatform):
    name = "bitget"
    display_name = "Bitget"
    URL = "https://www.bitget.com/v1/p2p/pub/adv/queryAdvList"
    MAX_PAGES = 3
    HEADERS = {**BROWSER_HEADERS, "Origin": "https://www.bitget.com", "Referer": "https://www.bitget.com/p2p-trade"}

    def __init__(self, http: HttpClient) -> None:
        self._http = http
        # Bitget отвечает HTTP 429 уже при нескольких запросах подряд — держим консервативный темп
        self._limiter = AsyncRateLimiter(rate=1 / 1.5, burst=1)

    async def fetch(self, asset: str, side: Side, amount: Decimal) -> dict[str, list[P2PAd]]:
        grouped: dict[str, list[P2PAd]] = defaultdict(list)
        for page in range(1, self.MAX_PAGES + 1):
            body = {"side": 1 if side is Side.BUY else 2, "pageNo": page, "pageSize": 20, "coinCode": asset,
                    "fiatCode": "UAH", "languageType": 6}
            payload = await self._http.post_json(self.URL, json=body, limiter=self._limiter, headers=self.HEADERS)
            part, has_next = parse_bitget(payload)
            for bank, ads in part.items():
                grouped[bank] += ads
            if not has_next:
                break
        return dict(grouped)


def all_platforms(http: HttpClient) -> list[P2PPlatform]:
    from app.providers.binance_p2p import BinanceP2P

    return [BinanceP2P(http), BybitP2P(http), OkxP2P(http), KucoinP2P(http), BitgetP2P(http)]

