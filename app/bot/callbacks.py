"""Фабрики callback-данных (лимит Telegram — 64 байта)."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Nav(CallbackData, prefix="nav"):
    to: str


class CryptoCb(CallbackData, prefix="cr"):
    symbol: str


class CompareCb(CallbackData, prefix="cp"):
    symbol: str = ""
    metric: str = "last"


class ChartCb(CallbackData, prefix="ch"):
    step: str  # asset | period | show
    symbol: str = ""
    period: str = ""
    source: str = ""


class AlertCb(CallbackData, prefix="al"):
    act: str
    v: str = ""


class ArbCb(CallbackData, prefix="ar"):
    act: str  # list | detail | thr | set
    symbol: str = ""
    v: str = ""


class P2PCb(CallbackData, prefix="p2"):
    act: str  # view | bank | refresh
    asset: str = "USDT"
    amount: int = 5000
    bank: str = ""


class SetCb(CallbackData, prefix="st"):
    act: str
    v: str = ""
    page: int = 0


class AdminCb(CallbackData, prefix="ad"):
    act: str
    v: str = ""
