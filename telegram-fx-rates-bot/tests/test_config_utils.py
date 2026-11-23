from __future__ import annotations

import logging
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.services.runtime_settings import RuntimeSettings
from app.utils.logging import RedactFilter
from app.utils.symbols import InvalidSymbol, asset_kind, native_map, normalize_symbol, to_decimal, to_native


def settings(**env) -> Settings:
    return Settings(_env_file=None, **env)


class TestSettings:
    def test_defaults_cover_all_required_sources_and_pairs(self):
        s = settings()
        assert set(s.enabled_sources) == {"monobank", "privatbank", "binance", "bybit", "okx", "bitget", "bingx", "kucoin"}
        for pair in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "BNB/USDT", "DOGE/USDT", "TON/USDT"):
            assert pair in s.default_crypto_pairs
        assert "USD/UAH" in s.default_fiat_pairs and "EUR/UAH" in s.default_fiat_pairs

    def test_admin_ids_csv_and_single_int(self, monkeypatch):
        monkeypatch.setenv("ADMIN_IDS", "123, 456,789")
        assert Settings(_env_file=None).admin_ids == [123, 456, 789]
        monkeypatch.setenv("ADMIN_IDS", "42")
        assert Settings(_env_file=None).admin_ids == [42]
        monkeypatch.setenv("ADMIN_IDS", "")
        assert Settings(_env_file=None).admin_ids == []

    def test_admin_ids_garbage_is_rejected_with_clear_message(self, monkeypatch):
        monkeypatch.setenv("ADMIN_IDS", "12,abc")
        with pytest.raises(ValidationError, match="числовым Telegram ID"):
            Settings(_env_file=None)

    def test_unknown_source_rejected(self, monkeypatch):
        monkeypatch.setenv("ENABLED_SOURCES", "binance,coinbase")
        with pytest.raises(ValidationError, match="coinbase"):
            Settings(_env_file=None)

    def test_monobank_cannot_be_polled_more_often_than_every_5_minutes(self):
        with pytest.raises(ValidationError):
            settings(monobank_poll_seconds=60)
        assert settings(monobank_poll_seconds=600).monobank_poll_seconds == 600

    def test_fee_overrides_from_json(self):
        s = settings(exchange_fees_json='{"Binance": 0.075}', withdraw_fees_json='{"btc": 0.0005}')
        assert s.taker_fees_pct["binance"] == D("0.075") and s.taker_fees_pct["okx"] == D("0.10")
        assert s.withdraw_fees["BTC"] == D("0.0005") and s.withdraw_fees["ETH"] == D("0.002")

    def test_bad_fee_json_has_clear_error(self):
        with pytest.raises(ValueError, match="EXCHANGE_FEES_JSON"):
            _ = settings(exchange_fees_json="not json").taker_fees_pct

    def test_pairs_are_uppercased_and_language_validated(self, monkeypatch):
        monkeypatch.setenv("DEFAULT_CRYPTO_PAIRS", "btc/usdt, eth/usdt")
        assert Settings(_env_file=None).default_crypto_pairs == ["BTC/USDT", "ETH/USDT"]
        with pytest.raises(ValidationError):
            settings(default_language="fr")

    def test_token_is_secret_and_not_in_repr(self):
        s = settings(bot_token="123456:SECRETSECRETSECRETSECRETSECRETSECRET")
        assert "SECRET" not in repr(s) and "SECRET" not in str(s.bot_token)
        assert s.bot_token.get_secret_value().startswith("123456:")


class TestSymbols:
    @pytest.mark.parametrize("raw,expected", [
        ("btc/usdt", "BTC/USDT"), ("BTCUSDT", "BTC/USDT"), ("btc-usdt", "BTC/USDT"), (" eth_usdt ", "ETH/USDT"),
        ("usd/uah", "USD/UAH"), ("EURUAH", "EUR/UAH"), ("DOGEUSDT", "DOGE/USDT"),
    ])
    def test_normalize(self, raw, expected):
        assert normalize_symbol(raw) == expected

    @pytest.mark.parametrize("raw", ["", "BTC", "BTC/", "/USDT", "B/USDT", "BTC/USDT/X", "BTC USDT; DROP TABLE", "<script>", "💥/USDT"])
    def test_invalid(self, raw):
        with pytest.raises(InvalidSymbol):
            normalize_symbol(raw)

    def test_kind_and_native_formats(self):
        assert asset_kind("USD/UAH") == "fiat" and asset_kind("BTC/USDT") == "crypto"
        assert to_native("BTC/USDT") == "BTCUSDT" and to_native("BTC/USDT", "-") == "BTC-USDT"
        assert native_map(["BTC/USDT"], "-") == {"BTC-USDT": "BTC/USDT"}

    @pytest.mark.parametrize("raw,expected", [("1.5", D("1.5")), (2, D(2)), ("", None), (None, None), ("abc", None),
                                              ("NaN", None), ("Infinity", None), (True, None)])
    def test_to_decimal(self, raw, expected):
        assert to_decimal(raw) == expected


class TestRuntimeSettings:
    @pytest.mark.parametrize("key,raw,expected", [
        ("arb_trade_size_usdt", "2 500".replace(" ", ""), D("2500")), ("arb_slippage_pct", "0,1", D("0.1")),
        ("signups_enabled", "off", False), ("alerts_enabled", "да", True), ("signups_enabled", True, True),
    ])
    def test_parse_ok(self, key, raw, expected):
        assert RuntimeSettings.parse(key, raw) == expected

    @pytest.mark.parametrize("key,raw", [
        ("arb_trade_size_usdt", "5"), ("arb_trade_size_usdt", "9999999999"), ("arb_slippage_pct", "-1"),
        ("arb_slippage_pct", "NaN"), ("arb_slippage_pct", "abc"), ("signups_enabled", "maybe"), ("unknown_key", "1"),
    ])
    def test_parse_rejects(self, key, raw):
        with pytest.raises(ValueError):
            RuntimeSettings.parse(key, raw)


class TestLogging:
    def test_bot_token_is_redacted_from_log_records(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1,
                                   "POST https://api.telegram.org/bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw/getMe", None, None)
        assert RedactFilter().filter(record) is True
        assert "AAHdq" not in record.getMessage() and "<bot-token>" in record.getMessage()

    def test_token_in_args_is_redacted_too(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "url=%s", ("bot123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw",), None)
        RedactFilter().filter(record)
        assert "AAHdq" not in record.getMessage()

    def test_normal_messages_untouched(self):
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "курс %s = %s", ("BTC", 61000), None)
        RedactFilter().filter(record)
        assert record.getMessage() == "курс BTC = 61000"
