"""📈 Графики и /history."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from app.bot.callbacks import ChartCb, Nav
from app.bot.context import AppContext
from app.bot.keyboards import asset_buttons, button, grid, markup, menu_row
from app.bot.utils import command_args, parse_symbol_arg, show, show_photo
from app.domain import source_name
from app.i18n import t
from app.services.chart_service import PERIODS
from app.services.users import UserCtx
from app.utils.fmt import format_age, format_pct, format_price

log = logging.getLogger(__name__)
router = Router(name="charts")


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    symbols = ctx.users.active_watchlist(u) or ctx.assets.all
    rows = grid(asset_buttons(symbols, lambda s: ChartCb(step="period", symbol=s)), 3)
    rows.append(menu_row(u.lang))
    await show(event, t(u.lang, "charts.pick"), markup(rows))


def _period_row(u: UserCtx, symbol: str, source: str, current: str) -> list[InlineKeyboardButton]:
    return [
        button(("✅ " if p == current else "") + t(u.lang, f"period.{p}"), ChartCb(step="show", symbol=symbol, period=p, source=source))
        for p in PERIODS
    ]


async def pick_period(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, symbol: str) -> None:
    rows = [_period_row(u, symbol, "", u.chart_period)]
    rows.append(menu_row(u.lang, back=Nav(to="charts")))
    await show(event, t(u.lang, "charts.pick_period", symbol=symbol), markup(rows))


async def show_chart(
    event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, symbol: str, period: str, source: str = ""
) -> None:
    sources = await ctx.charts.sources_for(symbol)
    if not sources:
        rows = [_period_row(u, symbol, "", period), menu_row(u.lang, back=Nav(to="charts"))]
        await show(event, t(u.lang, "charts.no_data", symbol=symbol, source="—"), markup(rows))
        return
    if source not in sources:
        source = sources[0]

    result = await ctx.charts.build(symbol, source, period, u.chart_theme, u.lang, ctx.settings.timezone)
    keyboard = [_period_row(u, symbol, source, period)]
    if len(sources) > 1:
        keyboard += grid(
            [
                button(("✅ " if s == source else "") + source_name(s), ChartCb(step="show", symbol=symbol, period=period, source=s))
                for s in sources
            ],
            3,
        )
    keyboard.append(menu_row(u.lang, refresh=ChartCb(step="show", symbol=symbol, period=period, source=source), back=Nav(to="charts")))

    if result is None:
        await show(event, t(u.lang, "charts.no_data", symbol=symbol, source=source_name(source)), markup(keyboard))
        return
    s = result.stats
    caption = t(
        u.lang, "charts.caption", symbol=symbol, source=source_name(source), period=t(u.lang, f"period.{period}"),
        min=format_price(s.minimum), max=format_price(s.maximum), now=format_price(s.last),
        change=format_pct(s.change_pct, 2, True),
    )
    if result.covered < result.requested * 0.8:
        caption += "\n" + t(u.lang, "charts.partial", span=format_age(result.covered.total_seconds(), u.lang),
                            period=t(u.lang, f"period.{period}"))
    await show_photo(event, result.png, caption, markup(keyboard))


@router.message(Command("history"))
async def cmd_history(message: Message, ctx: AppContext, u: UserCtx) -> None:
    args = command_args(message)
    if not args:
        await screen(message, ctx, u)
        return
    symbol = parse_symbol_arg(args[0], ctx.assets.all)
    if symbol is None:
        await message.answer(t(u.lang, "err.unknown_symbol", symbol=args[0][:20].replace("<", "")))
        return
    period = args[1].lower() if len(args) > 1 and args[1].lower() in PERIODS else u.chart_period
    await show_chart(message, ctx, u, symbol, period)


@router.callback_query(ChartCb.filter())
async def on_chart(cb: CallbackQuery, callback_data: ChartCb, ctx: AppContext, u: UserCtx) -> None:
    symbol = callback_data.symbol
    if symbol not in ctx.assets.all:
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
        return
    if callback_data.step == "period":
        await pick_period(cb, ctx, u, symbol)
        return
    period = callback_data.period if callback_data.period in PERIODS else u.chart_period
    await show_chart(cb, ctx, u, symbol, period, callback_data.source)
