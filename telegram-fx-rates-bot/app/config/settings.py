"""Настройки приложения. Все значения читаются из переменных окружения / файла .env."""

from __future__ import annotations

import json
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_CRYPTO_PAIRS = (
    "BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,BNB/USDT,DOGE/USDT,TON/USDT,"
    "ADA/USDT,TRX/USDT,LTC/USDT,AVAX/USDT,LINK/USDT"
)
DEFAULT_FIAT_PAIRS = "USD/UAH,EUR/UAH,EUR/USD,GBP/UAH,PLN/UAH,CHF/UAH,CZK/UAH"

ALL_SOURCES = ("monobank", "privatbank", "binance", "bybit", "okx", "bitget", "bingx", "kucoin")

# Оценочные комиссии. Живые комиссии нельзя получить публичным API без авторизации,
# поэтому значения настраиваются (EXCHANGE_FEES_JSON / WITHDRAW_FEES_JSON).
DEFAULT_TAKER_FEES_PCT: dict[str, Decimal] = {
    "binance": Decimal("0.10"),
    "bybit": Decimal("0.10"),
    "okx": Decimal("0.10"),
    "bitget": Decimal("0.10"),
    "bingx": Decimal("0.10"),
    "kucoin": Decimal("0.10"),
}
# Комиссия за вывод в единицах монеты (сеть выбирается пользователем самостоятельно, это грубая оценка).
DEFAULT_WITHDRAW_FEES: dict[str, Decimal] = {
    "BTC": Decimal("0.0002"),
    "ETH": Decimal("0.002"),
    "SOL": Decimal("0.01"),
    "XRP": Decimal("0.25"),
    "BNB": Decimal("0.0005"),
    "DOGE": Decimal("5"),
    "TON": Decimal("0.05"),
    "ADA": Decimal("1"),
    "TRX": Decimal("1"),
    "LTC": Decimal("0.001"),
    "AVAX": Decimal("0.02"),
    "LINK": Decimal("0.3"),
    "USDT": Decimal("1"),
}


def _split_csv(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(v).strip() for v in value if str(v).strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Telegram ---
    bot_token: SecretStr = Field(default=SecretStr(""), description="Токен от @BotFather")
    admin_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    default_language: str = "ru"

    # --- Инфраструктура ---
    database_url: str = "postgresql+asyncpg://fxbot:fxbot@localhost:5432/fxbot"
    redis_url: str = ""
    log_level: str = "INFO"
    log_dir: str = "logs"
    timezone: str = "Europe/Kyiv"

    # --- Источники и пары ---
    enabled_sources: Annotated[list[str], NoDecode] = Field(default_factory=lambda: list(ALL_SOURCES))
    default_crypto_pairs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: _split_csv(DEFAULT_CRYPTO_PAIRS)
    )
    default_fiat_pairs: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: _split_csv(DEFAULT_FIAT_PAIRS)
    )

    # --- Базовые URL (можно переопределить, например при гео-блокировке) ---
    monobank_url: str = "https://api.monobank.ua"
    privatbank_url: str = "https://api.privatbank.ua"
    binance_rest_url: str = "https://api.binance.com"
    binance_ws_url: str = "wss://stream.binance.com:9443"
    bybit_rest_url: str = "https://api.bybit.com"
    bybit_ws_url: str = "wss://stream.bybit.com/v5/public/spot"
    okx_rest_url: str = "https://www.okx.com"
    okx_ws_url: str = "wss://ws.okx.com/ws/v5/public"
    bitget_rest_url: str = "https://api.bitget.com"
    bitget_ws_url: str = "wss://ws.bitget.com/v2/ws/public"
    bingx_rest_url: str = "https://open-api.bingx.com"
    bingx_ws_url: str = "wss://open-api-ws.bingx.com/market"
    kucoin_rest_url: str = "https://api.kucoin.com"

    # --- Банки ---
    monobank_poll_seconds: int = Field(default=300, ge=300, description="Не чаще раза в 5 минут (ограничение API)")
    privatbank_poll_seconds: int = Field(default=300, ge=60)
    privatbank_coursid: int = Field(default=5, description="5 — наличный курс, 11 — безналичный")

    # --- Сбор данных ---
    http_timeout_seconds: float = 15.0
    rest_sweep_seconds: int = Field(default=120, ge=30, description="Периодическая REST-проверка бирж")
    stale_watchdog_seconds: int = Field(default=15, ge=5)
    crypto_fresh_seconds: int = Field(default=45, ge=5, description="Котировка биржи свежая, если моложе")
    bank_fresh_seconds: int = Field(default=900, ge=60, description="Котировка банка свежая, если моложе")
    stale_factor: int = Field(default=4, ge=2, description="Во сколько раз можно превысить fresh до статуса EXPIRED")
    ws_enabled: bool = True

    # --- История ---
    history_flush_seconds: int = Field(default=30, ge=5)
    exchange_rates_snapshot_seconds: int = Field(default=60, ge=10)
    history_1m_retention_hours: int = 72
    history_1h_retention_days: int = 120
    bank_rates_retention_days: int = 365
    alert_history_retention_days: int = 90
    error_log_retention_days: int = 14

    # --- Пользователи ---
    user_rate_limit_count: int = Field(default=8, ge=1)
    user_rate_limit_window_seconds: int = Field(default=10, ge=1)
    max_alerts_per_user: int = Field(default=20, ge=1)

    # --- Арбитраж ---
    arbitrage_trade_size_usdt: Decimal = Decimal("1000")
    arbitrage_slippage_pct: Decimal = Decimal("0.05")
    arbitrage_default_min_net_pct: Decimal = Decimal("0.30")
    exchange_fees_json: str = ""
    withdraw_fees_json: str = ""

    # --- Уведомления ---
    alerts_check_seconds: int = Field(default=5, ge=1)

    @field_validator("admin_ids", mode="before")
    @classmethod
    def _parse_admin_ids(cls, value: Any) -> list[int]:
        if isinstance(value, int):
            return [value]
        result: list[int] = []
        for item in _split_csv(value):
            try:
                result.append(int(item))
            except ValueError as exc:
                raise ValueError(f"ADMIN_IDS: '{item}' не является числовым Telegram ID") from exc
        return result

    @field_validator("enabled_sources", mode="before")
    @classmethod
    def _parse_sources(cls, value: Any) -> list[str]:
        items = [s.lower() for s in _split_csv(value)]
        unknown = [s for s in items if s not in ALL_SOURCES]
        if unknown:
            raise ValueError(f"ENABLED_SOURCES: неизвестные источники {unknown}; допустимо {list(ALL_SOURCES)}")
        return items

    @field_validator("default_crypto_pairs", "default_fiat_pairs", mode="before")
    @classmethod
    def _parse_pairs(cls, value: Any) -> list[str]:
        return [p.upper() for p in _split_csv(value)]

    @field_validator("default_language")
    @classmethod
    def _check_language(cls, value: str) -> str:
        value = value.lower()
        if value not in ("ru", "uk", "en"):
            raise ValueError("DEFAULT_LANGUAGE должен быть ru, uk или en")
        return value

    @property
    def taker_fees_pct(self) -> dict[str, Decimal]:
        fees = dict(DEFAULT_TAKER_FEES_PCT)
        fees.update({k.lower(): v for k, v in _parse_decimal_map(self.exchange_fees_json, "EXCHANGE_FEES_JSON").items()})
        return fees

    @property
    def withdraw_fees(self) -> dict[str, Decimal]:
        fees = dict(DEFAULT_WITHDRAW_FEES)
        fees.update({k.upper(): v for k, v in _parse_decimal_map(self.withdraw_fees_json, "WITHDRAW_FEES_JSON").items()})
        return fees

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


def _parse_decimal_map(raw: str, name: str) -> dict[str, Decimal]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return {str(k): Decimal(str(v)) for k, v in data.items()}
    except (ValueError, AttributeError, ArithmeticError) as exc:
        raise ValueError(f"{name}: ожидается JSON-объект вида {{\"имя\": число}}") from exc


@lru_cache
def get_settings() -> Settings:
    return Settings()
