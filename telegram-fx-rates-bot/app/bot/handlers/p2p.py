"""💱 P2P: сравнение площадок (Binance, Bybit, OKX, KuCoin, Bitget) по банкам Monobank, PrivatBank, Alliance, Sense Bank, A-Bank, PUMB."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import P2PCb
from app.bot.context import AppContext
from app.bot.keyboards import button, grid, markup, menu_row
from app.bot.utils import show
from app.i18n import t
from app.providers.p2p_common import P2P_BANKS, Side
from app.services.p2p import AMOUNTS, ASSETS, DEFAULT_AMOUNT, MIN_FINISH_RATE, MIN_MONTH_ORDERS, P2PBoard
from app.services.users import UserCtx
from app.utils.fmt import format_pct, format_price, format_time

log = logging.getLogger(__name__)
router = Router(name="p2p")

DASH = "—"


def _amount(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _price(ad_price) -> str:  # noqa: ANN001
    return format_price(ad_price) if ad_price is not None else DASH


def _mark(board: P2PBoard, platform: str) -> str:
    data = board.platforms[platform]
    if data.stale:
        return " 🟡"
    return " ⚠️" if data.error and not data.has_data else ""


def _notes(board: P2PBoard, lang: str) -> list[str]:
    lines = []
    if board.failed:
        lines.append(t(lang, "p2p.failed", items=", ".join(board.names[p] for p in board.failed)))
    if board.stale:
        lines.append(t(lang, "p2p.stale", items=", ".join(board.names[p] for p in board.stale)))
    return lines


def board_text(ctx: AppContext, u: UserCtx, board: P2PBoard) -> str:
    lang = u.lang
    names = board.names
    lines = [
        t(lang, "p2p.title", asset=board.asset),
        t(lang, "p2p.updated", time=format_time(board.fetched_at, ctx.settings.timezone)),
        t(lang, "p2p.params", amount=_amount(board.amount), orders=MIN_MONTH_ORDERS,
          rate=format_pct(MIN_FINISH_RATE * 100, 0), platforms=", ".join(names.values())),
        "",
        t(lang, "p2p.by_bank"),
    ]
    for bank, bank_name in P2P_BANKS.items():
        buy, sell = board.best_for_bank(bank, Side.BUY), board.best_for_bank(bank, Side.SELL)
        lines.append(
            t(lang, "p2p.bank_line", bank=bank_name,
              buy=_price(buy[1].price if buy else None), buy_src=names[buy[0]] if buy else DASH,
              sell=_price(sell[1].price if sell else None), sell_src=names[sell[0]] if sell else DASH)
        )
    lines += ["", t(lang, "p2p.by_platform")]
    for platform in board.platforms:
        buy, sell = board.best_for_platform(platform, Side.BUY), board.best_for_platform(platform, Side.SELL)
        lines.append(
            t(lang, "p2p.platform_line", platform=names[platform], mark=_mark(board, platform),
              buy=_price(buy[1].price if buy else None), buy_bank=P2P_BANKS[buy[0]] if buy else DASH,
              sell=_price(sell[1].price if sell else None), sell_bank=P2P_BANKS[sell[0]] if sell else DASH)
        )
    cheapest, richest, cross = board.cheapest_buy(), board.richest_sell(), board.cross_pct()
    if cheapest and richest:
        lines += [
            "",
            t(lang, "p2p.best_buy", platform=names[cheapest[0]], bank=P2P_BANKS[cheapest[1]], price=format_price(cheapest[2].price)),
            t(lang, "p2p.best_sell", platform=names[richest[0]], bank=P2P_BANKS[richest[1]], price=format_price(richest[2].price)),
        ]
        if cross is not None:
            lines.append(t(lang, "p2p.cross", pct=format_pct(cross, 2, True)))
    notes = _notes(board, lang)
    if notes:
        lines += ["", *notes]
    lines += ["", f"<i>{t(lang, 'p2p.legend', asset=board.asset)}</i>", "", t(lang, "p2p.disclaimer")]
    return "\n".join(lines)


def detail_text(ctx: AppContext, u: UserCtx, board: P2PBoard, bank: str) -> str:
    lang = u.lang
    names = board.names
    lines = [
        t(lang, "p2p.detail_title", bank=P2P_BANKS[bank], asset=board.asset, amount=_amount(board.amount)),
        t(lang, "p2p.updated", time=format_time(board.fetched_at, ctx.settings.timezone)),
        "",
        t(lang, "p2p.detail_platforms"),
    ]
    for platform, data in board.platforms.items():
        buy, sell = data.best(bank, Side.BUY), data.best(bank, Side.SELL)
        if buy is None and sell is None and not data.error:
            body = t(lang, "p2p.no_ads")
            lines.append(f"{names[platform]}{_mark(board, platform)}: {body}")
            continue
        lines.append(
            t(lang, "p2p.platform_row", platform=names[platform], mark=_mark(board, platform),
              buy=_price(buy.price if buy else None), sell=_price(sell.price if sell else None))
        )
    for side, header in ((Side.BUY, "p2p.detail_buy"), (Side.SELL, "p2p.detail_sell")):
        lines += ["", t(lang, header, asset=board.asset)]
        top = board.top_ads(bank, side)
        if not top:
            lines.append(t(lang, "p2p.no_ads"))
        for i, (platform, ad) in enumerate(top, 1):
            lines.append(
                t(lang, "p2p.ad_line", n=i, price=format_price(ad.price), platform=names[platform],
                  available=format_price(ad.available), asset=board.asset, low=format_price(ad.min_amount),
                  high=format_price(ad.max_amount), orders=ad.month_orders, rate=format_pct(ad.finish_rate * 100, 0))
            )
    notes = _notes(board, lang)
    if notes:
        lines += ["", *notes]
    lines += ["", t(lang, "p2p.disclaimer")]
    return "\n".join(lines)


def _keyboard(u: UserCtx, asset: str, amount: int, bank: str = "") -> list[list]:
    rows = [
        [button(("✅ " if a == amount else "") + f"{_amount(a)} ₴", P2PCb(act="view", asset=asset, amount=a, bank=bank)) for a in AMOUNTS],
        [button(("✅ " if a == asset else "") + a, P2PCb(act="view", asset=a, amount=amount, bank=bank)) for a in ASSETS],
    ]
    if not bank:
        rows += grid([button(name, P2PCb(act="bank", asset=asset, amount=amount, bank=key)) for key, name in P2P_BANKS.items()], 3)
    rows.append(menu_row(u.lang, refresh=P2PCb(act="refresh", asset=asset, amount=amount, bank=bank),
                         back=P2PCb(act="view", asset=asset, amount=amount) if bank else None))
    return rows


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, asset: str = "USDT",
                 amount: int = DEFAULT_AMOUNT, bank: str = "", force: bool = False) -> None:
    if not ctx.runtime.get("p2p_enabled"):
        await show(event, t(u.lang, "p2p.off"), markup([menu_row(u.lang)]))
        return
    retry = markup([menu_row(u.lang, refresh=P2PCb(act="refresh", asset=asset, amount=amount, bank=bank))])
    try:
        board = await ctx.p2p.board(asset, amount, force=force)
    except ValueError as exc:
        log.warning("P2P: %s", exc)
        await show(event, t(u.lang, "p2p.unavailable"), retry)
        return
    if not board.has_data:
        await show(event, t(u.lang, "p2p.unavailable") + "\n" + "\n".join(_notes(board, u.lang)), retry)
        return
    text = detail_text(ctx, u, board, bank) if bank else board_text(ctx, u, board)
    await show(event, text, markup(_keyboard(u, asset, amount, bank)))


@router.message(Command("p2p"))
async def cmd_p2p(message: Message, ctx: AppContext, u: UserCtx) -> None:
    await screen(message, ctx, u)


@router.callback_query(P2PCb.filter())
async def on_p2p(cb: CallbackQuery, callback_data: P2PCb, ctx: AppContext, u: UserCtx) -> None:
    asset, amount, bank = callback_data.asset, callback_data.amount, callback_data.bank
    if asset not in ASSETS or amount not in AMOUNTS or (bank and bank not in P2P_BANKS):
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
        return
    await screen(cb, ctx, u, asset, amount, bank, force=callback_data.act == "refresh")
