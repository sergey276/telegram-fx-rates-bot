"""🛠 Административная панель (только Telegram ID из ADMIN_IDS; интерфейс на русском)."""

from __future__ import annotations

import logging
from datetime import timedelta
from html import escape

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.bot.callbacks import AdminCb
from app.bot.context import AppContext
from app.bot.keyboards import button, grid, markup
from app.bot.utils import show
from app.database.repositories import AlertRepo, AssetRepo, StatusRepo, UserRepo
from app.domain import source_name, utcnow
from app.services.pairs import PairRejected, probe_pair, validate_format
from app.services.runtime_settings import SPECS
from app.utils.fmt import format_age, format_time

log = logging.getLogger(__name__)
router = Router(name="admin")

STATE_ICON = {"ok": "🟢", "degraded": "🟡", "down": "🔴", "disabled": "⚫", "unknown": "⚪"}
SETTING_TITLES = {
    "arb_trade_size_usdt": "Размер условной сделки для арбитража, USDT",
    "arb_slippage_pct": "Проскальзывание на каждую сторону, %",
    "signups_enabled": "Регистрация новых пользователей",
    "alerts_enabled": "Отправка уведомлений",
    "p2p_enabled": "Раздел P2P",
}


class IsAdmin(BaseFilter):
    async def __call__(self, event: TelegramObject, ctx: AppContext) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in ctx.settings.admin_ids


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


class AdminFlow(StatesGroup):
    add_pair = State()
    set_value = State()


def e(value: object) -> str:
    return escape(str(value), quote=False)


# --------------------------------------------------------------------------- панель
def _panel_rows() -> list[list]:
    return [
        [button("📈 Статистика", AdminCb(act="stats")), button("👥 Пользователи", AdminCb(act="users"))],
        [button("🌐 Источники", AdminCb(act="sources")), button("⚠️ Ошибки", AdminCb(act="errors"))],
        [button("➕ Добавить пару", AdminCb(act="addpair")), button("⚙️ Глобальные настройки", AdminCb(act="settings"))],
    ]


def _back_row() -> list:
    return [button("⬅️ Админ-панель", AdminCb(act="panel"))]


async def panel(event: Message | CallbackQuery) -> None:
    await show(event, "🛠 <b>Админ-панель</b>", markup(_panel_rows()))


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await panel(message)


# --------------------------------------------------------------------------- статистика
async def stats_text(ctx: AppContext) -> str:
    now = utcnow()
    async with ctx.db.session() as session:
        users = UserRepo(session)
        total = await users.count()
        active_24h = await users.count_active_since(now - timedelta(hours=24))
        alerts = len([a for a in await AlertRepo(session).list_active()])
        pairs = len(await AssetRepo(session).list_active())
        errors_24h = await StatusRepo(session, ctx.db.dialect).count_errors_since(now - timedelta(hours=24))
    health = ctx.health.all()
    states = [h.state(now, ctx.store.fresh_seconds(h.kind)) for h in health]
    quotes = ctx.store.all()
    fresh = sum(1 for q in quotes if ctx.quotes.freshness(q).value == "fresh")
    uptime = format_age((now - ctx.started_at).total_seconds())  # type: ignore[operator]
    cache = "Redis" if ctx.core.redis is not None else "память процесса (Redis не подключён)"
    return (
        "📈 <b>Статистика</b>\n\n"
        f"Пользователи: <b>{total}</b> (активны за 24 ч: {active_24h})\n"
        f"Активные уведомления: <b>{alerts}</b>\n"
        f"Отслеживаемые пары: <b>{pairs}</b>\n"
        f"Котировки в кеше: <b>{len(quotes)}</b> (свежих: {fresh})\n"
        f"Источники: 🟢 {states.count('ok')} · 🟡 {states.count('degraded')} · 🔴 {states.count('down')} · ⚫ {states.count('disabled')}\n"
        f"Ошибки за 24 ч: <b>{errors_24h}</b>\n"
        f"Кеш: {cache}\nБД: {ctx.db.dialect}\nАптайм: {uptime}"
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message, ctx: AppContext) -> None:
    await show(message, await stats_text(ctx), markup([_back_row()]))


# --------------------------------------------------------------------------- пользователи
async def users_text(ctx: AppContext) -> str:
    async with ctx.db.session() as session:
        repo = UserRepo(session)
        total = await repo.count()
        recent = await repo.recent(20)
    tz = ctx.settings.timezone
    lines = [f"👥 <b>Пользователи</b>: {total}\n\nПоследние активные:"]
    for u in recent:
        name = f"@{e(u.username)}" if u.username else e(u.first_name or "—")
        flag = " 🚫" if u.is_blocked else ""
        lines.append(f"<code>{u.telegram_id}</code> {name} · {format_time(u.last_seen_at, tz, True)}{flag}")
    lines.append("\nБлокировка: /ban &lt;id&gt; · разблокировка: /unban &lt;id&gt;")
    return "\n".join(lines)


@router.message(Command("users"))
async def cmd_users(message: Message, ctx: AppContext) -> None:
    await show(message, await users_text(ctx), markup([_back_row()]))


@router.message(Command("ban", "unban"))
async def cmd_ban(message: Message, command: CommandObject, ctx: AppContext) -> None:
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.answer(f"Использование: /{command.command} &lt;telegram_id&gt;")
        return
    telegram_id = int(arg)
    if telegram_id in ctx.settings.admin_ids:
        await message.answer("Администратора заблокировать нельзя.")
        return
    blocked = command.command == "ban"
    async with ctx.db.session() as session:
        ok = await UserRepo(session).set_blocked(telegram_id, blocked)
    ctx.users.forget(telegram_id)
    ctx.invalidate_alerts()
    await message.answer(("🚫 Заблокирован" if blocked else "✅ Разблокирован") if ok else "Пользователь не найден")


# --------------------------------------------------------------------------- источники
def sources_view(ctx: AppContext) -> tuple[str, list[list]]:
    now = utcnow()
    lines = ["🌐 <b>Источники</b>\n"]
    toggles = []
    for h in sorted(ctx.health.all(), key=lambda x: (x.kind.value, x.source)):
        state = h.state(now, ctx.store.fresh_seconds(h.kind))
        parts = [f"{STATE_ICON[state]} <b>{source_name(h.source)}</b>"]
        if h.supports_ws:
            parts.append("WS ✅" if h.ws_connected else "WS ❌")
        activity = h.last_activity_at
        parts.append(f"данные: {format_age((now - activity).total_seconds()) + ' назад' if activity else 'нет'}")
        parts.append(f"ошибок: {h.total_errors}")
        lines.append(" · ".join(parts))
        if h.unlisted:
            lines.append(f"   ℹ️ нет пар: {e(', '.join(h.unlisted))}")
        if h.last_error and h.consecutive_errors:
            lines.append(f"   ⚠️ {e(h.last_error[:160])}")
        label = f"{'✅ Включить' if not h.enabled else '⛔ Отключить'} {source_name(h.source)}"
        toggles.append(button(label, AdminCb(act="toggle", v=h.source)))
    return "\n".join(lines), [*grid(toggles, 2), _back_row()]


@router.message(Command("sources"))
async def cmd_sources(message: Message, ctx: AppContext) -> None:
    text, rows = sources_view(ctx)
    await show(message, text, markup(rows))


# --------------------------------------------------------------------------- ошибки
async def errors_text(ctx: AppContext) -> str:
    async with ctx.db.session() as session:
        rows = await StatusRepo(session, ctx.db.dialect).recent_errors(20)
    if not rows:
        return "⚠️ <b>Ошибки</b>\n\nОшибок нет 🎉"
    tz = ctx.settings.timezone
    lines = ["⚠️ <b>Последние ошибки</b>\n"]
    for r in rows:
        lines.append(f"{format_time(r.created_at, tz, True)} · <b>{source_name(r.source)}</b>: {e(r.message[:200])}")
    return "\n".join(lines)


@router.message(Command("errors"))
async def cmd_errors(message: Message, ctx: AppContext) -> None:
    await show(message, await errors_text(ctx), markup([_back_row()]))


# --------------------------------------------------------------------------- пары
async def add_pair(ctx: AppContext, raw: str, admin_id: int) -> str:
    try:
        symbol = validate_format(raw)
    except PairRejected as exc:
        return f"❌ {e(exc)}"
    if symbol in ctx.assets.all:
        return f"ℹ️ Пара {symbol} уже отслеживается."
    probe = await probe_pair(ctx.core, symbol)
    if not probe.listed:
        details = []
        if probe.not_listed:
            details.append("не найдена на: " + ", ".join(source_name(s) for s in probe.not_listed))
        for source, error in probe.errors.items():
            details.append(f"{source_name(source)}: {e(error[:120])}")
        return f"❌ Пара {symbol} не найдена ни на одном включённом источнике.\n" + "\n".join(details)
    await ctx.assets.add(ctx.db, symbol, admin_id)
    text = f"✅ Пара <b>{symbol}</b> добавлена.\nДоступна на: {', '.join(source_name(s) for s in probe.listed)}"
    if probe.not_listed:
        text += f"\nНе торгуется на: {', '.join(source_name(s) for s in probe.not_listed)}"
    if probe.errors:
        text += f"\n⚠️ Не удалось проверить: {', '.join(source_name(s) for s in probe.errors)}"
    return text + "\nПользователи могут включить её в «Настройки → Активы»."


@router.message(Command("addpair"))
async def cmd_addpair(message: Message, command: CommandObject, ctx: AppContext) -> None:
    if not command.args:
        await message.answer("Использование: /addpair BTC/USDT")
        return
    await message.answer(await add_pair(ctx, command.args.split()[0][:24], message.from_user.id))  # type: ignore[union-attr]


@router.message(Command("delpair"))
async def cmd_delpair(message: Message, command: CommandObject, ctx: AppContext) -> None:
    try:
        symbol = validate_format((command.args or "").split()[0][:24]) if command.args else None
    except PairRejected as exc:
        await message.answer(f"❌ {e(exc)}")
        return
    if symbol is None:
        await message.answer("Использование: /delpair BTC/USDT")
        return
    ok = symbol in ctx.assets.all and await ctx.assets.remove(ctx.db, symbol)
    await message.answer(f"🗑 Пара {symbol} отключена." if ok else "Такой пары нет в каталоге.")


@router.message(AdminFlow.add_pair, F.text)
async def on_addpair_text(message: Message, ctx: AppContext, state: FSMContext) -> None:
    await state.clear()
    await message.answer(await add_pair(ctx, (message.text or "").split()[0][:24] if message.text else "", message.from_user.id))  # type: ignore[union-attr]


# --------------------------------------------------------------------------- глобальные настройки
def settings_view(ctx: AppContext) -> tuple[str, list[list]]:
    lines = ["⚙️ <b>Глобальные настройки</b>\n"]
    rows = []
    for key, title in SETTING_TITLES.items():
        value = ctx.runtime.get(key)
        shown = ("вкл ✅" if value else "выкл ⛔") if SPECS[key].kind == "bool" else str(value)
        lines.append(f"{title}: <b>{shown}</b>")
        if SPECS[key].kind == "bool":
            rows.append([button(f"{'⛔ Выключить' if value else '✅ Включить'}: {title[:28]}", AdminCb(act="flip", v=key))])
        else:
            rows.append([button(f"✏️ {title[:40]}", AdminCb(act="edit", v=key))])
    rows.append(_back_row())
    return "\n".join(lines), rows


@router.message(AdminFlow.set_value, F.text)
async def on_setting_value(message: Message, ctx: AppContext, state: FSMContext) -> None:
    data = await state.get_data()
    key = data.get("key", "")
    try:
        value = await ctx.runtime.set(ctx.db, key, message.text or "")
    except ValueError as exc:
        await message.answer(f"❌ {e(exc)}. Попробуйте ещё раз или отправьте /admin.")
        return
    await state.clear()
    await message.answer(f"✅ {SETTING_TITLES.get(key, key)}: <b>{value}</b>")


# --------------------------------------------------------------------------- кнопки
@router.callback_query(AdminCb.filter())
async def on_admin(cb: CallbackQuery, callback_data: AdminCb, ctx: AppContext, state: FSMContext) -> None:
    act, v = callback_data.act, callback_data.v
    if act != "edit" and act != "addpair":
        await state.clear()
    if act == "panel":
        await panel(cb)
    elif act == "stats":
        await show(cb, await stats_text(ctx), markup([[button("🔄 Обновить", AdminCb(act="stats"))], _back_row()]))
    elif act == "users":
        await show(cb, await users_text(ctx), markup([_back_row()]))
    elif act == "errors":
        await show(cb, await errors_text(ctx), markup([[button("🔄 Обновить", AdminCb(act="errors"))], _back_row()]))
    elif act == "sources":
        text, rows = sources_view(ctx)
        rows.insert(-1, [button("🔄 Обновить", AdminCb(act="sources"))])
        await show(cb, text, markup(rows))
    elif act == "toggle":
        health = ctx.health.get(v)
        if health is None:
            await cb.answer("Источник не найден", show_alert=True)
            return
        enabled = not health.enabled
        ctx.health.set_enabled(v, enabled)
        async with ctx.db.session() as session:
            await StatusRepo(session, ctx.db.dialect).set_enabled(v, enabled, health.kind.value)
        text, rows = sources_view(ctx)
        rows.insert(-1, [button("🔄 Обновить", AdminCb(act="sources"))])
        await show(cb, text, markup(rows))
    elif act == "addpair":
        await state.set_state(AdminFlow.add_pair)
        await show(cb, "Отправьте пару, например <code>SOL/USDT</code> или <code>PLN/UAH</code>.\n"
                       "Бот проверит её на всех включённых источниках перед добавлением.", markup([_back_row()]))
    elif act == "settings":
        text, rows = settings_view(ctx)
        await show(cb, text, markup(rows))
    elif act == "flip" and v in SPECS and SPECS[v].kind == "bool":
        await ctx.runtime.set(ctx.db, v, not ctx.runtime.get(v))
        text, rows = settings_view(ctx)
        await show(cb, text, markup(rows))
    elif act == "edit" and v in SPECS and SPECS[v].kind != "bool":
        await state.set_state(AdminFlow.set_value)
        await state.update_data(key=v)
        spec = SPECS[v]
        await show(cb, f"{SETTING_TITLES[v]}\nТекущее значение: <b>{ctx.runtime.get(v)}</b>\n"
                       f"Допустимо: от {spec.minimum} до {spec.maximum}. Отправьте новое число.",
                   markup([[button("✖️ Отмена", AdminCb(act="settings"))]]))
    else:
        await cb.answer("Неизвестное действие", show_alert=True)

