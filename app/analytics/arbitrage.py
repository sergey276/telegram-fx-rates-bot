"""Поиск потенциальных арбитражных возможностей между биржами.

Это ОЦЕНКА по лучшим ценам стакана (top of book), а не гарантированная прибыль. Расчёт для сделки «купить на A
по ask, перевести, продать на B по bid»:

    затраты  = qty · ask_A · (1 + fee_A + slippage)
    получено = (qty − комиссия_вывода_в_монете) · bid_B · (1 − fee_B − slippage)
    прибыль  = получено − затраты

Объём ограничен лучшей ценой стакана с обеих сторон и размером сделки (``trade_size_usdt``).
Реальный результат зависит от глубины стакана, скорости перевода, лимитов и статуса ввода/вывода на биржах.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.domain import Freshness, Quote
from app.utils.symbols import split_symbol

HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class ArbitrageConfig:
    taker_fee_pct: Mapping[str, Decimal]
    withdraw_fee_coin: Mapping[str, Decimal]
    slippage_pct: Decimal = Decimal("0.05")
    trade_size_usdt: Decimal = Decimal("1000")
    default_fee_pct: Decimal = Decimal("0.10")


@dataclass(frozen=True, slots=True)
class Opportunity:
    symbol: str
    buy_source: str
    sell_source: str
    buy_price: Decimal  # ask на бирже покупки
    sell_price: Decimal  # bid на бирже продажи
    quantity: Decimal  # в базовой монете
    cost: Decimal  # затраты в котируемой валюте, с комиссией и проскальзыванием
    gross_pct: Decimal  # разница котировок до любых издержек
    gross_profit: Decimal
    trade_fees: Decimal
    slippage_cost: Decimal
    withdraw_fee_cost: Decimal
    net_profit: Decimal  # после всех издержек, с переводом
    net_pct: Decimal
    net_profit_prefunded: Decimal  # без перевода (балансы заранее на обеих биржах)
    net_pct_prefunded: Decimal
    liquidity_limited: bool  # объём ограничен стаканом, а не размером сделки
    liquidity_unknown: bool  # биржа не сообщила объём лучшей цены
    available_notional: Decimal | None  # сколько доступно по лучшим ценам

    @property
    def is_profitable(self) -> bool:
        return self.net_profit > 0


def evaluate_pair(symbol: str, buy: Quote, sell: Quote, cfg: ArbitrageConfig) -> Opportunity | None:
    """Оценка одной пары бирж; ``None`` — если не хватает данных."""
    if buy.source == sell.source or buy.ask is None or sell.bid is None:
        return None
    ask, bid = buy.ask, sell.bid
    base, _quote = split_symbol(symbol)

    fee_buy = cfg.taker_fee_pct.get(buy.source, cfg.default_fee_pct) / HUNDRED
    fee_sell = cfg.taker_fee_pct.get(sell.source, cfg.default_fee_pct) / HUNDRED
    slip = cfg.slippage_pct / HUNDRED

    target_qty = cfg.trade_size_usdt / ask
    sizes = [s for s in (buy.ask_size, sell.bid_size) if s is not None]
    unknown = len(sizes) < 2
    available_qty = min(sizes) if sizes else None
    quantity = target_qty if available_qty is None else min(target_qty, available_qty)
    limited = available_qty is not None and available_qty < target_qty
    if quantity <= 0:
        return None

    cost = quantity * ask * (1 + fee_buy + slip)
    gross_profit = quantity * (bid - ask)
    trade_fees = quantity * ask * fee_buy + quantity * bid * fee_sell
    slippage_cost = quantity * ask * slip + quantity * bid * slip

    revenue_prefunded = quantity * bid * (1 - fee_sell - slip)
    net_prefunded = revenue_prefunded - cost

    withdraw_coin = cfg.withdraw_fee_coin.get(base, Decimal(0))
    arriving = quantity - withdraw_coin
    revenue = max(arriving, Decimal(0)) * bid * (1 - fee_sell - slip)
    net = revenue - cost
    withdraw_cost = withdraw_coin * bid

    return Opportunity(
        symbol=symbol,
        buy_source=buy.source,
        sell_source=sell.source,
        buy_price=ask,
        sell_price=bid,
        quantity=quantity,
        cost=cost,
        gross_pct=(bid / ask - 1) * HUNDRED,
        gross_profit=gross_profit,
        trade_fees=trade_fees,
        slippage_cost=slippage_cost,
        withdraw_fee_cost=withdraw_cost,
        net_profit=net,
        net_pct=net / cost * HUNDRED,
        net_profit_prefunded=net_prefunded,
        net_pct_prefunded=net_prefunded / cost * HUNDRED,
        liquidity_limited=limited,
        liquidity_unknown=unknown,
        available_notional=None if available_qty is None else available_qty * ask,
    )


def find_opportunities(
    symbol: str,
    quotes: Iterable[Quote],
    cfg: ArbitrageConfig,
    freshness: Callable[[Quote], Freshness],
) -> list[Opportunity]:
    """Все направления между свежими котировками одной пары, лучшие первыми."""
    usable = [
        q for q in quotes if q.symbol == symbol and freshness(q) is Freshness.FRESH and (q.ask or q.bid)
    ]
    result: list[Opportunity] = []
    for buy in usable:
        for sell in usable:
            opportunity = evaluate_pair(symbol, buy, sell, cfg)
            if opportunity is not None:
                result.append(opportunity)
    result.sort(key=lambda o: o.net_pct, reverse=True)
    return result


def best_opportunity(
    symbol: str, quotes: Iterable[Quote], cfg: ArbitrageConfig, freshness: Callable[[Quote], Freshness]
) -> Opportunity | None:
    found = find_opportunities(symbol, quotes, cfg, freshness)
    return found[0] if found else None


def scan(
    symbols: Iterable[str],
    quotes_by_symbol: Callable[[str], list[Quote]],
    cfg: ArbitrageConfig,
    freshness: Callable[[Quote], Freshness],
    min_net_pct: Decimal | None = None,
) -> list[Opportunity]:
    """Лучшая возможность по каждой паре; при ``min_net_pct`` — только не ниже порога (по чистой прибыли с переводом)."""
    found: list[Opportunity] = []
    for symbol in symbols:
        best = best_opportunity(symbol, quotes_by_symbol(symbol), cfg, freshness)
        if best is None:
            continue
        if min_net_pct is None or best.net_pct >= min_net_pct:
            found.append(best)
    found.sort(key=lambda o: o.net_pct, reverse=True)
    return found
