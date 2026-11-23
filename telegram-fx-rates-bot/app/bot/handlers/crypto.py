"""🪙 Криптовалюты: список пар и подробности по биржам."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import AlertCb, ChartCb, CompareCb, CryptoCb, Nav
from app.bot.context import AppContext
from app.bot.formatting import crypto_detail_text
from app.bot.keyboards import asset_buttons, button, grid, markup, menu_row
from app.bot.utils import command_args, parse_symbol_arg, show
from app.i18n import t
from app.services.users import UserCtx

router = Router(name="crypto")


def _symbols(ctx: AppContext, u: UserCtx) -> list[str]:
    return [s for s in ctx.users.active_watchlist(u) if s in ctx.assets.crypto]


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    symbols = _symbols(ctx, u)
    if not symbols:
        from app.bot.formatting import rates_text

        await show(event, rates_text(ctx, u), markup([menu_row(u.lang)]))
        return
    rows = grid(asset_buttons(symbols, lambda s: CryptoCb(symbol=s)), 3)
    rows.append(menu_row(u.lang, refresh=Nav(to="crypto")))
    await show(event, t(u.lang, "crypto.pick"), markup(rows))


async def detail(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, symbol: str) -> None:
    rows = [
        [
            button(t(u.lang, "menu.compare"), CompareCb(symbol=symbol)),
            button(t(u.lang, "menu.charts"), ChartCb(step="period", symbol=symbol)),
        ],
        [button(t(u.lang, "menu.alerts"), AlertCb(act="list"))],
        menu_row(u.lang, refresh=CryptoCb(symbol=symbol), back=Nav(to="crypto")),
    ]
    await show(event, crypto_detail_text(ctx, u, symbol), markup(rows))


@router.message(Command("crypto"))
async def cmd_crypto(message: Message, ctx: AppContext, u: UserCtx) -> None:
    args = command_args(message)
    if args:
        symbol = parse_symbol_arg(args[0], ctx.assets.crypto)
        if symbol is None:
            await message.answer(t(u.lang, "err.unknown_symbol", symbol=args[0][:20].replace("<", "")))
            return
        await detail(message, ctx, u, symbol)
        return
    await screen(message, ctx, u)


@router.callback_query(CryptoCb.filter())
async def on_crypto(cb: CallbackQuery, callback_data: CryptoCb, ctx: AppContext, u: UserCtx) -> None:
    if callback_data.symbol not in ctx.assets.crypto:
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
        return
    await detail(cb, ctx, u, callback_data.symbol)
