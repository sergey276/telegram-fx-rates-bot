"""Типы уведомлений и их текстовое описание."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from app.domain import source_name
from app.i18n import t
from app.utils.fmt import format_pct, format_price


class AlertType(StrEnum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    PCT_CHANGE = "pct_change"
    SPREAD = "spread"
    ARBITRAGE = "arbitrage"

    @property
    def needs_source(self) -> bool:
        return self in (AlertType.PRICE_ABOVE, AlertType.PRICE_BELOW, AlertType.PCT_CHANGE)

    @property
    def is_percent(self) -> bool:
        return self in (AlertType.PCT_CHANGE, AlertType.SPREAD, AlertType.ARBITRAGE)

    @property
    def crypto_only(self) -> bool:
        return self in (AlertType.SPREAD, AlertType.ARBITRAGE)


PCT_MIN, PCT_MAX = Decimal("0.01"), Decimal("100")
PCT_WINDOWS = (5, 15, 60, 240, 1440)


def window_label(lang: str, minutes: int | None) -> str:
    if minutes is None:
        return "—"
    if minutes % 60 == 0:
        return t(lang, "alerts.window_h", h=minutes // 60)
    return t(lang, "alerts.window", m=minutes)


def describe(lang: str, type_: str, symbol: str, source: str | None, threshold: Decimal, window: int | None) -> str:
    kind = AlertType(type_)
    value = format_pct(threshold) if kind.is_percent else format_price(threshold)
    return t(
        lang,
        f"alerts.desc.{kind.value}",
        symbol=symbol,
        source=source_name(source) if source else "",
        value=value,
        window=window_label(lang, window),
    )
