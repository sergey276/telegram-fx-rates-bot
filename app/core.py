"""Ядро сбора данных: всё, что работает без Telegram (БД, кеш, провайдеры, сборщики, история)."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from app.cache import QuoteStore, UserRateLimiter, create_redis
from app.collectors import BankCollector, ExchangeCollector
from app.config import Settings
from app.database import Database
from app.domain import SourceKind
from app.providers import BaseProvider, ExchangeProvider, build_providers
from app.services.assets import AssetRegistry
from app.services.health import HealthRegistry
from app.services.history import HistoryAggregator
from app.services.persistence import PersistenceService
from app.services.runtime_settings import RuntimeSettings
from app.utils.http import HttpClient

log = logging.getLogger(__name__)


class Core:
    def __init__(self, settings: Settings, db: Database | None = None, redis: Redis | None = None) -> None:
        self.settings = settings
        self.db = db or Database(settings.database_url)
        self.redis = redis
        self._owns_redis = redis is None
        self.http = HttpClient(settings.http_timeout_seconds)
        self.health = HealthRegistry()
        self.assets = AssetRegistry()
        self.runtime = RuntimeSettings(settings)
        self.providers: dict[str, BaseProvider] = build_providers(settings, self.http)
        self.store: QuoteStore
        self.rate_limiter: UserRateLimiter
        self.history: HistoryAggregator
        self.persistence: PersistenceService
        self.collectors: dict[str, ExchangeCollector | BankCollector] = {}

    async def start(self, run_collectors: bool = True) -> None:
        s = self.settings
        if self._owns_redis:
            self.redis = await create_redis(s.redis_url)
        self.store = QuoteStore(
            self.redis, s.crypto_fresh_seconds, s.bank_fresh_seconds, s.stale_factor
        )
        self.rate_limiter = UserRateLimiter(self.redis, s.user_rate_limit_count, s.user_rate_limit_window_seconds)

        await self.assets.load(self.db, s)
        await self.runtime.load(self.db)
        for provider in self.providers.values():
            self.health.register(provider.name, provider.kind, provider.supports_stream and s.ws_enabled)
        await self.health.load(self.db)
        self.store.set_disabled(self.health.disabled_sources())
        self.health.on_enabled_changed(lambda: self.store.set_disabled(self.health.disabled_sources()))

        await self.store.warm_from_redis()
        self.history = HistoryAggregator(self.db, self.assets, s.history_flush_seconds)
        self.persistence = PersistenceService(self.db, self.store, self.assets, self.health, s)
        await self.persistence.start()
        self.store.add_listener(self.history.on_quote)  # после warm-up: старые данные в историю не попадают
        self.history.start()
        self.store.start()

        if not run_collectors:  # тесты: данные подставляются вручную, без обращения к сети
            return
        polls = {"monobank": s.monobank_poll_seconds, "privatbank": s.privatbank_poll_seconds}
        for name, provider in self.providers.items():
            collector: ExchangeCollector | BankCollector
            if provider.kind is SourceKind.BANK:
                collector = BankCollector(
                    provider, self.store, self.health, self.assets, polls[name], self.persistence.save_bank_quotes
                )
            else:
                assert isinstance(provider, ExchangeProvider)
                collector = ExchangeCollector(provider, self.store, self.health, self.assets, s)
            self.collectors[name] = collector
            collector.start()

        self.assets.on_changed(self.poke_collectors)
        self.health.on_enabled_changed(self.poke_collectors)
        log.info(
            "Ядро запущено: источников %d, пар %d крипто / %d фиат",
            len(self.providers),
            len(self.assets.crypto),
            len(self.assets.fiat),
        )

    def poke_collectors(self) -> None:
        for collector in self.collectors.values():
            collector.poke()

    async def stop(self) -> None:
        for collector in self.collectors.values():
            await collector.stop()
        await self.history.stop()
        await self.persistence.stop()
        await self.store.stop()
        await self.http.close()
        if self.redis is not None and self._owns_redis:
            await self.redis.aclose()
        await self.db.dispose()
        log.info("Ядро остановлено")
