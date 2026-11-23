"""Monobank: https://api.monobank.ua/bank/currency

Данные обновляются не чаще раза в 5 минут; запрос чаще раза в минуту получает HTTP 429.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.domain import Quote, SourceKind, utcnow
from app.providers.base import BaseProvider
from app.utils.http import AsyncRateLimiter, HttpClient, ProviderError
from app.utils.symbols import ISO_NUMERIC_TO_ALPHA, to_decimal


def parse_monobank(payload: Any, now: datetime | None = None) -> list[Quote]:
    """Преобразует ответ ``/bank/currency`` в котировки.

    Записи без ``rateBuy``/``rateSell`` (только ``rateCross``) сохраняются с ``bid=ask=None`` и ``cross_rate``:
    покупка/продажа у банка для них недоступны, и мы их не придумываем.
    """
    if not isinstance(payload, list):
        # При лимите запросов Monobank отвечает объектом {"errText": "..."}
        message = payload.get("errText") if isinstance(payload, dict) else type(payload).__name__
        raise ProviderError(f"Monobank: неожиданный ответ: {message}")
    received = now or utcnow()
    quotes: list[Quote] = []
    for item in payload:
        base = ISO_NUMERIC_TO_ALPHA.get(item.get("currencyCodeA"))
        quote_ccy = ISO_NUMERIC_TO_ALPHA.get(item.get("currencyCodeB"))
        if base is None or quote_ccy is None:
            continue
        ts = item.get("date")
        source_ts = datetime.fromtimestamp(ts, UTC) if isinstance(ts, int | float) and ts > 0 else None
        quote = Quote(
            source="monobank",
            symbol=f"{base}/{quote_ccy}",
            kind=SourceKind.BANK,
            bid=to_decimal(item.get("rateBuy")),
            ask=to_decimal(item.get("rateSell")),
            cross_rate=to_decimal(item.get("rateCross")),
            source_ts=source_ts,
            received_at=received,
        )
        if quote.has_price:
            quotes.append(quote)
    return quotes


class MonobankProvider(BaseProvider):
    name = "monobank"
    display_name = "Monobank"
    kind = SourceKind.BANK

    def __init__(self, http: HttpClient, base_url: str, min_interval: float = 60.0) -> None:
        super().__init__(http)
        self._url = f"{base_url.rstrip('/')}/bank/currency"
        # Жёсткая защита от бессмысленных запросов: не чаще раза в минуту (лимит API).
        self._limiter = AsyncRateLimiter(rate=1.0 / min_interval, burst=1)

    async def fetch_quotes(self, symbols: Sequence[str] = ()) -> list[Quote]:
        payload = await self.http.get_json(self._url, limiter=self._limiter)
        quotes = parse_monobank(payload)
        if not quotes:
            raise ProviderError("Monobank: ответ не содержит ни одного курса")
        if symbols:
            wanted = set(symbols)
            quotes = [q for q in quotes if q.symbol in wanted]
        return quotes
