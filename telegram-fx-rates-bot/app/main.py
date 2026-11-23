"""Точка входа: ``python -m app.main`` (бот) или ``python -m app.main --collect-only`` (только сбор данных)."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sqlalchemy import text

from app.alerts import AlertEngine
from app.bot.context import AppContext
from app.bot.factory import Notifier, create_bot, create_dispatcher, register_commands
from app.config import Settings, get_settings
from app.core import Core
from app.database import Database
from app.domain import utcnow
from app.providers.p2p_platforms import all_platforms
from app.services.chart_service import ChartService
from app.services.p2p import P2PService
from app.services.quotes import QuoteService
from app.services.users import UserService
from app.utils.logging import setup_logging

log = logging.getLogger("app.main")


async def check_database(db: Database) -> bool:
    if db.dialect == "sqlite":
        await db.create_all()  # SQLite — режим разработки: схема создаётся автоматически
    if not await db.ping():
        log.error("Нет соединения с базой данных. Проверьте DATABASE_URL.")
        return False
    try:
        async with db.engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM tracked_assets LIMIT 1"))
    except Exception:
        log.error("Схема БД не создана. Выполните миграции: alembic upgrade head")
        return False
    return True


async def run_bot(settings: Settings) -> int:
    if not settings.bot_token.get_secret_value():
        log.error("BOT_TOKEN не задан. Получите токен у @BotFather и добавьте его в файл .env")
        return 2
    if not settings.admin_ids:
        log.warning("ADMIN_IDS пуст: административные команды будут недоступны всем")

    bot = create_bot(settings)
    try:
        me = await bot.get_me()  # быстрая проверка токена до запуска сборщиков данных
    except Exception as exc:
        log.error("Не удалось подключиться к Telegram (проверьте BOT_TOKEN и сеть): %s", type(exc).__name__)
        await bot.session.close()
        return 4

    core = Core(settings)
    if not await check_database(core.db):
        await core.db.dispose()
        await bot.session.close()
        return 3
    await core.start()
    quotes = QuoteService(core.store, core.health, core.runtime, settings)
    ctx = AppContext(
        core=core,
        quotes=quotes,
        users=UserService(core.db, settings, core.assets),
        charts=ChartService(core.db, quotes),
        p2p=P2PService(all_platforms(core.http)),
    )
    log.info("Бот запущен: @%s", me.username)

    notifier = Notifier(bot)
    engine = AlertEngine(core.db, core.store, ctx.quotes, core.runtime, settings, notifier.send)
    ctx.alerts = engine
    ctx.users.on_settings_changed = engine.invalidate
    engine.start()
    dp = create_dispatcher(ctx)
    await register_commands(bot)
    try:
        await bot.delete_webhook(drop_pending_updates=False)
        await dp.start_polling(bot, handle_signals=True, allowed_updates=dp.resolve_used_update_types())
    finally:
        log.info("Остановка…")
        await engine.stop()
        await bot.session.close()
        await core.stop()
    return 0


async def run_collect_only(settings: Settings, seconds: int) -> int:
    """Сбор данных без Telegram: удобно для проверки источников, БД и Redis."""
    core = Core(settings)
    if not await check_database(core.db):
        await core.db.dispose()
        return 3
    await core.start()
    try:
        await asyncio.sleep(seconds)
        now = utcnow()
        for h in sorted(core.health.all(), key=lambda x: x.source):
            state = h.state(now, core.store.fresh_seconds(h.kind))
            print(f"{h.source:<11} {state:<9} ws={h.ws_connected!s:<5} ошибок={h.total_errors} {h.last_error or ''}")
        print(f"котировок в кеше: {len(core.store.all())}")
    finally:
        await core.stop()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Бот мониторинга курсов валют и криптовалют")
    parser.add_argument("--collect-only", type=int, metavar="SECONDS", help="только сбор данных N секунд, без Telegram")
    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_dir)
    try:
        if args.collect_only:
            code = asyncio.run(run_collect_only(settings, args.collect_only))
        else:
            code = asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        code = 0
    sys.exit(code)


if __name__ == "__main__":
    main()
