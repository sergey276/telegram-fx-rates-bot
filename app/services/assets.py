"""Каталог отслеживаемых пар (в памяти + таблица ``tracked_assets``)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from app.config import Settings
from app.database import Database
from app.database.repositories import AssetRepo
from app.utils.symbols import asset_kind

log = logging.getLogger(__name__)


class AssetRegistry:
    def __init__(self) -> None:
        self._crypto: list[str] = []
        self._fiat: list[str] = []
        self._listeners: list[Callable[[], None]] = []

    @property
    def crypto(self) -> list[str]:
        return list(self._crypto)

    @property
    def fiat(self) -> list[str]:
        return list(self._fiat)

    @property
    def all(self) -> list[str]:
        return [*self._crypto, *self._fiat]

    def is_tracked(self, symbol: str) -> bool:
        return symbol in self._crypto or symbol in self._fiat

    def on_changed(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def _set(self, crypto: list[str], fiat: list[str]) -> None:
        changed = crypto != self._crypto or fiat != self._fiat
        self._crypto, self._fiat = crypto, fiat
        if changed:
            for callback in self._listeners:
                callback()

    async def load(self, db: Database, settings: Settings | None = None) -> None:
        """Загружает каталог; при первом запуске заполняет его парами по умолчанию."""
        async with db.session() as session:
            repo = AssetRepo(session)
            if settings is not None:
                added = await repo.seed([*settings.default_crypto_pairs, *settings.default_fiat_pairs])
                if added:
                    log.info("В каталог добавлено пар по умолчанию: %d", added)
            active = await repo.list_active()
        self._set(
            [a.symbol for a in active if a.kind == "crypto"],
            [a.symbol for a in active if a.kind == "fiat"],
        )

    async def add(self, db: Database, symbol: str, added_by: int | None) -> None:
        async with db.session() as session:
            await AssetRepo(session).add(symbol, added_by)
        await self.load(db)

    async def remove(self, db: Database, symbol: str) -> bool:
        async with db.session() as session:
            ok = await AssetRepo(session).set_active(symbol, False)
        await self.load(db)
        return ok

    @staticmethod
    def kind_of(symbol: str) -> str:
        return asset_kind(symbol)
