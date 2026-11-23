"""Глобальные настройки, которые администратор меняет без перезапуска (таблица ``app_settings``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.config import Settings
from app.database import Database
from app.database.repositories import AppSettingsRepo

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    kind: str  # decimal | int | bool
    minimum: Decimal | None = None
    maximum: Decimal | None = None


SPECS: dict[str, SettingSpec] = {
    "arb_trade_size_usdt": SettingSpec("arb_trade_size_usdt", "decimal", Decimal("10"), Decimal("1000000")),
    "arb_slippage_pct": SettingSpec("arb_slippage_pct", "decimal", Decimal("0"), Decimal("5")),
    "signups_enabled": SettingSpec("signups_enabled", "bool"),
    "alerts_enabled": SettingSpec("alerts_enabled", "bool"),
    "p2p_enabled": SettingSpec("p2p_enabled", "bool"),
}


class RuntimeSettings:
    def __init__(self, settings: Settings) -> None:
        self._values: dict[str, Any] = {
            "arb_trade_size_usdt": settings.arbitrage_trade_size_usdt,
            "arb_slippage_pct": settings.arbitrage_slippage_pct,
            "signups_enabled": True,
            "alerts_enabled": True,
            "p2p_enabled": True,
        }

    def get(self, key: str) -> Any:
        return self._values[key]

    @property
    def snapshot(self) -> dict[str, Any]:
        return dict(self._values)

    async def load(self, db: Database) -> None:
        async with db.session() as session:
            stored = await AppSettingsRepo(session, db.dialect).all()
        for key, raw in stored.items():
            if key in SPECS:
                try:
                    self._values[key] = self.parse(key, raw)
                except ValueError:
                    log.warning("игнорирую некорректную настройку %s=%r", key, raw)

    async def set(self, db: Database, key: str, raw: Any) -> Any:
        value = self.parse(key, raw)
        async with db.session() as session:
            stored = str(value) if isinstance(value, Decimal) else value
            await AppSettingsRepo(session, db.dialect).set(key, stored)
        self._values[key] = value
        return value

    @staticmethod
    def parse(key: str, raw: Any) -> Any:
        spec = SPECS.get(key)
        if spec is None:
            raise ValueError(f"неизвестная настройка: {key}")
        if spec.kind == "bool":
            if isinstance(raw, bool):
                return raw
            text = str(raw).strip().lower()
            if text in ("1", "true", "yes", "on", "да", "вкл"):
                return True
            if text in ("0", "false", "no", "off", "нет", "выкл"):
                return False
            raise ValueError("ожидается on/off")
        try:
            number = Decimal(str(raw).replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError("ожидается число") from exc
        if not number.is_finite():
            raise ValueError("ожидается конечное число")
        if spec.minimum is not None and number < spec.minimum:
            raise ValueError(f"минимум {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            raise ValueError(f"максимум {spec.maximum}")
        return int(number) if spec.kind == "int" else number
