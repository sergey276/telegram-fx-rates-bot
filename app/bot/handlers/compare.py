"""🔄 Сравнение цен между источниками."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.analytics import Metric
from app.bot.callbacks import ChartCb, CompareCb, Nav
from app.bot.context import AppContext
from app.bot.formatting import compare_banks_text, compare_exchanges_text
from app.bot.keyboards import asset_buttons, button, grid, markup, menu_row
from app.bot.utils import command_args, parse_symbol_arg, show
from app.i18n import t
from app.services.users import UserCtx

router = Router(name="compare")


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    symbols = ctx.users.active_watchlist(u) or ctx.assets.all
    rows = grid(asset_buttons(symbols, lambda s: CompareCb(symbol=s)), 3)
    rows.append(menu_row(u.lang))
    await show(event, t(u.lang, "compare.pick"), markup(rows))


async def detail(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, symbol: str, metric: Metric) -> None:
    if symbol in ctx.assets.fiat:
        text = compare_banks_text(ctx, u, symbol)
        rows = [[button(t(u.lang, "menu.charts"), ChartCb(step="period", symbol=symbol))]]
    else:
        text = compare_exchanges_text(ctx, u, symbol, metric)
        rows = [
            [
                button(("✅ " if m is metric else "") + t(u.lang, f"metric.btn_{m.value}"), CompareCb(symbol=symbol, metric=m.value))
                for m in Metric
            ],
            [button(t(u.lang, "menu.charts"), ChartCb(step="period", symbol=symbol))],
        ]
    rows.append(menu_row(u.lang, refresh=CompareCb(symbol=symbol, metric=metric.value), back=Nav(to="compare")))
    await show(event, text, markup(rows))


@router.message(Command("compare"))
async def cmd_compare(message: Message, ctx: AppContext, u: UserCtx) -> None:
    args = command_args(message)
    if args:
        symbol = parse_symbol_arg(args[0], ctx.assets.all)
        if symbol is None:
            await message.answer(t(u.lang, "err.unknown_symbol", symbol=args[0][:20].replace("<", "")))
            return
        await detail(message, ctx, u, symbol, Metric.LAST)
        return
    await screen(message, ctx, u)


@router.callback_query(CompareCb.filter())
async def on_compare(cb: CallbackQuery, callback_data: CompareCb, ctx: AppContext, u: UserCtx) -> None:
    symbol = callback_data.symbol
    if symbol not in ctx.assets.all:
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
        return
    try:
        metric = Metric(callback_data.metric)
    except ValueError:
        metric = Metric.LAST
    await detail(cb, ctx, u, symbol, metric)
