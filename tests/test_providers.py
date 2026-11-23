"""Разбор реальных ответов API (фикстуры сняты с живых эндпоинтов)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain import Freshness, SourceKind
from app.providers.binance import parse_binance_ticker
from app.providers.bingx import parse_bingx_ticker
from app.providers.bitget import parse_bitget_ticker
from app.providers.bybit import parse_bybit_ticker
from app.providers.kucoin import parse_kucoin_level1
from app.providers.monobank import parse_monobank
from app.providers.okx import parse_okx_ticker
from app.providers.privatbank import parse_privatbank
from app.utils.http import ProviderError
from tests.conftest import load_json

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class TestMonobank:
    def test_usd_uah_has_buy_sell_and_source_time(self):
        quotes = {q.symbol: q for q in parse_monobank(load_json("mono_currency.json"), NOW)}
        usd = quotes["USD/UAH"]
        assert usd.kind is SourceKind.BANK
        assert usd.bid is not None and usd.ask is not None and usd.bid < usd.ask
        assert usd.last is None  # у банка нет «последней сделки»
        assert usd.source_ts is not None
        assert "EUR/UAH" in quotes and "EUR/USD" in quotes

    def test_cross_only_pair_has_no_fake_buy_sell(self):
        quotes = {q.symbol: q for q in parse_monobank(load_json("mono_currency.json"), NOW)}
        gbp = quotes["GBP/UAH"]
        assert gbp.bid is None and gbp.ask is None
        assert gbp.cross_rate is not None
        assert "bid" in gbp.missing_fields() and "ask" in gbp.missing_fields()

    def test_rate_limit_error_payload_raises(self):
        with pytest.raises(ProviderError, match="Too many requests"):
            parse_monobank({"errText": "Too many requests"})

    def test_unknown_currency_codes_skipped(self):
        payload = [{"currencyCodeA": 999999, "currencyCodeB": 980, "date": 1, "rateBuy": 1, "rateSell": 2}]
        assert parse_monobank(payload) == []


class TestPrivatBank:
    def test_buy_sell_parsed_and_time_reported_missing(self):
        quotes = {q.symbol: q for q in parse_privatbank(load_json("privat_pubinfo.json"), NOW)}
        usd = quotes["USD/UAH"]
        assert usd.bid is not None and usd.ask is not None
        assert usd.source_ts is None
        assert usd.missing_fields() == ["source_ts"]  # честно сообщаем, чего API не даёт

    def test_bad_payload(self):
        with pytest.raises(ProviderError):
            parse_privatbank({"error": "x"})


class TestExchangeRest:
    def test_binance(self):
        q = parse_binance_ticker(load_json("binance_ticker.json"), "BTC/USDT", NOW)
        assert q is not None
        assert q.bid < q.ask and q.last is not None and q.volume_24h is not None
        assert q.bid_size is not None and q.source_ts is not None
        assert q.spread == q.ask - q.bid

    def test_binance_invalid_symbol_is_none(self):
        assert parse_binance_ticker(load_json("binance_invalid.json"), "NOPE/USDT", NOW) is None

    def test_binance_empty_book_gives_no_bid_ask(self):
        """Реальный ответ по TON/USDT: bid/ask = 0 → нет стакана, цены не выдумываются."""
        q = parse_binance_ticker(load_json("binance_ton_nobook.json"), "TON/USDT", NOW)
        assert q is not None
        assert q.bid is None and q.ask is None and q.mid is None and q.spread is None

    def test_bybit(self):
        q = parse_bybit_ticker(load_json("bybit_ticker.json"), "BTC/USDT", NOW)
        assert q is not None and q.bid < q.ask and q.ask_size is not None and q.volume_24h is not None

    def test_bybit_unsupported(self):
        assert parse_bybit_ticker(load_json("bybit_unsupported.json"), "TON/USDT", NOW) is None

    def test_okx(self):
        q = parse_okx_ticker(load_json("okx_ticker.json"), "BTC/USDT", NOW)
        assert q is not None and q.bid < q.ask and q.last is not None

    def test_okx_unsupported(self):
        assert parse_okx_ticker(load_json("okx_unsupported.json"), "TON/USDT", NOW) is None

    def test_bitget(self):
        q = parse_bitget_ticker(load_json("bitget_ticker.json"), "BTC/USDT", NOW)
        assert q is not None and q.bid < q.ask and q.volume_24h is not None

    def test_bitget_unsupported(self):
        assert parse_bitget_ticker(load_json("bitget_unsupported.json"), "TON/USDT", NOW) is None

    def test_kucoin_combines_level1_and_stats(self):
        q = parse_kucoin_level1(load_json("kucoin_level1.json"), "BTC/USDT", load_json("kucoin_stats.json"), NOW)
        assert q is not None and q.bid < q.ask and q.volume_24h is not None

    def test_kucoin_without_stats_still_has_prices(self):
        q = parse_kucoin_level1(load_json("kucoin_level1.json"), "BTC/USDT", None, NOW)
        assert q is not None and q.volume_24h is None and q.last is not None

    def test_kucoin_unsupported(self):
        assert parse_kucoin_level1(load_json("kucoin_unsupported.json"), "TON/USDT", None, NOW) is None

    def test_bingx(self):
        q = parse_bingx_ticker(load_json("bingx_ticker.json"), "BTC/USDT", NOW)
        assert q is not None and q.bid < q.ask and q.volume_24h is not None

    def test_bingx_unsupported(self):
        assert parse_bingx_ticker(load_json("bingx_unsupported.json"), "TON/USDT", NOW) is None

    def test_error_codes_raise(self):
        with pytest.raises(ProviderError):
            parse_bybit_ticker({"retCode": 10006, "retMsg": "rate limit"}, "BTC/USDT")
        with pytest.raises(ProviderError):
            parse_okx_ticker({"code": "50011", "msg": "Too many requests"}, "BTC/USDT")
        with pytest.raises(ProviderError):
            parse_bitget_ticker({"code": "429", "msg": "limit"}, "BTC/USDT")


class TestQuoteModel:
    def test_non_positive_prices_become_none(self):
        from tests.conftest import make_quote

        q = make_quote(bid="0", ask="-1", last="5")
        assert q.bid is None and q.ask is None and q.last == Decimal("5")

    def test_spread_and_pct(self):
        from tests.conftest import make_quote

        q = make_quote(bid="99", ask="101")
        assert q.spread == Decimal("2") and q.mid == Decimal("100") and q.spread_pct == Decimal("2")

    def test_freshness_levels(self):
        from datetime import timedelta

        from tests.conftest import make_quote

        now = datetime.now(UTC)
        assert make_quote(received_at=now - timedelta(seconds=10)).freshness(45, 4, now) is Freshness.FRESH
        assert make_quote(received_at=now - timedelta(seconds=100)).freshness(45, 4, now) is Freshness.STALE
        assert make_quote(received_at=now - timedelta(seconds=500)).freshness(45, 4, now) is Freshness.EXPIRED

    def test_volume_carry_over_never_copies_prices(self):
        from tests.conftest import make_quote

        old = make_quote(bid="10", ask="11", last="10.5", volume="500")
        new = make_quote(bid="20", ask="21", last="20.5", volume=None)
        merged = new.with_volume_from(old)
        assert merged.volume_24h == Decimal("500") and merged.bid == Decimal("20")
