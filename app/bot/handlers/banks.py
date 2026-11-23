"""🏦 Банки: курсы Monobank и PrivatBank."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import ChartCb, CompareCb, Nav
from app.bot.context import AppContext
from app.bot.formatting import banks_text
from app.bot.keyboards import button, grid, markup, menu_row
from app.bot.utils import show
from app.services.users import UserCtx

router = Router(name="banks")


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    symbols = [s for s in ctx.users.active_watchlist(u) if s in ctx.assets.fiat]
    buttons = [button(f"🔄 {s}", CompareCb(symbol=s)) for s in symbols]
    buttons += [button(f"📈 {s}", ChartCb(step="period", symbol=s)) for s in symbols[:2]]
    rows = grid(buttons, 3) + [menu_row(u.lang, refresh=Nav(to="banks"))]
    await show(event, banks_text(ctx, u, symbols), markup(rows))


@router.message(Command("banks"))
async def cmd_banks(message: Message, ctx: AppContext, u: UserCtx) -> None:
    await screen(message, ctx, u)
