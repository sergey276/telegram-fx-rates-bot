"""Прикладной слой над хранилищем котировок: то, что нужно боту и системе уведомлений."""

from __future__ import annotations

from decimal import Decimal

from app.analytics import (
    ArbitrageConfig,
    BankComparison,
    Comparison,
    Metric,
    compare_banks,
    compare_exchanges,
)
from app.analytics import arbitrage as arb
from app.cache import QuoteStore
from app.config import Settings
from app.domain import EXCHANGE_ORDER, Freshness, Quote, SourceKind
from app.services.health import HealthRegistry
from app.services.runtime_settings import RuntimeSettings

FX_BANK_PRIORITY = ("monobank", "privatbank")


class QuoteService:
    def __init__(self, store: QuoteStore, health: HealthRegistry, runtime: RuntimeSettings, settings: Settings) -> None:
        self.store = store
        self.health = health
        self.runtime = runtime
        self.settings = settings

    # ----- выборки -----
    def exchange_quotes(self, symbol: str) -> list[Quote]:
        return [q for q in self.store.for_symbol(symbol) if q.kind is SourceKind.EXCHANGE]

    def bank_quotes(self, symbol: str) -> list[Quote]:
        return [q for q in self.store.for_symbol(symbol) if q.kind is SourceKind.BANK]

    def freshness(self, quote: Quote) -> Freshness:
        return self.store.freshness(quote)

    # ----- сравнение -----
    def compare_exchanges(self, symbol: str, metric: Metric = Metric.LAST) -> Comparison:
        return compare_exchanges(symbol, self.exchange_quotes(symbol), metric, self.freshness)

    def compare_banks(self, symbol: str) -> BankComparison:
        return compare_banks(symbol, self.bank_quotes(symbol), self.freshness)

    def unlisted_on(self, symbol: str) -> list[str]:
        """Биржи, которые явно сообщили, что пары нет."""
        return [h.source for h in self.health.all() if h.enabled and symbol in h.unlisted]

    # ----- арбитраж -----
    def arbitrage_config(self) -> ArbitrageConfig:
        return ArbitrageConfig(
            taker_fee_pct=self.settings.taker_fees_pct,
            withdraw_fee_coin=self.settings.withdraw_fees,
            slippage_pct=Decimal(self.runtime.get("arb_slippage_pct")),
            trade_size_usdt=Decimal(self.runtime.get("arb_trade_size_usdt")),
        )

    def opportunities(self, symbols: list[str], min_net_pct: Decimal | None) -> list[arb.Opportunity]:
        return arb.scan(symbols, self.exchange_quotes, self.arbitrage_config(), self.freshness, min_net_pct)

    def best_opportunity(self, symbol: str) -> arb.Opportunity | None:
        return arb.best_opportunity(symbol, self.exchange_quotes(symbol), self.arbitrage_config(), self.freshness)

    # ----- пересчёт валюты отображения -----
    def fx_factor(self, currency: str) -> tuple[Decimal, str] | None:
        """Множитель USDT -> currency и название банка-источника курса. USDT принимается за USD."""
        if currency == "USDT":
            return Decimal(1), ""
        for bank in FX_BANK_PRIORITY:
            usd = self.store.get(bank, "USD/UAH")
            if usd is None or usd.mid is None or self.freshness(usd) is not Freshness.FRESH:
                continue
            if currency == "UAH":
                return usd.mid, bank
            eur = self.store.get(bank, "EUR/UAH")
            if currency == "EUR" and eur is not None and eur.mid is not None and self.freshness(eur) is Freshness.FRESH:
                return usd.mid / eur.mid, bank
        return None

    def sort_exchanges(self, quotes: list[Quote]) -> list[Quote]:
        order = {name: i for i, name in enumerate(EXCHANGE_ORDER)}
        return sorted(quotes, key=lambda q: order.get(q.source, 99))
