"""Репозитории и агрегация истории на SQLite (та же логика SQLAlchemy, что и в PostgreSQL)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.database import Database
from app.database.repositories import (
    AlertRepo,
    AppSettingsRepo,
    AssetRepo,
    Candle,
    HistoryRepo,
    RatesRepo,
    StatusRepo,
    UserRepo,
)
from app.domain import SourceKind
from app.services.assets import AssetRegistry
from app.services.history import HistoryAggregator, floor_hour, floor_minute
from tests.conftest import make_quote


@pytest.fixture
async def db():
    database = Database("sqlite+aiosqlite://")
    await database.create_all()
    yield database
    await database.dispose()


def minute(offset: int = 0) -> datetime:
    return floor_minute(datetime.now(UTC)) - timedelta(minutes=offset)


async def test_user_creation_is_idempotent_and_has_settings(db):
    async with db.session() as s:
        user, settings, created = await UserRepo(s).get_or_create(100, "neo", "Thomas", "ru", ["BTC/USDT"])
        assert created and settings.watchlist == ["BTC/USDT"] and settings.language == "ru"
    async with db.session() as s:
        user2, _, created2 = await UserRepo(s).get_or_create(100, "neo2", "Thomas", "ru", [])
        assert not created2 and user2.id == user.id and user2.username == "neo2"
        assert await UserRepo(s).count() == 1


async def test_update_user_settings(db):
    async with db.session() as s:
        user, _, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        await UserRepo(s).update_settings(user.id, language="en", arb_min_net_pct=Decimal("0.75"))
    async with db.session() as s:
        _, settings, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        assert settings.language == "en" and settings.arb_min_net_pct == Decimal("0.75")


async def test_asset_seed_does_not_resurrect_disabled_pairs(db):
    async with db.session() as s:
        repo = AssetRepo(s)
        assert await repo.seed(["BTC/USDT", "USD/UAH"]) == 2
        await repo.set_active("BTC/USDT", False)
    async with db.session() as s:
        assert await AssetRepo(s).seed(["BTC/USDT", "ETH/USDT"]) == 1
        active = {a.symbol: a.kind for a in await AssetRepo(s).list_active()}
        assert active == {"USD/UAH": "fiat", "ETH/USDT": "crypto"}


async def test_exchange_rates_upsert_updates_existing_row(db):
    async with db.session() as s:
        await RatesRepo(s, db.dialect).upsert_exchange_rates([make_quote(bid="1", ask="2")])
    async with db.session() as s:
        await RatesRepo(s, db.dialect).upsert_exchange_rates([make_quote(bid="5", ask="6"), make_quote(source="okx")])
    async with db.session() as s:
        from sqlalchemy import select

        from app.database.models import ExchangeRate

        rows = {r.source: r for r in (await s.execute(select(ExchangeRate))).scalars()}
        assert set(rows) == {"binance", "okx"} and rows["binance"].bid == Decimal("5")


async def test_candle_upsert_merges_high_low_close_samples(db):
    start = minute(5)
    def candle(o, h, l, c, n, res="1m"):
        return Candle("binance", "BTC/USDT", res, start, "last", Decimal(o), Decimal(h), Decimal(l), Decimal(c),
                      Decimal(c) - 1, Decimal(c) + 1, n)

    async with db.session() as s:
        await HistoryRepo(s, db.dialect).upsert_candles([candle("100", "110", "95", "105", 3)])
    async with db.session() as s:
        await HistoryRepo(s, db.dialect).upsert_candles([candle("999", "120", "90", "101", 2)])
    async with db.session() as s:
        (row,) = await HistoryRepo(s, db.dialect).series("binance", "BTC/USDT", "1m", start - timedelta(hours=1))
        assert (row.open, row.high, row.low, row.close, row.samples) == (
            Decimal("100"), Decimal("120"), Decimal("90"), Decimal("101"), 5)


async def test_price_at_and_series_and_cleanup(db):
    now = datetime.now(UTC)
    old = floor_minute(now - timedelta(hours=100))
    recent = floor_minute(now - timedelta(minutes=30))
    async with db.session() as s:
        repo = HistoryRepo(s, db.dialect)
        await repo.upsert_candles([
            Candle("binance", "BTC/USDT", "1m", old, "last", Decimal(1), Decimal(1), Decimal(1), Decimal(1), None, None, 1),
            Candle("binance", "BTC/USDT", "1m", recent, "last", Decimal(7), Decimal(8), Decimal(6), Decimal(7), None, None, 1),
            Candle("binance", "BTC/USDT", "1h", floor_hour(old), "last", Decimal(1), Decimal(1), Decimal(1), Decimal(1), None, None, 1),
        ])
    async with db.session() as s:
        repo = HistoryRepo(s, db.dialect)
        assert await repo.price_at("binance", "BTC/USDT", now - timedelta(minutes=10), timedelta(hours=1)) == Decimal(7)
        assert await repo.price_at("binance", "BTC/USDT", now - timedelta(minutes=50), timedelta(minutes=5)) is None
        assert await repo.sources_for("BTC/USDT") == ["binance"]
        removed = await repo.cleanup(timedelta(hours=72), timedelta(days=120))
        assert removed == 1  # удалена только минутная свеча старше 72 часов
        assert len(await repo.series("binance", "BTC/USDT", "1h", old - timedelta(days=1))) == 1


async def test_bank_rates_only_changes_are_persisted(db):
    from app.cache import QuoteStore
    from app.config import Settings
    from app.services.health import HealthRegistry
    from app.services.persistence import PersistenceService

    assets = AssetRegistry()
    persistence = PersistenceService(db, QuoteStore(), assets, HealthRegistry(), Settings(_env_file=None))
    await persistence.start()
    try:
        q1 = make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="41", ask="42", last=None)
        assert await persistence.save_bank_quotes([q1]) == 1
        assert await persistence.save_bank_quotes([q1]) == 0  # курс не изменился — строка не добавляется
        q2 = make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="41", ask="42.5", last=None)
        assert await persistence.save_bank_quotes([q2]) == 1
    finally:
        await persistence.stop()
    async with db.session() as s:
        last = await RatesRepo(s, db.dialect).last_bank_rates()
        assert last[("monobank", "USD/UAH")][1] == Decimal("42.5")


async def test_alert_lifecycle_and_ownership(db):
    async with db.session() as s:
        u1, _, _ = await UserRepo(s).get_or_create(1, None, None, "ru", [])
        u2, _, _ = await UserRepo(s).get_or_create(2, None, None, "en", [])
        repo = AlertRepo(s)
        a = await repo.create(user_id=u1.id, type="price_above", symbol="BTC/USDT", source="binance", threshold=Decimal(100))
        assert await repo.delete(u2.id, a.id) is False  # чужое уведомление удалить нельзя
        assert await repo.toggle(u2.id, a.id) is None
        assert (await repo.toggle(u1.id, a.id)).is_active is False
        assert await repo.list_active() == []
        await repo.toggle(u1.id, a.id)
        (active,) = await repo.list_active()
        assert active.telegram_id == 1 and active.language == "ru" and active.armed
        assert await repo.delete(u1.id, a.id) is True


async def test_status_and_errors_and_app_settings(db):
    now = datetime.now(UTC)
    async with db.session() as s:
        repo = StatusRepo(s, db.dialect)
        await repo.upsert_many([{"source": "okx", "kind": "exchange", "is_enabled": True, "ws_connected": True,
                                 "last_success_at": now, "last_message_at": None, "last_error_at": None,
                                 "last_error": None, "consecutive_errors": 0, "total_errors": 0, "updated_at": now}])
        await repo.set_enabled("okx", False, "exchange")
        await repo.add_errors([("okx", "boom", now)])
        assert (await repo.load_all())["okx"].is_enabled is False
        assert [e.message for e in await repo.recent_errors()] == ["boom"]
        settings = AppSettingsRepo(s, db.dialect)
        await settings.set("arb_slippage_pct", "0.1")
        await settings.set("arb_slippage_pct", "0.2")
        assert await settings.all() == {"arb_slippage_pct": "0.2"}


async def test_aggregator_builds_minute_and_hour_candles(db):
    assets = AssetRegistry()
    assets._set(["BTC/USDT"], ["USD/UAH"])
    agg = HistoryAggregator(db, assets)
    t0 = minute(2)
    for i, price in enumerate(["100", "105", "98", "102"]):
        agg.on_quote(make_quote(last=price, bid=str(int(price) - 1), ask=str(int(price) + 1),
                                received_at=t0 + timedelta(seconds=i * 10)))
    agg.on_quote(make_quote(last="110", received_at=t0 + timedelta(minutes=1, seconds=5)))
    agg.on_quote(make_quote(symbol="XYZ/USDT", last="5", received_at=t0))  # не отслеживается — игнорируется
    assert await agg.flush() == 2  # обе минуты завершены (текущее время позже)
    async with db.session() as s:
        repo = HistoryRepo(s, db.dialect)
        rows = await repo.series("binance", "BTC/USDT", "1m", t0 - timedelta(hours=1))
        assert [(r.open, r.high, r.low, r.close, r.samples) for r in rows] == [
            (Decimal(100), Decimal(105), Decimal(98), Decimal(102), 4),
            (Decimal(110), Decimal(110), Decimal(110), Decimal(110), 1),
        ]
        hours = await repo.series("binance", "BTC/USDT", "1h", floor_hour(t0) - timedelta(hours=2))
        assert sum(h.samples for h in hours) == 5
        assert not await repo.series("binance", "XYZ/USDT", "1m", t0 - timedelta(hours=1))


async def test_aggregator_uses_mid_for_banks_and_keeps_failed_flush(db):
    assets = AssetRegistry()
    assets._set([], ["USD/UAH"])
    agg = HistoryAggregator(db, assets)
    agg.on_quote(make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="40", ask="42",
                            last=None, received_at=minute(3)))
    await agg.flush()
    async with db.session() as s:
        (row,) = await HistoryRepo(s, db.dialect).series("monobank", "USD/UAH", "1m", minute(10))
        assert row.price_kind == "mid" and row.close == Decimal(41) and row.bid == Decimal(40)

    # БД недоступна — свечи остаются в очереди и сохраняются при следующем сбросе
    agg.on_quote(make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="44", ask="46",
                            last=None, received_at=minute(2)))
    await db.dispose()
    await db.engine.dispose()
    original = db.session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def broken():
        raise RuntimeError("db down")
        yield

    db.session = broken  # type: ignore[method-assign]
    assert await agg.flush() == 0
    assert len(agg._pending) == 1
    db.session = original  # type: ignore[method-assign]
