"""Работа с БД. Все запросы параметризованы через SQLAlchemy Core/ORM (защита от SQL-инъекций)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    Alert,
    AlertHistory,
    AppSetting,
    BankRate,
    ExchangeRate,
    ExchangeStatus,
    PriceHistory,
    SourceError,
    TrackedAsset,
    User,
    UserSettings,
)
from app.database.session import insert_for
from app.domain import Quote, utcnow
from app.utils.symbols import asset_kind, split_symbol

_CHUNK = 300


def _chunks(items: Sequence[Any], size: int = _CHUNK) -> Iterable[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ---------------------------------------------------------------- пользователи
class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def get_or_create(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str | None,
        language: str,
        watchlist: list[str],
    ) -> tuple[User, UserSettings, bool]:
        user = (await self.s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()
        created = False
        if user is None:
            user = User(telegram_id=telegram_id, username=username, first_name=first_name)
            self.s.add(user)
            await self.s.flush()
            created = True
        else:
            user.username = username
            user.first_name = first_name
            user.last_seen_at = utcnow()
        settings = await self.s.get(UserSettings, user.id)
        if settings is None:
            settings = UserSettings(user_id=user.id, language=language, watchlist=list(watchlist))
            self.s.add(settings)
            await self.s.flush()
        return user, settings, created

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        return (await self.s.execute(select(User).where(User.telegram_id == telegram_id))).scalar_one_or_none()

    async def update_settings(self, user_id: int, **fields: Any) -> UserSettings:
        settings = await self.s.get(UserSettings, user_id)
        if settings is None:
            raise LookupError(f"нет настроек пользователя {user_id}")
        for key, value in fields.items():
            setattr(settings, key, value)
        await self.s.flush()
        return settings

    async def count(self) -> int:
        return (await self.s.execute(select(func.count(User.id)))).scalar_one()

    async def count_active_since(self, since: datetime) -> int:
        return (await self.s.execute(select(func.count(User.id)).where(User.last_seen_at >= since))).scalar_one()

    async def recent(self, limit: int = 20) -> list[User]:
        return list((await self.s.execute(select(User).order_by(User.last_seen_at.desc()).limit(limit))).scalars())

    async def set_blocked(self, telegram_id: int, blocked: bool) -> bool:
        result = await self.s.execute(update(User).where(User.telegram_id == telegram_id).values(is_blocked=blocked))
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def telegram_ids(self) -> dict[int, int]:
        """{user.id: telegram_id}."""
        rows = await self.s.execute(select(User.id, User.telegram_id))
        return {uid: tid for uid, tid in rows.all()}


# ---------------------------------------------------------------- каталог пар
class AssetRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def list_all(self) -> list[TrackedAsset]:
        return list((await self.s.execute(select(TrackedAsset).order_by(TrackedAsset.id))).scalars())

    async def list_active(self) -> list[TrackedAsset]:
        stmt = select(TrackedAsset).where(TrackedAsset.is_active.is_(True)).order_by(TrackedAsset.id)
        return list((await self.s.execute(stmt)).scalars())

    async def get(self, symbol: str) -> TrackedAsset | None:
        return (await self.s.execute(select(TrackedAsset).where(TrackedAsset.symbol == symbol))).scalar_one_or_none()

    async def add(self, symbol: str, added_by: int | None = None) -> TrackedAsset:
        existing = await self.get(symbol)
        if existing is not None:
            existing.is_active = True
            await self.s.flush()
            return existing
        base, quote = split_symbol(symbol)
        asset = TrackedAsset(symbol=symbol, kind=asset_kind(symbol), base=base, quote=quote, added_by=added_by)
        self.s.add(asset)
        await self.s.flush()
        return asset

    async def set_active(self, symbol: str, active: bool) -> bool:
        asset = await self.get(symbol)
        if asset is None:
            return False
        asset.is_active = active
        await self.s.flush()
        return True

    async def seed(self, symbols: Iterable[str]) -> int:
        """Добавляет недостающие пары по умолчанию. Уже существующие (в т.ч. отключённые) не трогает."""
        known = {a.symbol for a in await self.list_all()}
        added = 0
        for symbol in symbols:
            if symbol not in known:
                base, quote = split_symbol(symbol)
                self.s.add(TrackedAsset(symbol=symbol, kind=asset_kind(symbol), base=base, quote=quote))
                added += 1
        await self.s.flush()
        return added


# ---------------------------------------------------------------- снимки курсов
class RatesRepo:
    def __init__(self, session: AsyncSession, dialect: str) -> None:
        self.s = session
        self.dialect = dialect

    async def upsert_exchange_rates(self, quotes: Sequence[Quote]) -> None:
        rows = [
            {
                "source": q.source,
                "symbol": q.symbol,
                "bid": q.bid,
                "ask": q.ask,
                "last": q.last,
                "bid_size": q.bid_size,
                "ask_size": q.ask_size,
                "volume_24h": q.volume_24h,
                "quote_volume_24h": q.quote_volume_24h,
                "source_ts": q.source_ts,
                "received_at": q.received_at,
                "updated_at": utcnow(),
            }
            for q in quotes
        ]
        ins = insert_for(self.dialect)
        for part in _chunks(rows, 100):
            stmt = ins(ExchangeRate).values(list(part))
            update_cols = {c: getattr(stmt.excluded, c) for c in part[0] if c not in ("source", "symbol")}
            await self.s.execute(stmt.on_conflict_do_update(index_elements=["source", "symbol"], set_=update_cols))

    async def last_bank_rates(self) -> dict[tuple[str, str], tuple[Decimal | None, Decimal | None, Decimal | None]]:
        """Последние сохранённые (buy, sell, cross) по каждой паре — для записи только изменений."""
        latest = (
            select(BankRate.source, BankRate.symbol, func.max(BankRate.id).label("mid"))
            .group_by(BankRate.source, BankRate.symbol)
            .subquery()
        )
        rows = await self.s.execute(
            select(BankRate.source, BankRate.symbol, BankRate.buy, BankRate.sell, BankRate.cross_rate).join(
                latest, BankRate.id == latest.c.mid
            )
        )
        return {(src, sym): (buy, sell, cross) for src, sym, buy, sell, cross in rows.all()}

    async def add_bank_rates(self, quotes: Sequence[Quote]) -> None:
        for q in quotes:
            self.s.add(
                BankRate(
                    source=q.source,
                    symbol=q.symbol,
                    buy=q.bid,
                    sell=q.ask,
                    cross_rate=q.cross_rate,
                    source_ts=q.source_ts,
                    received_at=q.received_at,
                )
            )
        await self.s.flush()

    async def cleanup_bank_rates(self, older_than: datetime) -> int:
        result = await self.s.execute(delete(BankRate).where(BankRate.received_at < older_than))
        return result.rowcount or 0  # type: ignore[attr-defined]

    async def bank_rate_changes(self, source: str, symbol: str, since: datetime, limit: int = 500) -> list[BankRate]:
        stmt = (
            select(BankRate)
            .where(BankRate.source == source, BankRate.symbol == symbol, BankRate.received_at >= since)
            .order_by(BankRate.received_at)
            .limit(limit)
        )
        return list((await self.s.execute(stmt)).scalars())


# ---------------------------------------------------------------- история цен
@dataclass(slots=True)
class Candle:
    source: str
    symbol: str
    resolution: str
    bucket_start: datetime
    price_kind: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    bid: Decimal | None
    ask: Decimal | None
    samples: int

    def as_row(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "symbol": self.symbol,
            "resolution": self.resolution,
            "bucket_start": self.bucket_start,
            "price_kind": self.price_kind,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "bid": self.bid,
            "ask": self.ask,
            "samples": self.samples,
        }


class HistoryRepo:
    def __init__(self, session: AsyncSession, dialect: str) -> None:
        self.s = session
        self.dialect = dialect

    def _greatest(self, a: Any, b: Any) -> Any:
        return func.greatest(a, b) if self.dialect == "postgresql" else func.max(a, b)

    def _least(self, a: Any, b: Any) -> Any:
        return func.least(a, b) if self.dialect == "postgresql" else func.min(a, b)

    async def upsert_candles(self, candles: Sequence[Candle]) -> None:
        """Вставляет свечи; при совпадении бакета объединяет их (high/low/close/samples)."""
        ins = insert_for(self.dialect)
        for part in _chunks(list(candles), 200):
            stmt = ins(PriceHistory).values([c.as_row() for c in part])
            excl = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["source", "symbol", "resolution", "bucket_start"],
                set_={
                    "high": self._greatest(PriceHistory.high, excl.high),
                    "low": self._least(PriceHistory.low, excl.low),
                    "close": excl.close,
                    "bid": excl.bid,
                    "ask": excl.ask,
                    "samples": PriceHistory.samples + excl.samples,
                },
            )
            await self.s.execute(stmt)

    async def series(
        self, source: str, symbol: str, resolution: str, since: datetime, until: datetime | None = None
    ) -> list[PriceHistory]:
        conditions = [
            PriceHistory.source == source,
            PriceHistory.symbol == symbol,
            PriceHistory.resolution == resolution,
            PriceHistory.bucket_start >= since,
        ]
        if until is not None:
            conditions.append(PriceHistory.bucket_start <= until)
        stmt = select(PriceHistory).where(and_(*conditions)).order_by(PriceHistory.bucket_start)
        return list((await self.s.execute(stmt)).scalars())

    async def price_at(self, source: str, symbol: str, moment: datetime, max_gap: timedelta) -> Decimal | None:
        """Закрытие последней свечи не позже ``moment`` (но не старше ``max_gap`` от него)."""
        for resolution in ("1m", "1h"):
            stmt = (
                select(PriceHistory.close)
                .where(
                    PriceHistory.source == source,
                    PriceHistory.symbol == symbol,
                    PriceHistory.resolution == resolution,
                    PriceHistory.bucket_start <= moment,
                    PriceHistory.bucket_start >= moment - max_gap,
                )
                .order_by(PriceHistory.bucket_start.desc())
                .limit(1)
            )
            value = (await self.s.execute(stmt)).scalar_one_or_none()
            if value is not None:
                return value
        return None

    async def sources_for(self, symbol: str) -> list[str]:
        rows = await self.s.execute(select(PriceHistory.source).where(PriceHistory.symbol == symbol).distinct())
        return sorted(r[0] for r in rows.all())

    async def cleanup(self, retention_1m: timedelta, retention_1h: timedelta) -> int:
        now = utcnow()
        r1 = await self.s.execute(
            delete(PriceHistory).where(PriceHistory.resolution == "1m", PriceHistory.bucket_start < now - retention_1m)
        )
        r2 = await self.s.execute(
            delete(PriceHistory).where(PriceHistory.resolution == "1h", PriceHistory.bucket_start < now - retention_1h)
        )
        return (r1.rowcount or 0) + (r2.rowcount or 0)  # type: ignore[attr-defined]


# ---------------------------------------------------------------- уведомления
@dataclass(slots=True)
class ActiveAlert:
    id: int
    user_id: int
    telegram_id: int
    type: str
    symbol: str
    source: str | None
    threshold: Decimal
    window_minutes: int | None
    cooldown_minutes: int
    armed: bool
    last_triggered_at: datetime | None
    language: str
    notify_interval_min: int
    muted_until: datetime | None


class AlertRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def create(self, **fields: Any) -> Alert:
        alert = Alert(**fields)
        self.s.add(alert)
        await self.s.flush()
        return alert

    async def list_for_user(self, user_id: int) -> list[Alert]:
        stmt = select(Alert).where(Alert.user_id == user_id).order_by(Alert.id)
        return list((await self.s.execute(stmt)).scalars())

    async def count_for_user(self, user_id: int) -> int:
        return (await self.s.execute(select(func.count(Alert.id)).where(Alert.user_id == user_id))).scalar_one()

    async def get_owned(self, user_id: int, alert_id: int) -> Alert | None:
        stmt = select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
        return (await self.s.execute(stmt)).scalar_one_or_none()

    async def delete(self, user_id: int, alert_id: int) -> bool:
        result = await self.s.execute(delete(Alert).where(Alert.id == alert_id, Alert.user_id == user_id))
        return (result.rowcount or 0) > 0  # type: ignore[attr-defined]

    async def toggle(self, user_id: int, alert_id: int) -> Alert | None:
        alert = await self.get_owned(user_id, alert_id)
        if alert is None:
            return None
        alert.is_active = not alert.is_active
        alert.armed = True
        await self.s.flush()
        return alert

    async def list_active(self) -> list[ActiveAlert]:
        stmt = (
            select(Alert, User.telegram_id, UserSettings)
            .join(User, User.id == Alert.user_id)
            .join(UserSettings, UserSettings.user_id == User.id)
            .where(Alert.is_active.is_(True), User.is_blocked.is_(False))
        )
        result = []
        for alert, telegram_id, settings in (await self.s.execute(stmt)).all():
            result.append(
                ActiveAlert(
                    id=alert.id,
                    user_id=alert.user_id,
                    telegram_id=telegram_id,
                    type=alert.type,
                    symbol=alert.symbol,
                    source=alert.source,
                    threshold=alert.threshold,
                    window_minutes=alert.window_minutes,
                    cooldown_minutes=alert.cooldown_minutes,
                    armed=alert.armed,
                    last_triggered_at=alert.last_triggered_at,
                    language=settings.language,
                    notify_interval_min=settings.notify_interval_min,
                    muted_until=settings.alerts_muted_until,
                )
            )
        return result

    async def set_state(self, alert_id: int, armed: bool, triggered_at: datetime | None = None) -> None:
        values: dict[str, Any] = {"armed": armed}
        if triggered_at is not None:
            values["last_triggered_at"] = triggered_at
        await self.s.execute(update(Alert).where(Alert.id == alert_id).values(**values))

    async def add_history(
        self, alert: ActiveAlert, message: str, value: Decimal | None, delivered: bool, at: datetime
    ) -> None:
        self.s.add(
            AlertHistory(
                alert_id=alert.id,
                user_id=alert.user_id,
                alert_type=alert.type,
                symbol=alert.symbol,
                message=message,
                value=value,
                delivered=delivered,
                triggered_at=at,
            )
        )
        await self.s.flush()

    async def history_for_user(self, user_id: int, limit: int = 10) -> list[AlertHistory]:
        stmt = (
            select(AlertHistory)
            .where(AlertHistory.user_id == user_id)
            .order_by(AlertHistory.triggered_at.desc())
            .limit(limit)
        )
        return list((await self.s.execute(stmt)).scalars())

    async def cleanup_history(self, older_than: datetime) -> int:
        result = await self.s.execute(delete(AlertHistory).where(AlertHistory.triggered_at < older_than))
        return result.rowcount or 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------- статус источников
class StatusRepo:
    def __init__(self, session: AsyncSession, dialect: str) -> None:
        self.s = session
        self.dialect = dialect

    async def load_all(self) -> dict[str, ExchangeStatus]:
        rows = (await self.s.execute(select(ExchangeStatus))).scalars()
        return {r.source: r for r in rows}

    async def upsert_many(self, rows: Sequence[dict[str, Any]]) -> None:
        if not rows:
            return
        ins = insert_for(self.dialect)
        stmt = ins(ExchangeStatus).values(list(rows))
        cols = {c: getattr(stmt.excluded, c) for c in rows[0] if c != "source"}
        await self.s.execute(stmt.on_conflict_do_update(index_elements=["source"], set_=cols))

    async def set_enabled(self, source: str, enabled: bool, kind: str) -> None:
        ins = insert_for(self.dialect)
        stmt = ins(ExchangeStatus).values(source=source, kind=kind, is_enabled=enabled, updated_at=utcnow())
        await self.s.execute(
            stmt.on_conflict_do_update(index_elements=["source"], set_={"is_enabled": enabled, "updated_at": utcnow()})
        )

    async def add_errors(self, errors: Sequence[tuple[str, str, datetime]]) -> None:
        for source, message, at in errors:
            self.s.add(SourceError(source=source, message=message[:1000], created_at=at))
        await self.s.flush()

    async def recent_errors(self, limit: int = 20, source: str | None = None) -> list[SourceError]:
        stmt = select(SourceError).order_by(SourceError.created_at.desc(), SourceError.id.desc()).limit(limit)
        if source:
            stmt = stmt.where(SourceError.source == source)
        return list((await self.s.execute(stmt)).scalars())

    async def count_errors_since(self, since: datetime) -> int:
        stmt = select(func.count(SourceError.id)).where(SourceError.created_at >= since)
        return (await self.s.execute(stmt)).scalar_one()

    async def cleanup_errors(self, older_than: datetime) -> int:
        result = await self.s.execute(delete(SourceError).where(SourceError.created_at < older_than))
        return result.rowcount or 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------- глобальные настройки
class AppSettingsRepo:
    def __init__(self, session: AsyncSession, dialect: str) -> None:
        self.s = session
        self.dialect = dialect

    async def all(self) -> dict[str, Any]:
        rows = (await self.s.execute(select(AppSetting))).scalars()
        return {r.key: r.value for r in rows}

    async def set(self, key: str, value: Any) -> None:
        ins = insert_for(self.dialect)
        stmt = ins(AppSetting).values(key=key, value=value, updated_at=utcnow())
        await self.s.execute(
            stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value, "updated_at": utcnow()})
        )


__all__ = [
    "ActiveAlert",
    "AlertRepo",
    "AppSettingsRepo",
    "AssetRepo",
    "Candle",
    "HistoryRepo",
    "RatesRepo",
    "StatusRepo",
    "UserRepo",
]
