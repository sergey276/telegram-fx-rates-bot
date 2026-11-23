"""Сборка Bot и Dispatcher."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import BotCommand, ErrorEvent

from app.bot.context import AppContext
from app.bot.handlers import (
    admin,
    alerts,
    arbitrage,
    banks,
    charts,
    compare,
    crypto,
    menu,
    p2p,
    rates,
    settings,
)
from app.bot.middlewares import ThrottleMiddleware, UserMiddleware
from app.config import Settings
from app.i18n import t

log = logging.getLogger(__name__)

COMMANDS = (
    ("start", "Главное меню"),
    ("rates", "Курсы валют и криптовалют"),
    ("crypto", "Криптовалюты по биржам"),
    ("banks", "Курсы Monobank и PrivatBank"),
    ("compare", "Сравнить цены между источниками"),
    ("history", "График цены"),
    ("alerts", "Уведомления"),
    ("arbitrage", "Арбитражные возможности"),
    ("p2p", "P2P: покупка и продажа через банки"),
    ("settings", "Настройки"),
    ("help", "Справка"),
)


def create_bot(settings: Settings) -> Bot:
    return Bot(token=settings.bot_token.get_secret_value(), default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def create_dispatcher(ctx: AppContext) -> Dispatcher:
    storage: BaseStorage = RedisStorage(ctx.core.redis) if ctx.core.redis is not None else MemoryStorage()
    dp = Dispatcher(storage=storage, ctx=ctx)

    throttle, users = ThrottleMiddleware(ctx), UserMiddleware(ctx)
    for observer in (dp.message, dp.callback_query):
        observer.outer_middleware(throttle)
        observer.outer_middleware(users)

    dp.include_routers(
        admin.router, alerts.router, rates.router, crypto.router, banks.router, compare.router, charts.router,
        arbitrage.router, p2p.router, settings.router, menu.router, menu.fallback_router,
    )
    dp.errors.register(on_error)
    return dp


async def on_error(event: ErrorEvent) -> bool:
    log.error("Необработанная ошибка в обработчике: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query is not None:
            await update.callback_query.answer(t("ru", "err.generic"), show_alert=True)
        elif update.message is not None:
            await update.message.answer(t("ru", "err.generic"))
    except TelegramAPIError:
        pass
    return True


async def register_commands(bot: Bot) -> None:
    try:
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in COMMANDS])
    except TelegramAPIError as exc:
        log.warning("Не удалось зарегистрировать команды бота: %s", exc)


class Notifier:
    """Отправка уведомлений с соблюдением лимитов Telegram (не более ~20 сообщений в секунду)."""

    def __init__(self, bot: Bot, min_gap: float = 0.05) -> None:
        self._bot = bot
        self._gap = min_gap
        self._lock = asyncio.Lock()

    async def send(self, telegram_id: int, text: str) -> bool | None:
        async with self._lock:
            try:
                await self._bot.send_message(telegram_id, text, disable_web_page_preview=True)
                await asyncio.sleep(self._gap)
                return True
            except TelegramForbiddenError:
                log.info("пользователь %s заблокировал бота", telegram_id)
                return None
            except TelegramRetryAfter as exc:
                log.warning("Telegram просит подождать %s с", exc.retry_after)
                await asyncio.sleep(min(exc.retry_after, 30))
                return False
            except TelegramAPIError as exc:
                log.error("не удалось отправить уведомление %s: %s", telegram_id, exc)
                return False
