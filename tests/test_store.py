from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import fakeredis.aioredis
import pytest

from app.cache import QuoteStore, UserRateLimiter
from app.cache.store import REDIS_HASH
from app.domain import Freshness, SourceKind
from tests.conftest import make_quote

NOW = datetime.now(UTC)


def test_put_get_and_listeners():
    store = QuoteStore()
    seen = []
    store.add_listener(seen.append)
    q = make_quote()
    assert store.put(q) is True
    assert store.get("binance", "BTC/USDT") == q
    assert seen == [q]


def test_quote_without_any_price_is_rejected():
    store = QuoteStore()
    assert store.put(make_quote(bid=None, ask=None, last=None)) is False
    assert store.all() == []


def test_older_quote_does_not_overwrite_newer():
    store = QuoteStore()
    new = make_quote(bid="200", ask="201", received_at=NOW)
    old = make_quote(bid="100", ask="101", received_at=NOW - timedelta(seconds=30))
    store.put(new)
    assert store.put(old) is False
    assert store.get("binance", "BTC/USDT").bid == Decimal("200")


def test_volume_carried_over_from_rest_to_stream_quotes():
    store = QuoteStore()
    store.put(make_quote(volume="1234", received_at=NOW))
    store.put(make_quote(bid="150", ask="151", volume=None, received_at=NOW + timedelta(seconds=1)))
    q = store.get("binance", "BTC/USDT")
    assert q.volume_24h == Decimal("1234") and q.bid == Decimal("150")


def test_disabled_source_is_hidden():
    store = QuoteStore()
    store.put(make_quote(source="binance"))
    store.put(make_quote(source="okx"))
    store.set_disabled({"binance"})
    assert [q.source for q in store.for_symbol("BTC/USDT")] == ["okx"]
    assert store.get("binance", "BTC/USDT") is None
    assert [q.source for q in store.all()] == ["okx"]


def test_usable_returns_only_fresh_quotes():
    store = QuoteStore(crypto_fresh_seconds=45, bank_fresh_seconds=900)
    fresh = make_quote(source="binance", received_at=datetime.now(UTC))
    stale = make_quote(source="okx", received_at=datetime.now(UTC) - timedelta(seconds=120))
    bank = make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, last=None,
                      received_at=datetime.now(UTC) - timedelta(seconds=300))
    store.put_many([fresh, stale, bank])
    assert store.freshness(stale) is Freshness.STALE
    assert store.freshness(bank) is Freshness.FRESH  # у банка своё окно свежести
    assert {q.source for q in store.usable([fresh, stale, bank])} == {"binance", "monobank"}


async def test_redis_write_through_and_warmup():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = QuoteStore(redis)
    store.put(make_quote(bid="42", ask="43"))
    await store.flush()
    assert "binance|BTC/USDT" in await redis.hgetall(REDIS_HASH)

    fresh_store = QuoteStore(redis)
    assert await fresh_store.warm_from_redis() == 1
    assert fresh_store.get("binance", "BTC/USDT").bid == Decimal("42")


async def test_warmup_does_not_call_listeners():
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    first = QuoteStore(redis)
    first.put(make_quote())
    await first.flush()
    second = QuoteStore(redis)
    calls = []
    second.add_listener(calls.append)
    await second.warm_from_redis()
    assert calls == []


async def test_rate_limiter_memory_and_redis():
    for redis in (None, fakeredis.aioredis.FakeRedis(decode_responses=True)):
        limiter = UserRateLimiter(redis, limit=3, window_seconds=10)
        results = [await limiter.allow(1) for _ in range(5)]
        assert results == [True, True, True, False, False]
        assert await limiter.allow(2) is True  # лимиты пользователей независимы


@pytest.mark.parametrize("kind,fresh", [(SourceKind.EXCHANGE, 45), (SourceKind.BANK, 900)])
def test_fresh_seconds_per_kind(kind, fresh):
    assert QuoteStore(crypto_fresh_seconds=45, bank_fresh_seconds=900).fresh_seconds(kind) == fresh
