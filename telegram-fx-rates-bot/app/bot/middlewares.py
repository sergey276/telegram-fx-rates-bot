"""Middleware: ограничение частоты запросов и загрузка пользователя."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.context import AppContext
from app.i18n import normalize_lang, t

log = logging.getLogger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class ThrottleMiddleware(BaseMiddleware):
    """Не даёт одному пользователю заваливать бота запросами (лимит из настроек, окно фиксированное)."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user is None or user.is_bot:
            return await handler(event, data)
        if await self._ctx.core.rate_limiter.allow(user.id):
            return await handler(event, data)
        log.debug("rate limit: пользователь %s", user.id)
        if isinstance(event, CallbackQuery):
            lang = normalize_lang(user.language_code, self._ctx.settings.default_language)
            await event.answer(t(lang, "err.throttled"))
        return None  # сообщения молча отбрасываем: ответ на каждое ухудшил бы ситуацию


class UserMiddleware(BaseMiddleware):
    """Регистрирует пользователя при первом обращении и кладёт его настройки в ``data['u']``."""

    def __init__(self, ctx: AppContext) -> None:
        self._ctx = ctx

    async def __call__(self, handler: Handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        chat = event.chat if isinstance(event, Message) else (
            event.message.chat if isinstance(event, CallbackQuery) and event.message else None
        )
        if user is None or user.is_bot or (chat is not None and chat.type != "private"):
            return None  # бот работает только в личных сообщениях
        if not self._ctx.runtime.get("signups_enabled") and not await self._ctx.users.exists(user.id):
            if isinstance(event, Message):
                await event.answer("🔒 Регистрация новых пользователей временно закрыта.")
            return None
        u = await self._ctx.users.ensure(user.id, user.username, user.first_name, user.language_code)
        if u.is_blocked and not u.is_admin:
            return None
        data["u"] = u
        return await handler(event, data)
