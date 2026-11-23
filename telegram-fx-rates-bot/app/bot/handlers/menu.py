"""/start, /help и навигация по главному меню."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.bot.callbacks import Nav, SetCb
from app.bot.context import AppContext
from app.bot.formatting import h
from app.bot.handlers import alerts, arbitrage, banks, charts, compare, crypto, p2p, rates, settings
from app.bot.keyboards import button, main_menu, markup
from app.bot.utils import show
from app.i18n import t
from app.services.users import UserCtx

router = Router(name="menu")

SCREENS = {
    "rates": rates.screen,
    "crypto": crypto.screen,
    "banks": banks.screen,
    "compare": compare.screen,
    "charts": charts.screen,
    "alerts": alerts.screen,
    "arbitrage": arbitrage.screen,
    "p2p": p2p.screen,
    "settings": settings.screen,
}


async def home(event: Message | CallbackQuery, u: UserCtx) -> None:
    await show(event, t(u.lang, "menu.title"), main_menu(u.lang))


@router.message(CommandStart())
async def cmd_start(message: Message, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    await state.clear()
    menu = main_menu(u.lang)
    rows = [[button(t(u.lang, "start.pick"), SetCb(act="assets", v="crypto"))], *menu.inline_keyboard]
    await message.answer(t(u.lang, "start.text", name=h(u.first_name)), reply_markup=markup(rows))


@router.message(Command("help", "menu"))
async def cmd_help(message: Message, u: UserCtx, state: FSMContext) -> None:
    await state.clear()
    await message.answer(t(u.lang, "help.text"), reply_markup=main_menu(u.lang))


@router.callback_query(Nav.filter())
async def on_nav(cb: CallbackQuery, callback_data: Nav, ctx: AppContext, u: UserCtx, state: FSMContext) -> None:
    await state.clear()
    if callback_data.to == "home":
        await home(cb, u)
        return
    screen = SCREENS.get(callback_data.to)
    if screen is None:
        await cb.answer(t(u.lang, "err.expired_button"), show_alert=True)
        return
    await screen(cb, ctx, u)


fallback_router = Router(name="fallback")


@fallback_router.message(F.text & ~F.text.startswith("/"))
async def fallback_text(message: Message, u: UserCtx) -> None:
    """Любой обычный текст вне сценариев — подсказка и меню."""
    await message.answer(t(u.lang, "menu.title"), reply_markup=main_menu(u.lang))
