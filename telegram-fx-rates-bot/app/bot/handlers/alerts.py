"""🔔 Уведомления: список, создание (пошаговый сценарий), пауза, удаление, история."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.alerts.types import PCT_MAX, PCT_MIN, PCT_WINDOWS, AlertType, describe, window_label
from app.bot.callbacks import AlertCb, Nav
from app.bot.context import AppContext
from app.bot.keyboards import asset_buttons, button, grid, markup, menu_row
from app.bot.utils import parse_decimal, show
from app.database.repositories import AlertRepo
from app.domain import EXCHANGE_ORDER, SourceKind, source_name, utcnow
from app.i18n import t
from app.services.users import UserCtx
from app.utils.fmt import format_price, format_time

log = logging.getLogger(__name__)
router = Router(name="alerts")

DEFAULT_COOLDOWN_MIN = 15
MUTE_HOURS = (1, 8, 24)
PRICE_MAX = Decimal("1e12")


class AlertFlow(StatesGroup):
    threshold = State()


# --------------------------------------------------------------------------- список
async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, state: FSMContext | None = None) -> None:
    if state is not None:
        await state.clear()
    async with ctx.db.session() as session:
        alerts = await AlertRepo(session).list_for_user(u.user_id)
    lines = [t(u.lang, "alerts.title")]
    if u.muted and u.muted_until is not None:
        lines.append(t(u.lang, "alerts.muted_until", time=format_time(u.muted_until, ctx.settings.timezone, True)))
    lines.append("")
    toggles = []
    if not alerts:
        lines.append(t(u.lang, "alerts.empty"))
    for i, a in enumerate(alerts, 1):
        desc = describe(u.lang, a.type, a.symbol, a.source, a.threshold, a.window_minutes)
        lines.append(t(u.lang, "alerts.active_line", n=i, icon="🔔" if a.is_active else "⏸", desc=desc))
        toggles.append(button(f"{'⏸' if a.is_active else '▶️'} {i}", AlertCb(act="toggle", v=str(a.id))))
        toggles.append(button(f"🗑 {i}", AlertCb(act="del", v=str(a.id))))
    rows = grid(toggles, 6) if toggles else []
    rows.append([button(t(u.lang, "alerts.create"), AlertCb(act="new")), button(t(u.lang, "alerts.history"), AlertCb(act="hist"))])
    if u.muted:
        rows.append([button(t(u.lang, "alerts.unmute"), AlertCb(act="unmute"))])
    else:
        rows.append([button(t(u.lang, "alerts.mute", h=hrs), AlertCb(act="mute", v=str(hrs))) for hrs in MUTE_HOURS])
    rows.append(menu_row(u.lang, refresh=AlertCb(act="list")))
    await show(event, "\n".join(lines), markup(rows))


@router.message(Command("alerts"))
async def cmd_alerts(message: Message, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    await screen(message, ctx, u, state)


# --------------------------------------------------------------------------- создание
def _type_buttons(u: UserCtx, has_crypto: bool) -> list:
    return [
        [button(t(u.lang, f"alerts.type.{kind.value}"), AlertCb(act="type", v=kind.value))]
        for kind in AlertType
        if has_crypto or not kind.crypto_only
    ]


def _sources_for(ctx: AppContext, symbol: str) -> list[str]:
    if symbol in ctx.assets.fiat:
        names = [p.name for p in ctx.core.providers.values() if p.kind is SourceKind.BANK]
    else:
        names = [s for s in EXCHANGE_ORDER if s in ctx.core.providers]
    return [s for s in names if ctx.health.is_enabled(s) and ctx.store.get(s, symbol) is not None]


async def _ask_threshold(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    data = await state.get_data()
    kind = AlertType(data["type"])
    symbol, source = data["symbol"], data.get("source")
    await state.set_state(AlertFlow.threshold)
    cancel = markup([[button(t(u.lang, "btn.cancel"), AlertCb(act="cancel"))]])
    if kind.is_percent:
        example = {"pct_change": "1", "spread": "0.5", "arbitrage": "0.3"}[kind.value]
        text = t(u.lang, "alerts.enter_pct", example=example)
    else:
        quote = ctx.store.get(source, symbol) if source else None
        price = quote.history_price[0] if quote and quote.history_price else None
        now = format_price(price)
        example = format_price(price.quantize(Decimal(1)) if price is not None and price >= 100 else price or Decimal(1))
        text = t(u.lang, "alerts.enter_price", symbol=symbol, source=source_name(source or ""), example=example, now=now)
    await show(event, text, cancel)


@router.callback_query(AlertCb.filter())
async def on_alert(cb: CallbackQuery, callback_data: AlertCb, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    act, v = callback_data.act, callback_data.v
    lang = u.lang

    if act == "list" or act == "cancel":
        await screen(cb, ctx, u, state)
        return

    if act == "new":
        await state.clear()
        async with ctx.db.session() as session:
            count = await AlertRepo(session).count_for_user(u.user_id)
        if count >= ctx.settings.max_alerts_per_user:
            await cb.answer(t(lang, "alerts.limit", n=ctx.settings.max_alerts_per_user), show_alert=True)
            return
        has_crypto = any(s in ctx.assets.crypto for s in ctx.users.active_watchlist(u))
        rows = _type_buttons(u, has_crypto) + [[button(t(lang, "btn.back"), AlertCb(act="list"))]]
        await show(cb, t(lang, "alerts.type_prompt"), markup(rows))
        return

    if act == "type":
        try:
            kind = AlertType(v)
        except ValueError:
            await cb.answer(t(lang, "err.expired_button"), show_alert=True)
            return
        await state.update_data(type=kind.value)
        symbols = ctx.users.active_watchlist(u)
        if kind.crypto_only:
            symbols = [s for s in symbols if s in ctx.assets.crypto]
        rows = grid(asset_buttons(symbols, lambda s: AlertCb(act="asset", v=s)), 3)
        rows.append([button(t(lang, "btn.back"), AlertCb(act="new"))])
        await show(cb, t(lang, "alerts.pick_asset"), markup(rows))
        return

    data = await state.get_data()
    if act in ("asset", "src", "win") and "type" not in data:
        await cb.answer(t(lang, "err.expired_button"), show_alert=True)
        return

    if act == "asset":
        symbol = v
        kind = AlertType(data["type"])
        if symbol not in ctx.assets.all or (kind.crypto_only and symbol not in ctx.assets.crypto):
            await cb.answer(t(lang, "err.expired_button"), show_alert=True)
            return
        await state.update_data(symbol=symbol)
        if kind.needs_source:
            sources = _sources_for(ctx, symbol)
            rows = grid([button(source_name(s), AlertCb(act="src", v=s)) for s in sources], 3)
            rows.append([button(t(lang, "btn.back"), AlertCb(act="type", v=kind.value))])
            await show(cb, t(lang, "alerts.pick_source", symbol=symbol), markup(rows))
        else:
            await state.update_data(source=None)
            await _ask_threshold(cb, ctx, u, state)
        return

    if act == "src":
        if v not in ctx.core.providers:
            await cb.answer(t(lang, "err.expired_button"), show_alert=True)
            return
        await state.update_data(source=v)
        if AlertType(data["type"]) is AlertType.PCT_CHANGE:
            rows = grid([button(window_label(lang, m), AlertCb(act="win", v=str(m))) for m in PCT_WINDOWS], 3)
            rows.append([button(t(lang, "btn.cancel"), AlertCb(act="cancel"))])
            await show(cb, t(lang, "alerts.pick_window"), markup(rows))
        else:
            await _ask_threshold(cb, ctx, u, state)
        return

    if act == "win":
        if not v.isdigit() or int(v) not in PCT_WINDOWS:
            await cb.answer(t(lang, "err.expired_button"), show_alert=True)
            return
        await state.update_data(window=int(v))
        await _ask_threshold(cb, ctx, u, state)
        return

    if act in ("toggle", "del") and v.isdigit():
        async with ctx.db.session() as session:
            repo = AlertRepo(session)
            ok = (await repo.toggle(u.user_id, int(v))) is not None if act == "toggle" else await repo.delete(u.user_id, int(v))
        ctx.invalidate_alerts()
        if not ok:
            await cb.answer(t(lang, "alerts.not_found"), show_alert=True)
        await screen(cb, ctx, u, state)
        return

    if act == "mute" and v.isdigit() and int(v) in MUTE_HOURS:
        await ctx.users.update(u.telegram_id, alerts_muted_until=utcnow() + timedelta(hours=int(v)))
        u = await _fresh(ctx, cb, u)
        await screen(cb, ctx, u, state)
        return

    if act == "unmute":
        await ctx.users.update(u.telegram_id, alerts_muted_until=None)
        u = await _fresh(ctx, cb, u)
        await screen(cb, ctx, u, state)
        return

    if act == "hist":
        async with ctx.db.session() as session:
            rows_ = await AlertRepo(session).history_for_user(u.user_id, 10)
        lines = [t(lang, "alerts.history_title"), ""]
        if not rows_:
            lines.append(t(lang, "alerts.history_empty"))
        for r in rows_:
            lines.append(f"🕒 {format_time(r.triggered_at, ctx.settings.timezone, True)}\n{r.message}\n")
        await show(cb, "\n".join(lines), markup([menu_row(u.lang, back=AlertCb(act="list"))]))
        return

    await cb.answer(t(lang, "err.expired_button"), show_alert=True)


async def _fresh(ctx: AppContext, cb: CallbackQuery, u: UserCtx) -> UserCtx:
    user = cb.from_user
    return await ctx.users.ensure(user.id, user.username, user.first_name, user.language_code)


# --------------------------------------------------------------------------- ввод порога
@router.message(AlertFlow.threshold, F.text)
async def on_threshold(message: Message, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    data = await state.get_data()
    if "type" not in data or "symbol" not in data:
        await state.clear()
        await screen(message, ctx, u, state)
        return
    kind = AlertType(data["type"])
    value = parse_decimal(message.text or "")
    example = "0.5" if kind.is_percent else "100"
    if value is None:
        await message.answer(t(u.lang, "err.invalid_number", example=example))
        return
    low, high = (PCT_MIN, PCT_MAX) if kind.is_percent else (Decimal("0.00000001"), PRICE_MAX)
    if not low <= value <= high:
        await message.answer(t(u.lang, "err.out_of_range", min=format_price(low), max=format_price(high)))
        return

    async with ctx.db.session() as session:
        repo = AlertRepo(session)
        if await repo.count_for_user(u.user_id) >= ctx.settings.max_alerts_per_user:
            await message.answer(t(u.lang, "alerts.limit", n=ctx.settings.max_alerts_per_user))
            await state.clear()
            return
        alert = await repo.create(
            user_id=u.user_id, type=kind.value, symbol=data["symbol"], source=data.get("source"), threshold=value,
            window_minutes=data.get("window"), cooldown_minutes=DEFAULT_COOLDOWN_MIN,
        )
    await state.clear()
    ctx.invalidate_alerts()
    desc = describe(u.lang, alert.type, alert.symbol, alert.source, alert.threshold, alert.window_minutes)
    rows = [[button(t(u.lang, "menu.alerts"), AlertCb(act="list")), button(t(u.lang, "btn.menu"), Nav(to="home"))]]
    await message.answer(
        t(u.lang, "alerts.created", desc=desc, cooldown=max(DEFAULT_COOLDOWN_MIN, u.notify_interval_min)),
        reply_markup=markup(rows),
    )
