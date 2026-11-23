"""Контекст приложения, доступный всем обработчикам бота."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.alerts import AlertEngine
from app.cache import QuoteStore
from app.config import Settings
from app.core import Core
from app.database import Database
from app.domain import utcnow
from app.services.assets import AssetRegistry
from app.services.chart_service import ChartService
from app.services.health import HealthRegistry
from app.services.p2p import P2PService
from app.services.quotes import QuoteService
from app.services.runtime_settings import RuntimeSettings
from app.services.users import UserService


@dataclass
class AppContext:
    core: Core
    quotes: QuoteService
    users: UserService
    charts: ChartService
    p2p: P2PService
    alerts: AlertEngine | None = None
    started_at: object = field(default_factory=utcnow)

    @property
    def settings(self) -> Settings:
        return self.core.settings

    @property
    def db(self) -> Database:
        return self.core.db

    @property
    def store(self) -> QuoteStore:
        return self.core.store

    @property
    def health(self) -> HealthRegistry:
        return self.core.health

    @property
    def assets(self) -> AssetRegistry:
        return self.core.assets

    @property
    def runtime(self) -> RuntimeSettings:
        return self.core.runtime

    def invalidate_alerts(self) -> None:
        if self.alerts is not None:
            self.alerts.invalidate()
