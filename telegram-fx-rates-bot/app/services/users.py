"""Пользователи и их настройки (с коротким кешем, чтобы не ходить в БД на каждое нажатие кнопки)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.database import Database
from app.database.repositories import UserRepo
from app.domain import utcnow
from app.i18n import normalize_lang
from app.services.assets import AssetRegistry

log = logging.getLogger(__name__)

_TTL = 30.0
DEFAULT_WATCH_CRYPTO = 7
DEFAULT_WATCH_FIAT = 2


@dataclass(frozen=True, slots=True)
class UserCtx:
    user_id: int
    telegram_id: int
    first_name: str
    lang: str
    display_currency: str
    notify_interval_min: int
    muted_until: datetime | None
    arb_min_net_pct: Decimal
    chart_period: str
    chart_theme: str
    watchlist: tuple[str, ...]
    is_admin: bool
    is_blocked: bool
    is_new: bool = False

    @property
    def muted(self) -> bool:
        return self.muted_until is not None and self.muted_until > utcnow()


class UserService:
    def __init__(self, db: Database, settings: Settings, assets: AssetRegistry) -> None:
        self._db = db
        self._settings = settings
        self._assets = assets
        self._cache: dict[int, tuple[float, UserCtx]] = {}
        self.on_settings_changed: Callable[[], None] | None = None

    def default_watchlist(self) -> list[str]:
        crypto = [s for s in self._settings.default_crypto_pairs if s in self._assets.crypto][:DEFAULT_WATCH_CRYPTO]
        fiat = [s for s in self._settings.default_fiat_pairs if s in self._assets.fiat][:DEFAULT_WATCH_FIAT]
        return [*crypto, *fiat]

    async def ensure(
        self, telegram_id: int, username: str | None, first_name: str | None, language_code: str | None
    ) -> UserCtx:
        cached = self._cache.get(telegram_id)
        if cached and time.monotonic() - cached[0] < _TTL:
            return cached[1]
        lang = normalize_lang(language_code, self._settings.default_language)
        async with self._db.session() as session:
            user, settings, created = await UserRepo(session).get_or_create(
                telegram_id, username, first_name, lang, self.default_watchlist()
            )
        ctx = UserCtx(
            user_id=user.id,
            telegram_id=telegram_id,
            first_name=first_name or username or "friend",
            lang=settings.language,
            display_currency=settings.display_currency,
            notify_interval_min=settings.notify_interval_min,
            muted_until=settings.alerts_muted_until,
            arb_min_net_pct=settings.arb_min_net_pct,
            chart_period=settings.chart_period,
            chart_theme=settings.chart_theme,
            watchlist=tuple(settings.watchlist or []),
            is_admin=telegram_id in self._settings.admin_ids,
            is_blocked=user.is_blocked,
            is_new=created,
        )
        self._cache[telegram_id] = (time.monotonic(), replace(ctx, is_new=False))
        return ctx

    def active_watchlist(self, ctx: UserCtx) -> list[str]:
        """Список пользователя без пар, отключённых в каталоге администратором."""
        known = set(self._assets.all)
        return [s for s in ctx.watchlist if s in known]

    async def update(self, telegram_id: int, **fields: Any) -> None:
        cached = self._cache.get(telegram_id)
        if cached is None:
            raise LookupError("пользователь не загружен")
        user_id = cached[1].user_id
        async with self._db.session() as session:
            await UserRepo(session).update_settings(user_id, **fields)
        self._cache.pop(telegram_id, None)
        if self.on_settings_changed is not None:
            self.on_settings_changed()

    def forget(self, telegram_id: int) -> None:
        self._cache.pop(telegram_id, None)

    async def exists(self, telegram_id: int) -> bool:
        if telegram_id in self._cache:
            return True
        async with self._db.session() as session:
            return await UserRepo(session).get_by_telegram_id(telegram_id) is not None
