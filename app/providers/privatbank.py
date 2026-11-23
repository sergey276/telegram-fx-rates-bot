"""PrivatBank: https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5

``coursid=5`` — наличный курс (отделения), ``coursid=11`` — безналичный (карты).
API возвращает только USD и EUR и **не** возвращает время котировки — это отражается в
``Quote.missing_fields()``, а бот честно сообщает об этом пользователю.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import BaseProvider
from app.utils.http import AsyncRateLimiter, HttpClient, ProviderError
from app.utils.symbols import to_decimal


def parse_privatbank(payload: Any, now: datetime | None = None) -> list[Quote]:
    if not isinstance(payload, list):
        raise ProviderError(f"PrivatBank: неожиданный ответ ({type(payload).__name__})")
    received = now or utcnow()
    quotes: list[Quote] = []
    for item in payload:
        base = item.get("ccy")
        quote_ccy = item.get("base_ccy")
        if not base or not quote_ccy:
            continue
        quote = Quote(
            source="privatbank",
            symbol=f"{base}/{quote_ccy}",
            kind=SourceKind.BANK,
            bid=to_decimal(item.get("buy")),
            ask=to_decimal(item.get("sale")),
            source_ts=None,
            received_at=received,
        )
        if quote.has_price:
            quotes.append(quote)
    return quotes


class PrivatBankProvider(BaseProvider):
    name = "privatbank"
    display_name = "PrivatBank"
    kind = SourceKind.BANK

    def __init__(self, http: HttpClient, base_url: str, coursid: int = 5) -> None:
        super().__init__(http)
        self._url = f"{base_url.rstrip('/')}/p24api/pubinfo"
        self._coursid = coursid
        self._limiter = AsyncRateLimiter(rate=1 / 5, burst=1)

    async def fetch_quotes(self, symbols: Sequence[str] = ()) -> list[Quote]:
        payload = await self.http.get_json(
            self._url, params={"exchange": "", "coursid": str(self._coursid)}, limiter=self._limiter
        )
        quotes = parse_privatbank(payload)
        if not quotes:
            raise ProviderError("PrivatBank: ответ не содержит ни одного курса")
        if symbols:
            wanted = set(symbols)
            quotes = [q for q in quotes if q.symbol in wanted]
        return quotes
