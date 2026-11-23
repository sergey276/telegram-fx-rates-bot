"""Вспомогательные функции обработчиков."""

from __future__ import annotations

import contextlib
import logging
from decimal import Decimal, InvalidOperation

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, InputMediaPhoto, Message

from app.utils.symbols import InvalidSymbol, normalize_symbol

log = logging.getLogger(__name__)

MAX_TEXT = 4000


def clip(text: str, limit: int = MAX_TEXT) -> str:
    """Обрезает по границе строки: HTML-теги в наших сообщениях не пересекают строки, поэтому разметка не ломается."""
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit - 2)
    if cut <= 0:
        cut = limit - 2
    return text[:cut] + "\n…"


async def show(event: Message | CallbackQuery, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Для кнопки редактирует сообщение, для команды отправляет новое. Устойчиво к «не изменилось» и к фото."""
    text = clip(text)
    if isinstance(event, CallbackQuery):
        message = event.message
        if not isinstance(message, Message):
            await event.answer()
            return
        if message.photo:  # под графиком нельзя редактировать текст — заменяем сообщение
            await _replace_message(message, text, reply_markup)
            await event.answer()
            return
        try:
            await message.edit_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        except TelegramBadRequest as exc:
            reason = str(exc).lower()
            if "message is not modified" in reason:
                pass
            elif "no text in the message" in reason or "message can't be edited" in reason:
                await _replace_message(message, text, reply_markup)
            else:
                raise
        await event.answer()
        return
    await event.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


async def _replace_message(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await message.answer(text, reply_markup=reply_markup, disable_web_page_preview=True)


async def show_photo(
    event: Message | CallbackQuery, png: bytes, caption: str, reply_markup: InlineKeyboardMarkup | None = None
) -> None:
    """Отправляет график; при нажатии кнопки под графиком подменяет картинку в том же сообщении."""
    caption = clip(caption, 1000)
    file = BufferedInputFile(png, filename="chart.png")
    if isinstance(event, CallbackQuery):
        message = event.message
        if isinstance(message, Message):
            if message.photo:
                try:
                    await message.edit_media(
                        InputMediaPhoto(media=file, caption=caption, parse_mode="HTML"), reply_markup=reply_markup
                    )
                    await event.answer()
                    return
                except TelegramBadRequest as exc:
                    if "message is not modified" in str(exc).lower():
                        await event.answer()
                        return
                    raise
            await message.answer_photo(file, caption=caption, reply_markup=reply_markup)
            with contextlib.suppress(TelegramBadRequest):
                await message.delete()
        await event.answer()
        return
    await event.answer_photo(file, caption=caption, reply_markup=reply_markup)


def command_args(message: Message) -> list[str]:
    text = message.text or ""
    parts = text.split()[1:]
    return [p[:32] for p in parts[:4]]


def parse_symbol_arg(raw: str, known: list[str]) -> str | None:
    """``btc``, ``BTC/USDT``, ``usd`` -> символ из каталога или None."""
    try:
        symbol = normalize_symbol(raw)
    except InvalidSymbol:
        symbol = None
    if symbol and symbol in known:
        return symbol
    token = raw.strip().upper()
    if token.isalnum():
        for candidate in known:
            if candidate.split("/")[0] == token:
                return candidate
    return None


def parse_decimal(raw: str) -> Decimal | None:
    cleaned = raw.strip().replace(" ", "").replace(" ", "").replace(" ", "").replace(",", ".")
    if not cleaned or len(cleaned) > 24:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    return value if value.is_finite() else None
