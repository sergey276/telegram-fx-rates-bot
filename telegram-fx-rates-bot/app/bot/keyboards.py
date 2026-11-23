"""Inline-клавиатуры."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import Nav
from app.i18n import t

MENU_ITEMS = (
    ("rates", "menu.rates"),
    ("crypto", "menu.crypto"),
    ("banks", "menu.banks"),
    ("compare", "menu.compare"),
    ("charts", "menu.charts"),
    ("alerts", "menu.alerts"),
    ("arbitrage", "menu.arbitrage"),
    ("p2p", "menu.p2p"),
    ("settings", "menu.settings"),
)


def button(text: str, data: CallbackData | str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data if isinstance(data, str) else data.pack())


def markup(rows: Iterable[Iterable[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def main_menu(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for target, key in MENU_ITEMS:
        builder.button(text=t(lang, key), callback_data=Nav(to=target))
    builder.adjust(2)
    return builder.as_markup()


def menu_row(lang: str, refresh: CallbackData | None = None, back: CallbackData | None = None) -> list[InlineKeyboardButton]:
    row = []
    if back is not None:
        row.append(button(t(lang, "btn.back"), back))
    if refresh is not None:
        row.append(button(t(lang, "btn.refresh"), refresh))
    row.append(button(t(lang, "btn.menu"), Nav(to="home")))
    return row


def grid(buttons: list[InlineKeyboardButton], columns: int = 3) -> list[list[InlineKeyboardButton]]:
    return [buttons[i : i + columns] for i in range(0, len(buttons), columns)]


def asset_buttons(symbols: Iterable[str], factory: Callable[[str], CallbackData], label: Callable[[str], str] | None = None) -> list[InlineKeyboardButton]:
    return [button(label(s) if label else s, factory(s)) for s in symbols]
