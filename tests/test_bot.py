"""Сценарии Telegram-интерфейса: настоящий Dispatcher + поддельная сессия Bot."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.bot.callbacks import AdminCb, AlertCb, ArbCb, ChartCb, CompareCb, CryptoCb, Nav, SetCb
from app.database.repositories import AlertRepo, Candle, HistoryRepo
from app.services.history import floor_minute
from tests.bot_harness import BotApp


@pytest.fixture
async def app():
    a = await BotApp.create()
    a.load_market()
    yield a
    await a.close()


# --------------------------------------------------------------------------- /start и меню
async def test_start_greets_registers_user_and_shows_menu(app):
    s = await app.say("/start", name="Анна")
    text = s.last_text()
    assert "Анна" in text and "Monobank" in text and "Binance" in text
    labels = [b["text"] for row in s.last_markup() for b in row]
    for expected in ("📊 Курсы валют", "🪙 Криптовалюты", "🏦 Банки", "🔄 Сравнение цен", "📈 Графики",
                     "🔔 Уведомления", "⚡ Арбитраж", "⚙️ Настройки"):
        assert expected in labels
    assert any("Выбрать активы" in label for label in labels)  # предложение выбрать активы
    assert await app.ctx.users.exists(1)


async def test_start_escapes_html_in_user_name(app):
    s = await app.say("/start", name="<b>Hacker</b>")
    assert "&lt;b&gt;Hacker&lt;/b&gt;" in s.last_text() and "<b>Hacker</b>" not in s.last_text()


async def test_language_taken_from_telegram_profile(app):
    s = await app.say("/start", user_id=5, lang="en")
    assert "Hi," in s.last_text()
    s = await app.say("/start", user_id=6, lang="uk")
    assert "Привіт" in s.last_text()
    s = await app.say("/start", user_id=7, lang="de")  # неизвестный язык -> по умолчанию
    assert "Привет" in s.last_text()


async def test_all_commands_answer_without_errors(app):
    for command in ("/rates", "/crypto", "/banks", "/compare", "/history", "/alerts", "/arbitrage", "/settings", "/help"):
        app.session.clear()
        s = await app.say(command)
        assert s.texts(), f"{command} не дал ответа"
        assert "Что-то пошло не так" not in " ".join(s.texts()), command


async def test_every_menu_button_works(app):
    for target in ("rates", "crypto", "banks", "compare", "charts", "alerts", "arbitrage", "settings", "home"):
        app.session.clear()
        s = await app.press(Nav(to=target).pack())
        assert s.of("EditMessageText"), f"кнопка {target} не отредактировала сообщение"
        assert "Что-то пошло не так" not in s.last_text()


async def test_plain_text_outside_flow_shows_menu(app):
    s = await app.say("привет")
    assert "Главное меню" in s.last_text()


# --------------------------------------------------------------------------- курсы
async def test_rates_show_banks_and_crypto_with_freshness(app):
    s = await app.say("/rates")
    text = s.last_text()
    assert "USD/UAH" in text and "Monobank" in text and "PrivatBank" in text
    assert "44.91 / 45.4091" in text
    assert "BTC/USDT" in text and "6 бирж" not in text and "5 бирж" in text
    assert "61 460" in text.replace(" ", " ")  # минимум среди бирж


async def test_rates_warn_when_data_is_stale(app):
    app.load_market(now=datetime.now(UTC) - timedelta(minutes=5))  # биржи (45 с) устарели, банки (15 мин) ещё свежие
    text = (await app.say("/rates")).last_text()
    assert "⛔" in text or "🟡" in text or "Нет актуальных" in text or "нет актуальных" in text


async def test_banks_show_cross_rate_and_missing_api_fields(app):
    from app.domain import SourceKind
    from tests.conftest import make_quote

    cross = make_quote(source="monobank", symbol="GBP/UAH", kind=SourceKind.BANK, bid=None, ask=None, last=None)
    app.core.store.put(cross.model_copy(update={"cross_rate": D("59.6")}))
    await app.ctx.assets.add(app.db, "GBP/UAH", None)
    await app.press(SetCb(act="toggle", v="GBP/UAH").pack())
    text = (await app.say("/banks")).last_text()
    assert "кросс-курс" in text and "59.6" in text
    assert "не предоставляется API банка" in text  # PrivatBank без времени котировки — честно сообщаем
    assert "Продать валюту выгоднее" in text


async def test_crypto_detail_lists_each_exchange_and_explains_metrics(app):
    s = await app.say("/crypto btc")
    text = s.last_text()
    for name in ("Binance", "Bybit", "OKX", "Bitget", "KuCoin"):
        assert name in text
    assert "bid" in text and "ask" in text and "объём" in text.lower()
    assert "last — цена последней сделки" in text


async def test_crypto_unknown_pair_rejected_with_escaped_input(app):
    s = await app.say("/crypto <script>")
    assert "не отслеживается" in s.last_text() and "<script>" not in s.last_text()


# --------------------------------------------------------------------------- сравнение
async def test_compare_sorted_low_to_high_with_min_max_and_diff(app):
    text = (await app.say("/compare BTC/USDT")).last_text()
    order = [text.index(n) for n in ("OKX", "KuCoin", "Binance", "Bybit", "Bitget")]
    assert order == sorted(order)  # по возрастанию последней цены
    assert "Минимум: <b>OKX</b>" in text and "Максимум: <b>Bitget</b>" in text and "Разница" in text and "%" in text


async def test_compare_metric_buttons_switch_metric(app):
    s = await app.press(CompareCb(symbol="BTC/USDT", metric="ask").pack())
    assert "лучший ask" in s.last_text()
    data = s.button_data()
    assert CompareCb(symbol="BTC/USDT", metric="bid").pack() in data


async def test_compare_banks_recommendations(app):
    text = (await app.say("/compare USD/UAH")).last_text()
    assert "Monobank" in text and "PrivatBank" in text and "курс покупки" in text.lower()


async def test_compare_single_source_explains(app):
    app.core.store._quotes = {k: v for k, v in app.core.store._quotes.items() if not (v.symbol == "ETH/USDT" and v.source == "okx")}
    await app.press(SetCb(act="toggle", v="ETH/USDT").pack())
    text = (await app.say("/compare ETH/USDT")).last_text()
    assert "минимум два источника" in text


# --------------------------------------------------------------------------- графики
async def _seed_history(app, symbol="BTC/USDT", source="binance", n=30):
    start = floor_minute(datetime.now(UTC)) - timedelta(minutes=n)
    async with app.db.session() as s:
        await HistoryRepo(s, app.db.dialect).upsert_candles([
            Candle(source, symbol, "1m", start + timedelta(minutes=i), "last", D(100 + i), D(101 + i), D(99 + i), D(100 + i), None, None, 5)
            for i in range(n)
        ])


async def test_chart_sends_png_with_caption_stats(app):
    await _seed_history(app)
    s = await app.say("/history BTC/USDT 1h")
    photos = s.of("SendPhoto")
    assert len(photos) == 1
    caption = photos[0]["caption"]
    assert "BTC/USDT" in caption and "Binance" in caption and "Мин" in caption and "Макс" in caption
    assert any("ch:show" in d for d in s.button_data())


async def test_chart_period_button_replaces_picture_in_place(app):
    await _seed_history(app)
    s = await app.press(ChartCb(step="show", symbol="BTC/USDT", period="1h", source="binance").pack(), photo=True)
    assert s.of("EditMessageMedia") and not s.of("SendPhoto")


async def test_chart_without_enough_history_explains(app):
    text = (await app.say("/history BTC/USDT")).last_text()
    assert "недостаточно" in text or "накапливает" in text


async def test_chart_pick_flow(app):
    s = await app.press(Nav(to="charts").pack())
    assert ChartCb(step="period", symbol="BTC/USDT").pack() in s.button_data()
    s = await app.press(ChartCb(step="period", symbol="BTC/USDT").pack())
    labels = " ".join(b["text"] for r in s.last_markup() for b in r)
    assert "1 час" in labels and "24 часа" in labels and "7 дней" in labels and "30 дней" in labels


# --------------------------------------------------------------------------- уведомления
async def test_full_alert_creation_flow_and_trigger(app):
    await app.say("/start")
    s = await app.press(AlertCb(act="new").pack())
    assert AlertCb(act="type", v="price_above").pack() in s.button_data()
    await app.press(AlertCb(act="type", v="price_above").pack())
    await app.press(AlertCb(act="asset", v="BTC/USDT").pack())
    s = await app.press(AlertCb(act="src", v="binance").pack())
    assert "Binance" in s.last_text() and "BTC/USDT" in s.last_text()

    s = await app.say("abc")  # некорректный ввод не ломает сценарий
    assert "Введите число" in s.last_text()
    s = await app.say("-5")
    assert "Допустимый диапазон" in s.last_text()
    s = await app.say("61 000,5")  # пробелы и запятая допустимы
    assert "Уведомление создано" in s.last_text() and "61\xa0000.5" in s.last_text()

    async with app.db.session() as session:
        (alert,) = await AlertRepo(session).list_for_user(1)
    assert alert.type == "price_above" and alert.threshold == D("61000.5") and alert.source == "binance"

    app.engine.invalidate()
    assert await app.engine.tick() == 1  # цена Binance 61469.25 уже выше порога
    assert "BTC/USDT" in app.sent[0][1] and "Binance" in app.sent[0][1]


async def test_alert_flow_for_percent_change_requires_window(app):
    await app.say("/start")
    await app.press(AlertCb(act="type", v="pct_change").pack())
    await app.press(AlertCb(act="asset", v="USD/UAH").pack())
    s = await app.press(AlertCb(act="src", v="monobank").pack())
    assert AlertCb(act="win", v="60").pack() in s.button_data()
    await app.press(AlertCb(act="win", v="60").pack())
    s = await app.say("1")
    assert "Уведомление создано" in s.last_text()
    async with app.db.session() as session:
        (alert,) = await AlertRepo(session).list_for_user(1)
    assert alert.window_minutes == 60 and alert.threshold == D("1")


async def test_spread_and_arbitrage_alerts_only_offered_for_crypto(app):
    await app.say("/start")
    await app.press(AlertCb(act="type", v="spread").pack())
    s = await app.press(AlertCb(act="asset", v="BTC/USDT").pack())
    s = await app.say("0.05")
    assert "Уведомление создано" in s.last_text()
    # для фиатной пары кнопка выбора актива не должна предлагать USD/UAH
    s = await app.press(AlertCb(act="type", v="arbitrage").pack())
    assert "USD/UAH" not in " ".join(b["text"] for r in s.last_markup() for b in r)


async def test_toggle_delete_and_mute(app):
    await app.say("/start")
    async with app.db.session() as session:
        from app.database.repositories import UserRepo
        user, _, _ = await UserRepo(session).get_or_create(1, None, None, "ru", [])
        alert = await AlertRepo(session).create(user_id=user.id, type="price_above", symbol="BTC/USDT", source="binance", threshold=D(1))
    s = await app.press(AlertCb(act="toggle", v=str(alert.id)).pack())
    assert "⏸" in s.last_text()
    s = await app.press(AlertCb(act="mute", v="8").pack())
    assert "отключены до" in s.last_text()
    s = await app.press(AlertCb(act="unmute").pack())
    assert "отключены до" not in s.last_text()
    s = await app.press(AlertCb(act="del", v=str(alert.id)).pack())
    assert "пока нет уведомлений" in s.last_text()


async def test_cannot_delete_or_toggle_someone_elses_alert(app):
    await app.say("/start", user_id=1)
    await app.say("/start", user_id=2)
    async with app.db.session() as session:
        from app.database.repositories import UserRepo
        owner, _, _ = await UserRepo(session).get_or_create(1, None, None, "ru", [])
        alert = await AlertRepo(session).create(user_id=owner.id, type="price_above", symbol="BTC/USDT", source="binance", threshold=D(1))
    await app.press(AlertCb(act="del", v=str(alert.id)).pack(), user_id=2)
    async with app.db.session() as session:
        assert len(await AlertRepo(session).list_for_user(owner.id)) == 1


async def test_alert_limit_enforced(app):
    app.settings.max_alerts_per_user = 2
    await app.say("/start")
    async with app.db.session() as session:
        from app.database.repositories import UserRepo
        user, _, _ = await UserRepo(session).get_or_create(1, None, None, "ru", [])
        for i in range(2):
            await AlertRepo(session).create(user_id=user.id, type="price_above", symbol="BTC/USDT", source="binance", threshold=D(i + 1))
    s = await app.press(AlertCb(act="new").pack())
    assert any(c[1].get("show_alert") for c in s.calls if c[0] == "AnswerCallbackQuery")


async def test_mute_blocks_delivery(app):
    await app.say("/start")
    await app.press(AlertCb(act="type", v="price_above").pack())
    await app.press(AlertCb(act="asset", v="BTC/USDT").pack())
    await app.press(AlertCb(act="src", v="binance").pack())
    await app.say("100")
    await app.press(AlertCb(act="mute", v="1").pack())
    app.engine.invalidate()
    assert await app.engine.tick() == 0 and app.sent == []


# --------------------------------------------------------------------------- арбитраж
async def test_arbitrage_screen_has_disclaimer_threshold_and_net_numbers(app):
    s = await app.say("/arbitrage")
    text = s.last_text()
    assert "не гарантированная прибыль" in text
    assert "Порог сигнала" in text and "после издержек" in text
    assert ArbCb(act="thr").pack() in s.button_data()


async def test_arbitrage_detail_breaks_down_costs(app):
    s = await app.say("/arbitrage")
    detail = [d for d in s.button_data() if d.startswith("ar:detail")]
    assert detail
    s = await app.press(detail[0])
    text = s.last_text()
    for part in ("комиссии торговли", "проскальзывание", "вывод монеты", "итого", "не гарантированная прибыль"):
        assert part in text


async def test_arbitrage_threshold_setting_persists(app):
    await app.say("/start")
    await app.press(ArbCb(act="set", v="1").pack())
    text = (await app.say("/arbitrage")).last_text()
    assert "<b>1.00%</b>" in text


async def test_arbitrage_without_fresh_data_says_so(app):
    app.core.store._quotes.clear()
    text = (await app.say("/arbitrage")).last_text()
    assert "Недостаточно свежих данных" in text


# --------------------------------------------------------------------------- настройки
async def test_language_switch_changes_interface(app):
    await app.say("/start")
    s = await app.press(SetCb(act="setlang", v="en").pack())
    assert "Language" in s.last_text() and "Settings" in s.last_text()
    s = await app.say("/rates")
    assert "Rates" in s.last_text()


async def test_watchlist_toggle_affects_rates(app):
    await app.say("/start")
    s = await app.press(SetCb(act="toggle", v="BTC/USDT", page=0).pack())
    assert "▫️ BTC/USDT" in " ".join(b["text"] for r in s.last_markup() for b in r)
    assert "BTC/USDT" not in (await app.say("/rates")).last_text()


async def test_unknown_symbol_toggle_is_rejected(app):
    await app.say("/start")
    s = await app.press(SetCb(act="toggle", v="HACK/USDT").pack())
    assert any(c[1].get("show_alert") for c in s.calls if c[0] == "AnswerCallbackQuery")


async def test_display_currency_converts_crypto_prices_via_bank_rate(app):
    await app.say("/start")
    await app.press(SetCb(act="setcur", v="UAH").pack())
    text = (await app.say("/crypto BTC")).last_text()
    # 61 469.25 * 44.8795 (mid Monobank) ≈ 2 758 6xx
    assert "2 7" in text.replace(" ", " ") and "пересчитаны в UAH" in text


async def test_display_currency_falls_back_when_no_bank_rate(app):
    await app.say("/start")
    await app.press(SetCb(act="setcur", v="UAH").pack())
    app.core.store._quotes = {k: v for k, v in app.core.store._quotes.items() if v.symbol != "USD/UAH"}
    text = (await app.say("/crypto BTC")).last_text()
    assert "недоступен" in text and "61 469" in text.replace(" ", " ")


async def test_settings_persist_chart_and_interval_options(app):
    await app.say("/start")
    await app.press(SetCb(act="setperiod", v="7d").pack())
    await app.press(SetCb(act="settheme", v="light").pack())
    await app.press(SetCb(act="setint", v="30").pack())
    text = (await app.say("/settings")).last_text()
    assert "7 дней" in text and "Светлая" in text and "30 мин" in text


async def test_invalid_callback_payloads_do_not_crash(app):
    for data in ("garbage", "al:bogus:x", "st:setlang:zz", "ch:show:NOPE:1h:", "ar:detail:NOPE:", "cr:NOPE", "cp:NOPE:last", "ad:toggle:x"):
        app.session.clear()
        await app.press(data)
        assert "Что-то пошло не так" not in " ".join(app.session.texts())


# --------------------------------------------------------------------------- админка
async def test_admin_commands_denied_for_regular_users(app):
    for cmd in ("/admin", "/stats", "/users", "/sources", "/errors", "/addpair SOL/USDT", "/ban 5"):
        app.session.clear()
        s = await app.say(cmd, user_id=1)
        assert not any("Админ" in t or "Статистика" in t or "Источники" in t for t in s.texts()), cmd
    s = await app.press(AdminCb(act="toggle", v="binance").pack(), user_id=1)
    assert app.core.health.is_enabled("binance")


async def test_admin_panel_and_pages(app):
    s = await app.say("/admin", user_id=999)
    assert "Админ-панель" in s.last_text()
    s = await app.say("/stats", user_id=999)
    assert "Пользователи" in s.last_text() and "Источники" in s.last_text()
    s = await app.say("/users", user_id=999)
    assert "Пользователи" in s.last_text()
    s = await app.say("/errors", user_id=999)
    assert "Ошибок нет" in s.last_text() or "ошибки" in s.last_text()


async def test_admin_can_disable_and_enable_source_and_data_disappears(app):
    s = await app.say("/sources", user_id=999)
    assert "Binance" in s.last_text() and "Monobank" in s.last_text()
    await app.press(AdminCb(act="toggle", v="binance").pack(), user_id=999)
    assert not app.core.health.is_enabled("binance")
    assert "Binance" not in (await app.say("/crypto BTC", user_id=999)).last_text().split("Пара не торгуется")[0].replace("Включить Binance", "")
    await app.press(AdminCb(act="toggle", v="binance").pack(), user_id=999)
    assert app.core.health.is_enabled("binance")


async def test_admin_global_settings_roundtrip_and_validation(app):
    s = await app.press(AdminCb(act="settings").pack(), user_id=999)
    assert "Глобальные настройки" in s.last_text()
    await app.press(AdminCb(act="flip", v="signups_enabled").pack(), user_id=999)
    assert app.core.runtime.get("signups_enabled") is False
    await app.press(AdminCb(act="edit", v="arb_trade_size_usdt").pack(), user_id=999)
    s = await app.say("5", user_id=999)  # меньше минимума
    assert "минимум" in s.last_text()
    s = await app.say("2500", user_id=999)
    assert "2500" in s.last_text() and app.core.runtime.get("arb_trade_size_usdt") == D("2500")


async def test_signups_closed_blocks_new_users_only(app):
    await app.say("/start", user_id=1)
    await app.core.runtime.set(app.db, "signups_enabled", "off")
    s = await app.say("/start", user_id=42)
    assert "Регистрация" in s.last_text()
    assert not await app.ctx.users.exists(42)
    s = await app.say("/rates", user_id=1)  # существующий пользователь работает
    assert "Курсы" in s.last_text()


async def test_ban_stops_user(app):
    await app.say("/start", user_id=5)
    await app.say("/ban 5", user_id=999)
    app.session.clear()
    await app.say("/rates", user_id=5)
    assert app.session.texts() == []
    await app.say("/unban 5", user_id=999)
    assert (await app.say("/rates", user_id=5)).texts()


async def test_addpair_rejects_bad_input_and_unknown_pairs(app):
    s = await app.say("/addpair hello", user_id=999)
    assert "Неверный формат" in s.last_text()
    s = await app.say("/addpair BTC/EUR", user_id=999)
    assert "USDT" in s.last_text() or "Смешанные" in s.last_text()
    s = await app.say("/addpair BTC/USDT", user_id=999)
    assert "уже отслеживается" in s.last_text()


# --------------------------------------------------------------------------- защита
async def test_rate_limit_drops_excess_messages():
    a = await BotApp.create(rate_limit=3)
    a.load_market()
    try:
        for _ in range(8):
            await a.say("/rates", user_id=1)
        assert len(a.session.of("SendMessage")) == 3
        await a.say("/rates", user_id=2)  # другой пользователь не затронут
        assert len(a.session.of("SendMessage")) == 4
    finally:
        await a.close()


async def test_rate_limit_answers_callbacks_with_notice():
    a = await BotApp.create(rate_limit=1)
    try:
        await a.press(Nav(to="rates").pack())
        a.session.clear()
        await a.press(Nav(to="rates").pack())
        assert a.session.of("AnswerCallbackQuery") and not a.session.of("EditMessageText")
    finally:
        await a.close()


async def test_groups_are_ignored(app):
    from aiogram.types import Chat, Message, Update

    from tests.bot_harness import BOT_USER  # noqa: F401

    message = Message(message_id=1, date=datetime.now(UTC), chat=Chat(id=-100, type="supergroup"),
                      from_user=app._user(1, "X", "ru"), text="/rates")
    await app.dp.feed_update(app.bot, Update(update_id=999, message=message))
    assert app.session.texts() == []


async def test_works_without_redis_using_memory_storage():
    a = await BotApp.create(redis=False)
    a.load_market()
    try:
        await a.say("/start")
        await a.press(AlertCb(act="type", v="price_above").pack())
        await a.press(AlertCb(act="asset", v="BTC/USDT").pack())
        await a.press(AlertCb(act="src", v="binance").pack())
        s = await a.say("100")
        assert "Уведомление создано" in s.last_text()
    finally:
        await a.close()


async def test_crypto_callback_and_back_navigation(app):
    s = await app.press(CryptoCb(symbol="BTC/USDT").pack())
    assert "BTC/USDT" in s.last_text()
    assert Nav(to="crypto").pack() in s.button_data()


def test_clip_cuts_on_line_boundary_and_keeps_html_balanced():
    from app.bot.utils import clip

    lines = [f"<b>Источник {i}</b>: ошибка {'x' * 180}" for i in range(40)]
    clipped = clip("\n".join(lines), 4000)
    assert len(clipped) <= 4000 and clipped.endswith("…")
    assert clipped.count("<b>") == clipped.count("</b>")
    assert clip("короткий текст") == "короткий текст"
    assert len(clip("x" * 9000, 4000)) <= 4000  # даже без переводов строки
