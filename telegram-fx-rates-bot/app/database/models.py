"""SQLAlchemy 2.x модели."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# SQLite требует INTEGER PRIMARY KEY для автоинкремента; в PostgreSQL используется BIGINT.
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")
Price = Numeric(38, 12)


class UTCDateTime(TypeDecorator[datetime]):
    """Всегда хранит и возвращает datetime с часовым поясом UTC (SQLite теряет tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime запрещён: используйте datetime с tzinfo=UTC")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    language: Mapped[str] = mapped_column(String(2), default="ru", server_default="ru")
    display_currency: Mapped[str] = mapped_column(String(8), default="USDT", server_default="USDT")
    notify_interval_min: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    alerts_muted_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    arb_min_net_pct: Mapped[Decimal] = mapped_column(Numeric(10, 4), default=Decimal("0.3"), server_default="0.3")
    chart_period: Mapped[str] = mapped_column(String(4), default="24h", server_default="24h")
    chart_theme: Mapped[str] = mapped_column(String(8), default="dark", server_default="dark")
    watchlist: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class TrackedAsset(Base):
    """Каталог отслеживаемых пар (общий для всего бота; управляется администратором)."""

    __tablename__ = "tracked_assets"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), unique=True)
    kind: Mapped[str] = mapped_column(String(8))  # crypto | fiat
    base: Mapped[str] = mapped_column(String(12))
    quote: Mapped[str] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    added_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class ExchangeRate(Base):
    """Последний снимок котировки биржи (обновляется периодически, не на каждое сообщение)."""

    __tablename__ = "exchange_rates"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    bid: Mapped[Decimal | None] = mapped_column(Price)
    ask: Mapped[Decimal | None] = mapped_column(Price)
    last: Mapped[Decimal | None] = mapped_column(Price)
    bid_size: Mapped[Decimal | None] = mapped_column(Price)
    ask_size: Mapped[Decimal | None] = mapped_column(Price)
    volume_24h: Mapped[Decimal | None] = mapped_column(Price)
    quote_volume_24h: Mapped[Decimal | None] = mapped_column(Price)
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class BankRate(Base):
    """История курсов банков: запись создаётся только при изменении курса."""

    __tablename__ = "bank_rates"
    __table_args__ = (Index("ix_bank_rates_source_symbol_received", "source", "symbol", "received_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    buy: Mapped[Decimal | None] = mapped_column(Price)
    sell: Mapped[Decimal | None] = mapped_column(Price)
    cross_rate: Mapped[Decimal | None] = mapped_column(Price)
    source_ts: Mapped[datetime | None] = mapped_column(UTCDateTime)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PriceHistory(Base):
    """Агрегированная история цен: свечи 1m (хранятся недолго) и 1h (хранятся долго)."""

    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("source", "symbol", "resolution", "bucket_start", name="uq_price_history_bucket"),
        Index("ix_price_history_resolution_bucket", "resolution", "bucket_start"),
    )

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16))
    symbol: Mapped[str] = mapped_column(String(24))
    resolution: Mapped[str] = mapped_column(String(2))  # 1m | 1h
    bucket_start: Mapped[datetime] = mapped_column(UTCDateTime)
    price_kind: Mapped[str] = mapped_column(String(8))  # last | mid | cross
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    bid: Mapped[Decimal | None] = mapped_column(Price)
    ask: Mapped[Decimal | None] = mapped_column(Price)
    samples: Mapped[int] = mapped_column(Integer, default=1)


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (Index("ix_alerts_active", "is_active"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(24))
    symbol: Mapped[str] = mapped_column(String(24))
    source: Mapped[str | None] = mapped_column(String(16))
    threshold: Mapped[Decimal] = mapped_column(Price)
    window_minutes: Mapped[int | None] = mapped_column(Integer)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    armed: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    last_triggered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class AlertHistory(Base):
    __tablename__ = "alert_history"
    __table_args__ = (Index("ix_alert_history_user_triggered", "user_id", "triggered_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alerts.id", ondelete="SET NULL"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    alert_type: Mapped[str] = mapped_column(String(24))
    symbol: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    value: Mapped[Decimal | None] = mapped_column(Price)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    triggered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now)


class ExchangeStatus(Base):
    __tablename__ = "exchange_status"

    source: Mapped[str] = mapped_column(String(16), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    ws_connected: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_errors: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)


class SourceError(Base):
    """Журнал ошибок источников для команды /errors."""

    __tablename__ = "source_errors"
    __table_args__ = (Index("ix_source_errors_source_created", "source", "created_at"),)

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, index=True)


class AppSetting(Base):
    """Глобальные настройки, изменяемые администратором во время работы."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=_now, onupdate=_now)
