"""⚡ Арбитражный мониторинг."""

from __future__ import annotations

from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import ArbCb
from app.bot.context import AppContext
from app.bot.formatting import arbitrage_detail_text, arbitrage_text
from app.bot.keyboards import button, grid, markup, menu_row
from app.bot.utils import show
from app.i18n import t
from app.services.users import UserCtx
from app.utils.fmt import format_pct

router = Router(name="arbitrage")

THRESHOLDS = ("0.1", "0.2", "0.3", "0.5", "0.75", "1", "2")


def _symbols(ctx: AppContext, u: UserCtx) -> list[str]:
    return [s for s in ctx.users.active_watchlist(u) if s in ctx.assets.crypto]


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    text, shown = arbitrage_text(ctx, u, _symbols(ctx, u))
    rows = grid([button(f"🔍 {o.symbol}", ArbCb(act="detail", symbol=o.symbol)) for o in shown], 3)
    rows.append([button(t(u.lang, "arb.set_threshold"), ArbCb(act="thr"))])
    rows.append(menu_row(u.lang, refresh=ArbCb(act="list")))
    await show(event, text, markup(rows))


@router.message(Command("arbitrage", "arb"))
async def cmd_arbitrage(message: Message, ctx: AppContext, u: UserCtx) -> None:
    await screen(message, ctx, u)


@router.callback_query(ArbCb.filter())
async def on_arbitrage(cb: CallbackQuery, callback_data: ArbCb, ctx: AppContext, u: UserCtx) -> None:
    act = callback_data.act
    if act == "list":
        await screen(cb, ctx, u)
    elif act == "detail":
        symbol = callback_data.symbol
        best = ctx.quotes.best_opportunity(symbol) if symbol in ctx.assets.crypto else None
        if best is None:
            await cb.answer(t(u.lang, "arb.no_data"), show_alert=True)
            return
        rows = [menu_row(u.lang, refresh=ArbCb(act="detail", symbol=symbol), back=ArbCb(act="list"))]
        await show(cb, arbitrage_detail_text(ctx, u.lang, best), markup(rows))
    elif act == "thr":
        rows = grid([button(format_pct(Decimal(v), 2), ArbCb(act="set", v=v)) for v in THRESHOLDS], 4)
        rows.append(menu_row(u.lang, back=ArbCb(act="list")))
        await show(cb, t(u.lang, "arb.threshold_prompt"), markup(rows))
    elif act == "set" and callback_data.v in THRESHOLDS:
        await ctx.users.update(u.telegram_id, arb_min_net_pct=Decimal(callback_data.v))
        user = cb.from_user
        u = await ctx.users.ensure(user.id, user.username, user.first_name, user.language_code)
        await screen(cb, ctx, u)
    else:
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
