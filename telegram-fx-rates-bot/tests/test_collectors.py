"""Поведение сборщиков с управляемым поддельным провайдером (без сети)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.cache import QuoteStore
from app.collectors import BankCollector, ExchangeCollector
from app.config import Settings
from app.domain import Quote, SourceKind
from app.providers.base import BaseProvider, ExchangeProvider
from app.services.assets import AssetRegistry
from app.services.health import HealthRegistry
from app.utils.http import AsyncRateLimiter, HttpClient, ProviderError, RateLimitedError
from tests.conftest import make_quote


class FakeExchange(ExchangeProvider):
    name = "fake"
    display_name = "Fake"

    def __init__(self, listed: set[str]):
        super().__init__(HttpClient(), "http://x", AsyncRateLimiter(1000, 1000))
        self.listed = listed
        self.calls: list[list[str]] = []
        self.raise_error: Exception | None = None
        self.fail_symbols: set[str] = set()

    async def fetch_one(self, symbol: str) -> Quote | None:
        if self.raise_error:
            raise self.raise_error
        if symbol in self.fail_symbols:
            raise ProviderError("boom")
        if symbol not in self.listed:
            return None
        return make_quote(source=self.name, symbol=symbol, received_at=datetime.now(UTC))

    async def fetch_detailed(self, symbols):
        self.calls.append(list(symbols))
        return await super().fetch_detailed(symbols)


class FakeBank(BaseProvider):
    name = "fakebank"
    display_name = "FakeBank"
    kind = SourceKind.BANK

    def __init__(self):
        super().__init__(HttpClient())
        self.error: Exception | None = None
        self.calls = 0

    async def fetch_quotes(self, symbols=()):
        self.calls += 1
        if self.error:
            raise self.error
        return [make_quote(source="fakebank", symbol="USD/UAH", kind=SourceKind.BANK, last=None, bid="41", ask="42"),
                make_quote(source="fakebank", symbol="XXX/UAH", kind=SourceKind.BANK, last=None, bid="1", ask="2")]


def build(provider, crypto=("BTC/USDT", "TON/USDT"), fiat=("USD/UAH",)):
    settings = Settings(_env_file=None, ws_enabled=False, stale_watchdog_seconds=5, crypto_fresh_seconds=45)
    store = QuoteStore()
    health = HealthRegistry()
    health.register(provider.name, provider.kind)
    assets = AssetRegistry()
    assets._set(list(crypto), list(fiat))
    return settings, store, health, assets


async def test_first_tick_classifies_listed_and_unlisted_pairs():
    provider = FakeExchange(listed={"BTC/USDT"})
    settings, store, health, assets = build(provider)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    assert collector._listed == {"BTC/USDT"} and collector._unlisted == {"TON/USDT"}
    assert store.get("fake", "BTC/USDT") is not None
    assert store.get("fake", "TON/USDT") is None
    assert health.get("fake").unlisted == ("TON/USDT",)
    assert health.get("fake").last_success_at is not None


async def test_transient_pair_failure_does_not_mark_pair_as_unlisted():
    provider = FakeExchange(listed={"BTC/USDT", "TON/USDT"})
    provider.fail_symbols = {"TON/USDT"}
    settings, store, health, assets = build(provider)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    assert collector._unlisted == set()  # сбой запроса ≠ «пары нет на бирже»
    assert collector._listed == {"BTC/USDT"}
    assert health.get("fake").total_errors == 1


async def test_new_pair_is_fetched_without_full_sweep():
    provider = FakeExchange(listed={"BTC/USDT", "TON/USDT", "ETH/USDT"})
    settings, store, health, assets = build(provider)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    provider.calls.clear()
    assets._set(["BTC/USDT", "TON/USDT", "ETH/USDT"], ["USD/UAH"])
    await collector._tick()
    assert provider.calls == [["ETH/USDT"]]
    assert "ETH/USDT" in collector._listed


async def test_watchdog_refreshes_only_stale_pairs_via_rest():
    provider = FakeExchange(listed={"BTC/USDT", "TON/USDT"})
    settings, store, health, assets = build(provider)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    # BTC свежий, TON устарел
    store.put(make_quote(source="fake", symbol="BTC/USDT", received_at=datetime.now(UTC)))
    store._quotes["fake|TON/USDT"] = make_quote(
        source="fake", symbol="TON/USDT", received_at=datetime.now(UTC) - timedelta(seconds=40)
    )
    provider.calls.clear()
    await collector._tick()
    assert provider.calls == [["TON/USDT"]]


async def test_rate_limit_pauses_requests_and_records_error():
    provider = FakeExchange(listed={"BTC/USDT"})
    provider.raise_error = RateLimitedError("429", retry_after=120)
    settings, store, health, assets = build(provider)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    calls = len(provider.calls)
    await collector._tick()  # пауза ещё не истекла — новых запросов нет
    assert len(provider.calls) == calls
    assert health.get("fake").consecutive_errors == 1


async def test_source_failure_keeps_other_sources_running():
    broken = FakeExchange(listed={"BTC/USDT"})
    broken.raise_error = ProviderError("down")
    healthy = FakeExchange(listed={"BTC/USDT"})
    healthy.name = "fake2"
    settings, store, health, assets = build(broken)
    health.register("fake2", SourceKind.EXCHANGE)
    c1 = ExchangeCollector(broken, store, health, assets, settings)
    c2 = ExchangeCollector(healthy, store, health, assets, settings)
    await c1._tick()
    await c2._tick()
    assert store.get("fake", "BTC/USDT") is None
    assert store.get("fake2", "BTC/USDT") is not None
    assert health.get("fake").state(datetime.now(UTC), 45) == "down" or health.get("fake").consecutive_errors == 1


async def test_disabled_source_makes_no_requests():
    provider = FakeExchange(listed={"BTC/USDT"})
    settings, store, health, assets = build(provider)
    health.set_enabled("fake", False)
    collector = ExchangeCollector(provider, store, health, assets, settings)
    await collector._tick()
    assert provider.calls == []


async def test_bank_collector_saves_only_tracked_pairs_and_stores_all():
    bank = FakeBank()
    settings, store, health, assets = build(bank)
    saved: list[Quote] = []

    async def on_batch(quotes):
        saved.extend(quotes)

    collector = BankCollector(bank, store, health, assets, 300, on_batch)
    delay = await collector._poll_once()
    assert delay == 300
    assert {q.symbol for q in saved} == {"USD/UAH"}  # XXX/UAH не отслеживается
    assert store.get("fakebank", "XXX/UAH") is not None  # но доступен в кеше


async def test_bank_collector_backoff_on_errors_and_rate_limit():
    bank = FakeBank()
    settings, store, health, assets = build(bank)
    collector = BankCollector(bank, store, health, assets, 300)
    bank.error = ProviderError("down")
    assert await collector._poll_once() == 30  # первая ошибка — повтор через 30 с
    assert await collector._poll_once() == 60
    bank.error = RateLimitedError("429", retry_after=60)
    assert await collector._poll_once() == 300  # не чаще штатного интервала
    bank.error = None
    assert await collector._poll_once() == 300
    assert collector._failures == 0


async def test_bank_collector_skips_disabled_source():
    bank = FakeBank()
    settings, store, health, assets = build(bank)
    health.set_enabled("fakebank", False)
    collector = BankCollector(bank, store, health, assets, 300)
    await collector._poll_once()
    assert bank.calls == 0


@pytest.mark.parametrize("errors,expected", [(0, "ok"), (1, "degraded"), (3, "down")])
def test_health_state(errors, expected):
    health = HealthRegistry()
    h = health.register("x", SourceKind.EXCHANGE)
    health.record_success("x")
    h.consecutive_errors = errors
    assert h.state(datetime.now(UTC), 45) == expected


async def test_health_state_unknown_and_stale_ws():
    health = HealthRegistry()
    h = health.register("x", SourceKind.EXCHANGE, supports_ws=True)
    assert h.state(datetime.now(UTC), 45) == "unknown"
    health.record_success("x")
    assert h.state(datetime.now(UTC), 45) == "degraded"  # WebSocket ещё не подключён
    health.set_ws("x", True)
    assert h.state(datetime.now(UTC), 45) == "ok"
    assert h.state(datetime.now(UTC) + timedelta(seconds=100), 45) == "degraded"
    assert h.state(datetime.now(UTC) + timedelta(seconds=500), 45) == "down"
    await asyncio.sleep(0)
