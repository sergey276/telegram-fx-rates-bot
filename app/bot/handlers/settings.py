"""⚙️ Настройки: язык, активы, частота уведомлений, валюта отображения, графики, порог арбитража."""

from __future__ import annotations

from decimal import Decimal

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import Nav, SetCb
from app.bot.context import AppContext
from app.bot.keyboards import button, grid, markup, menu_row
from app.bot.utils import show
from app.i18n import LANGUAGES, t
from app.services.chart_service import PERIODS
from app.services.users import UserCtx
from app.utils.fmt import format_pct

router = Router(name="settings")

INTERVALS = (1, 5, 15, 30, 60)
CURRENCIES = ("USDT", "UAH", "EUR")
THEMES = ("dark", "light")
ARB_THRESHOLDS = ("0.1", "0.2", "0.3", "0.5", "0.75", "1", "2")
PAGE_SIZE = 12


def _interval_label(lang: str, minutes: int) -> str:
    return t(lang, "settings.interval_hour") if minutes == 60 else t(lang, "settings.interval_opt", m=minutes)


async def _fresh(ctx: AppContext, cb: CallbackQuery | Message) -> UserCtx:
    user = cb.from_user
    assert user is not None
    return await ctx.users.ensure(user.id, user.username, user.first_name, user.language_code)


async def screen(event: Message | CallbackQuery, ctx: AppContext, u: UserCtx) -> None:
    lang = u.lang
    summary = t(
        lang, "settings.summary", language=LANGUAGES[lang], cur=u.display_currency,
        interval=_interval_label(lang, u.notify_interval_min), period=t(lang, f"period.{u.chart_period}"),
        theme=t(lang, f"settings.theme.{u.chart_theme}"), arb=format_pct(u.arb_min_net_pct),
        assets=len(ctx.users.active_watchlist(u)),
    )
    rows = [
        [button(t(lang, "settings.lang"), SetCb(act="lang")), button(t(lang, "settings.assets"), SetCb(act="assets", v="crypto"))],
        [button(t(lang, "settings.interval"), SetCb(act="interval")), button(t(lang, "settings.currency"), SetCb(act="cur"))],
        [button(t(lang, "settings.charts"), SetCb(act="charts")), button(t(lang, "settings.arb"), SetCb(act="arb"))],
        menu_row(lang),
    ]
    await show(event, f"{t(lang, 'settings.title')}\n\n{summary}", markup(rows))


@router.message(Command("settings"))
async def cmd_settings(message: Message, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    await state.clear()
    await screen(message, ctx, u)


def _back(lang: str) -> list:
    return menu_row(lang, back=SetCb(act="menu"))


async def _assets_screen(cb: CallbackQuery, ctx: AppContext, u: UserCtx, group: str, page: int) -> None:
    lang = u.lang
    catalog = ctx.assets.crypto if group == "crypto" else ctx.assets.fiat
    pages = max(1, (len(catalog) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    chosen = set(u.watchlist)
    chunk = catalog[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]
    rows = [
        [
            button(t(lang, "settings.assets_crypto"), SetCb(act="assets", v="crypto")),
            button(t(lang, "settings.assets_fiat"), SetCb(act="assets", v="fiat")),
        ]
    ]
    rows += grid([button(("✅ " if s in chosen else "▫️ ") + s, SetCb(act="toggle", v=s, page=page)) for s in chunk], 2)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(button("◀️", SetCb(act="assets", v=group, page=page - 1)))
        nav.append(button(f"{page + 1}/{pages}", SetCb(act="assets", v=group, page=page)))
        if page < pages - 1:
            nav.append(button("▶️", SetCb(act="assets", v=group, page=page + 1)))
        rows.append(nav)
    rows.append([button(t(lang, "settings.assets_done"), SetCb(act="menu")), button(t(lang, "btn.menu"), Nav(to="home"))])
    await show(cb, t(lang, "settings.assets_prompt"), markup(rows))


@router.callback_query(SetCb.filter())
async def on_settings(cb: CallbackQuery, callback_data: SetCb, ctx: AppContext, u: UserCtx) -> None:
    act, v = callback_data.act, callback_data.v
    lang = u.lang
    tid = u.telegram_id

    async def save_and_show_menu(**fields: object) -> None:
        await ctx.users.update(tid, **fields)
        fresh = await _fresh(ctx, cb)
        await screen(cb, ctx, fresh)

    if act == "menu":
        await screen(cb, ctx, u)
    elif act == "lang":
        rows = grid([button(("✅ " if code == lang else "") + name, SetCb(act="setlang", v=code)) for code, name in LANGUAGES.items()], 1)
        rows.append(_back(lang))
        await show(cb, t(lang, "settings.lang_prompt"), markup(rows))
    elif act == "setlang" and v in LANGUAGES:
        await save_and_show_menu(language=v)
    elif act == "assets":
        group = v if v in ("crypto", "fiat") else "crypto"
        await _assets_screen(cb, ctx, u, group, callback_data.page)
    elif act == "toggle":
        catalog = ctx.assets.all
        if v not in catalog:
            await cb.answer(t(lang, "err.expired_button"), show_alert=True)
            return
        chosen = set(u.watchlist)
        chosen.symmetric_difference_update({v})
        await ctx.users.update(tid, watchlist=[s for s in catalog if s in chosen])
        fresh = await _fresh(ctx, cb)
        await _assets_screen(cb, ctx, fresh, "crypto" if v in ctx.assets.crypto else "fiat", callback_data.page)
    elif act == "interval":
        rows = grid([button(("✅ " if m == u.notify_interval_min else "") + _interval_label(lang, m), SetCb(act="setint", v=str(m))) for m in INTERVALS], 3)
        rows.append(_back(lang))
        await show(cb, t(lang, "settings.interval_prompt"), markup(rows))
    elif act == "setint" and v.isdigit() and int(v) in INTERVALS:
        await save_and_show_menu(notify_interval_min=int(v))
        ctx.invalidate_alerts()
    elif act == "cur":
        rows = grid([button(("✅ " if c == u.display_currency else "") + c, SetCb(act="setcur", v=c)) for c in CURRENCIES], 3)
        rows.append(_back(lang))
        await show(cb, t(lang, "settings.currency_prompt"), markup(rows))
    elif act == "setcur" and v in CURRENCIES:
        await save_and_show_menu(display_currency=v)
    elif act == "charts":
        rows = [
            [button(("✅ " if p == u.chart_period else "") + t(lang, f"period.{p}"), SetCb(act="setperiod", v=p)) for p in PERIODS],
            [button(("✅ " if th == u.chart_theme else "") + t(lang, f"settings.theme.{th}"), SetCb(act="settheme", v=th)) for th in THEMES],
            _back(lang),
        ]
        text = t(lang, "settings.charts_prompt", period=t(lang, f"period.{u.chart_period}"), theme=t(lang, f"settings.theme.{u.chart_theme}"))
        await show(cb, text, markup(rows))
    elif act == "setperiod" and v in PERIODS:
        await ctx.users.update(tid, chart_period=v)
        await _charts_refresh(cb, ctx)
    elif act == "settheme" and v in THEMES:
        await ctx.users.update(tid, chart_theme=v)
        await _charts_refresh(cb, ctx)
    elif act == "arb":
        rows = grid([button(("✅ " if Decimal(x) == u.arb_min_net_pct else "") + format_pct(Decimal(x), 2), SetCb(act="setarb", v=x)) for x in ARB_THRESHOLDS], 4)
        rows.append(_back(lang))
        await show(cb, t(lang, "settings.arb_prompt"), markup(rows))
    elif act == "setarb" and v in ARB_THRESHOLDS:
        await save_and_show_menu(arb_min_net_pct=Decimal(v))
    else:
        await cb.answer(t(lang, "err.expired_button"), show_alert=True)


async def _charts_refresh(cb: CallbackQuery, ctx: AppContext) -> None:
    fresh = await _fresh(ctx, cb)
    lang = fresh.lang
    rows = [
        [button(("✅ " if p == fresh.chart_period else "") + t(lang, f"period.{p}"), SetCb(act="setperiod", v=p)) for p in PERIODS],
        [button(("✅ " if th == fresh.chart_theme else "") + t(lang, f"settings.theme.{th}"), SetCb(act="settheme", v=th)) for th in THEMES],
        _back(lang),
    ]
    text = t(lang, "settings.charts_prompt", period=t(lang, f"period.{fresh.chart_period}"), theme=t(lang, f"settings.theme.{fresh.chart_theme}"))
    await show(cb, text, markup(rows))
