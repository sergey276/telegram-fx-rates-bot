"""📊 Курсы валют: сводка по банкам и биржам."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import Nav
from app.bot.context import AppContext
from app.bot.formatting import rates_text
from app.bot.keyboards import markup, menu_row
from app.bot.utils import show
from app.services.users import UserCtx

router = Router(name="rates")


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    await show(event, rates_text(ctx, u), markup([menu_row(u.lang, refresh=Nav(to="rates"))]))


@router.message(Command("rates"))
async def cmd_rates(message: Message, ctx: AppContext, u: UserCtx) -> None:
    await screen(message, ctx, u)
