from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.alerts import AlertEngine
from app.cache import QuoteStore
from app.config import Settings
from app.database import Database
from app.database.repositories import AlertRepo, Candle, HistoryRepo, UserRepo
from app.domain import SourceKind
from app.services.health import HealthRegistry
from app.services.history import floor_minute
from app.services.quotes import QuoteService
from app.services.runtime_settings import RuntimeSettings
from tests.conftest import make_quote


class Harness:
    def __init__(self, db: Database):
        self.db = db
        self.settings = Settings(_env_file=None)
        self.store = QuoteStore()
        self.runtime = RuntimeSettings(self.settings)
        self.quotes = QuoteService(self.store, HealthRegistry(), self.runtime, self.settings)
        self.sent: list[tuple[int, str]] = []
        self.delivery: bool | None = True
        self.engine = AlertEngine(db, self.store, self.quotes, self.runtime, self.settings, self.send)

    async def send(self, telegram_id: int, text: str):
        if self.delivery:
            self.sent.append((telegram_id, text))
        return self.delivery

    def price(self, value: str, source="binance", symbol="BTC/USDT", **kw):
        self.store.put(make_quote(source=source, symbol=symbol, last=value, bid=value, ask=value, **kw))

    async def alert(self, type_="price_above", threshold="100", user_tid=1, **fields):
        async with self.db.session() as s:
            user, settings, _ = await UserRepo(s).get_or_create(user_tid, None, None, fields.pop("lang", "ru"), [])
            data = dict(user_id=user.id, type=type_, symbol="BTC/USDT", source="binance", threshold=D(threshold),
                        cooldown_minutes=15)
            data.update(fields)
            alert = await AlertRepo(s).create(**data)
            return alert.id, user.id

    async def tick(self, now=None) -> int:
        self.engine.invalidate()
        return await self.engine.tick(now)


@pytest.fixture
async def h():
    db = Database("sqlite+aiosqlite://")
    await db.create_all()
    yield Harness(db)
    await db.dispose()


async def test_price_above_fires_once_with_spec_style_message(h):
    await h.alert("price_above", "100")
    h.price("99")
    assert await h.tick() == 0
    h.price("101")
    assert await h.tick() == 1
    assert "BTC/USDT" in h.sent[0][1] and "Binance" in h.sent[0][1] and "101" in h.sent[0][1]
    h.price("105")
    assert await h.tick() == 0  # цена всё ещё выше — повтора нет
    assert len(h.sent) == 1


async def test_rearms_after_condition_resets_but_respects_cooldown(h):
    await h.alert("price_above", "100")
    t0 = datetime.now(UTC)
    h.price("101"); assert await h.tick(t0) == 1
    h.price("99"); await h.tick(t0 + timedelta(minutes=1))  # условие сброшено → «заряжено»
    h.price("102"); assert await h.tick(t0 + timedelta(minutes=2)) == 0  # интервал 15 мин ещё не прошёл
    assert await h.tick(t0 + timedelta(minutes=16)) == 1  # прошёл — отправляем
    assert len(h.sent) == 2


async def test_user_notification_interval_extends_cooldown(h):
    async with h.db.session() as s:
        user, settings, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        await UserRepo(s).update_settings(user.id, notify_interval_min=60)
    await h.alert("price_above", "100")
    t0 = datetime.now(UTC)
    h.price("101"); await h.tick(t0)
    h.price("99"); await h.tick(t0 + timedelta(minutes=1))
    h.price("101")
    assert await h.tick(t0 + timedelta(minutes=30)) == 0  # 15 мин прошло, но пользователь просил не чаще часа
    assert await h.tick(t0 + timedelta(minutes=61)) == 1


async def test_price_below(h):
    await h.alert("price_below", "100")
    h.price("101"); assert await h.tick() == 0
    h.price("99.5"); assert await h.tick() == 1
    assert "99.5" in h.sent[0][1]


async def test_muted_user_gets_nothing_then_signal_after_mute(h):
    await h.alert("price_above", "100")
    async with h.db.session() as s:
        user, _, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        await UserRepo(s).update_settings(user.id, alerts_muted_until=datetime.now(UTC) + timedelta(hours=1))
    h.price("101")
    assert await h.tick() == 0
    assert await h.tick(datetime.now(UTC) + timedelta(hours=2)) == 1  # пауза закончилась, условие всё ещё выполняется


async def test_stale_data_does_not_fire_or_change_state(h):
    await h.alert("price_above", "100")
    h.price("500", received_at=datetime.now(UTC) - timedelta(minutes=10))
    assert await h.tick() == 0 and h.sent == []


async def test_paused_alert_is_ignored(h):
    alert_id, user_id = await h.alert("price_above", "100", is_active=False)
    h.price("500")
    assert await h.tick() == 0


async def test_global_switch_disables_all_alerts(h):
    await h.alert("price_above", "100")
    h.price("500")
    await h.runtime.set(h.db, "alerts_enabled", "off")
    assert await h.tick() == 0


async def test_transient_send_failure_is_retried_without_losing_the_alert(h):
    await h.alert("price_above", "100")
    h.price("101")
    h.delivery = False
    assert await h.tick() == 0
    h.delivery = True
    assert await h.tick() == 1


async def test_user_who_blocked_the_bot_is_marked_and_skipped(h):
    await h.alert("price_above", "100")
    h.price("101")
    h.delivery = None
    assert await h.tick() == 0
    h.delivery = True
    assert await h.tick() == 0  # заблокированному пользователю больше не шлём
    async with h.db.session() as s:
        from sqlalchemy import select

        from app.database.models import User
        assert (await s.execute(select(User.is_blocked))).scalar_one() is True


async def test_pct_change_uses_history_reference(h):
    await h.alert("pct_change", "1", window_minutes=60)
    ref_time = floor_minute(datetime.now(UTC) - timedelta(minutes=60))
    async with h.db.session() as s:
        await HistoryRepo(s, h.db.dialect).upsert_candles([
            Candle("binance", "BTC/USDT", "1m", ref_time, "last", D(100), D(100), D(100), D(100), None, None, 1)])
    h.price("100.5"); assert await h.tick() == 0  # +0.5% < 1%
    h.engine._reference.clear()
    h.price("102"); assert await h.tick() == 1
    assert "+2.00%" in h.sent[0][1]


async def test_pct_change_without_history_stays_silent(h):
    await h.alert("pct_change", "1", window_minutes=60)
    h.price("500")
    assert await h.tick() == 0


async def test_bank_price_alert_uses_mid_rate(h):
    await h.alert("price_above", "45", source="monobank", symbol="USD/UAH")
    h.store.put(make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="44.5", ask="45.2", last=None))
    assert await h.tick() == 0  # mid = 44.85
    h.store.put(make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="44.9", ask="45.3", last=None,
                           received_at=datetime.now(UTC) + timedelta(seconds=1)))
    assert await h.tick() == 1  # mid = 45.10


async def test_spread_alert_names_both_exchanges(h):
    await h.alert("spread", "0.5", source=None, lang="en")
    h.price("100", "binance"); h.price("100.2", "okx")
    assert await h.tick() == 0
    h.price("101", "bybit")
    assert await h.tick() == 1
    text = h.sent[0][1]
    assert "Binance" in text and "Bybit" in text and "1.00%" in text


async def test_arbitrage_alert_has_disclaimer_and_uses_net_percent(h):
    await h.alert("arbitrage", "0.5", source=None, lang="en")
    h.store.put(make_quote(source="binance", bid="99", ask="100", ask_size="50", bid_size="50"))
    h.store.put(make_quote(source="okx", bid="100.2", ask="101", ask_size="50", bid_size="50"))
    assert await h.tick() == 0  # разница 0.2% съедена комиссиями
    h.store.put(make_quote(source="okx", bid="103", ask="104", ask_size="50", bid_size="50",
                           received_at=datetime.now(UTC) + timedelta(seconds=1)))
    assert await h.tick() == 1
    assert "not guaranteed profit" in h.sent[0][1] and "Binance" in h.sent[0][1]


async def test_history_row_written_for_each_trigger(h):
    await h.alert("price_above", "100")
    h.price("101"); await h.tick()
    async with h.db.session() as s:
        _, user_id = 0, None
        user, _, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        rows = await AlertRepo(s).history_for_user(user.id)
        assert len(rows) == 1 and rows[0].delivered and rows[0].symbol == "BTC/USDT"


async def test_no_repeat_while_condition_stays_true_even_after_cooldown(h):
    """Защита «по фронту»: цена непрерывно выше порога — повторов нет, даже когда интервал давно прошёл."""
    await h.alert("price_above", "100")
    t0 = datetime.now(UTC)
    h.price("101"); assert await h.tick(t0) == 1
    assert await h.tick(t0 + timedelta(hours=5)) == 0
    assert await h.tick(t0 + timedelta(hours=10)) == 0
    assert len(h.sent) == 1
