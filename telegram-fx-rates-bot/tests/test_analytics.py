from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

from app.analytics import ArbitrageConfig, Metric, compare_banks, compare_exchanges, find_opportunities, scan
from app.analytics.arbitrage import evaluate_pair
from app.domain import Freshness, SourceKind
from tests.conftest import make_quote

NOW = datetime.now(UTC)


def fresh(_q):
    return Freshness.FRESH


def by_age(q):
    return q.freshness(45, 4)


CFG = ArbitrageConfig(
    taker_fee_pct={"a": D("0.1"), "b": D("0.1")},
    withdraw_fee_coin={"BTC": D("0.01")},
    slippage_pct=D("0.05"),
    trade_size_usdt=D("1000"),
)


class TestArbitrageMath:
    """Ожидаемые значения посчитаны вручную (см. комментарии), а не скопированы из кода."""

    def setup_method(self):
        self.buy = make_quote(source="a", bid="99", ask="100", ask_size="10")
        self.sell = make_quote(source="b", bid="102", ask="103", bid_size="10")

    def test_hand_computed_example(self):
        o = evaluate_pair("BTC/USDT", self.buy, self.sell, CFG)
        assert o is not None
        assert o.quantity == D("10")  # 1000 / 100, стакан вмещает 10
        assert not o.liquidity_limited and not o.liquidity_unknown
        assert o.gross_pct == D("2")  # 102/100 - 1
        assert o.gross_profit == D("20")  # 10 * (102 - 100)
        assert o.cost == D("1001.5")  # 1000 * (1 + 0.001 + 0.0005)
        assert o.trade_fees == D("2.02")  # 1000*0.001 + 1020*0.001
        assert o.slippage_cost == D("1.01")  # 1000*0.0005 + 1020*0.0005
        assert o.withdraw_fee_cost == D("1.02")  # 0.01 BTC * 102
        # без перевода: 10*102*(1-0.0015) - 1001.5 = 1018.47 - 1001.5
        assert o.net_profit_prefunded == D("16.97")
        # с переводом: (10-0.01)*102*0.9985 - 1001.5 = 1017.45153 - 1001.5
        assert o.net_profit == D("15.95153")
        assert o.net_profit < o.gross_profit  # после издержек прибыль всегда меньше «грязной»

    def test_liquidity_limits_quantity(self):
        thin = make_quote(source="a", bid="99", ask="100", ask_size="2")
        o = evaluate_pair("BTC/USDT", thin, self.sell, CFG)
        assert o.quantity == D("2") and o.liquidity_limited
        assert o.available_notional == D("200")

    def test_sell_side_liquidity_also_limits(self):
        thin = make_quote(source="b", bid="102", ask="103", bid_size="0.5")
        o = evaluate_pair("BTC/USDT", self.buy, thin, CFG)
        assert o.quantity == D("0.5") and o.liquidity_limited

    def test_unknown_liquidity_is_flagged(self):
        no_size = make_quote(source="a", bid="99", ask="100", ask_size=None)
        o = evaluate_pair("BTC/USDT", no_size, self.sell, CFG)
        assert o.liquidity_unknown and o.quantity == D("10")

    def test_small_spread_is_unprofitable_after_costs(self):
        buy = make_quote(source="a", bid="99", ask="100", ask_size="10")
        sell = make_quote(source="b", bid="100.1", ask="101", bid_size="10")  # разница 0.1% < комиссий 0.2% + проскальзывание
        o = evaluate_pair("BTC/USDT", buy, sell, CFG)
        assert o.gross_pct > 0 and o.net_profit < 0 and not o.is_profitable

    def test_withdrawal_larger_than_quantity_does_not_go_positive(self):
        cfg = ArbitrageConfig({"a": D("0.1"), "b": D("0.1")}, {"BTC": D("50")}, D("0"), D("1000"))
        o = evaluate_pair("BTC/USDT", self.buy, self.sell, cfg)
        assert o.net_profit < 0  # вывод дороже всей сделки — убыток равен затратам

    def test_same_exchange_and_missing_prices_are_skipped(self):
        assert evaluate_pair("BTC/USDT", self.buy, self.buy, CFG) is None
        assert evaluate_pair("BTC/USDT", make_quote(source="a", ask=None), self.sell, CFG) is None
        assert evaluate_pair("BTC/USDT", self.buy, make_quote(source="b", bid=None), CFG) is None

    def test_unknown_exchange_uses_default_fee(self):
        buy = make_quote(source="zzz", bid="99", ask="100", ask_size="10")
        o = evaluate_pair("BTC/USDT", buy, self.sell, CFG)
        assert o.trade_fees == D("2.02")  # default_fee_pct = 0.10


class TestFindOpportunities:
    def test_best_direction_first_and_stale_excluded(self):
        a = make_quote(source="a", bid="99", ask="100", bid_size="5", ask_size="5")
        b = make_quote(source="b", bid="104", ask="105", bid_size="5", ask_size="5")
        old = make_quote(source="c", bid="150", ask="151", received_at=NOW - timedelta(seconds=300))
        found = find_opportunities("BTC/USDT", [a, b, old], CFG, by_age)
        assert {(o.buy_source, o.sell_source) for o in found} == {("a", "b"), ("b", "a")}
        assert (found[0].buy_source, found[0].sell_source) == ("a", "b")  # купить дешёвую, продать дорогую
        assert found[0].net_pct > 0 > found[1].net_pct
        assert all("c" not in (o.buy_source, o.sell_source) for o in found)  # устаревшие не участвуют

    def test_single_source_has_no_opportunity(self):
        assert find_opportunities("BTC/USDT", [make_quote(source="a")], CFG, fresh) == []

    def test_scan_applies_min_net_threshold(self):
        quotes = {
            "BTC/USDT": [make_quote(source="a", bid="99", ask="100", ask_size="9"),
                         make_quote(source="b", bid="102", ask="103", bid_size="9")],
            "ETH/USDT": [make_quote(source="a", symbol="ETH/USDT", bid="99", ask="100", ask_size="9"),
                         make_quote(source="b", symbol="ETH/USDT", bid="100.05", ask="101", bid_size="9")],
        }
        everything = scan(quotes, lambda s: quotes[s], CFG, fresh, min_net_pct=None)
        assert [o.symbol for o in everything] == ["BTC/USDT", "ETH/USDT"]
        strong = scan(quotes, lambda s: quotes[s], CFG, fresh, min_net_pct=D("0.5"))
        assert [o.symbol for o in strong] == ["BTC/USDT"]


class TestCompareExchanges:
    def quotes(self):
        return [
            make_quote(source="okx", last="101", bid="100.9", ask="101.1"),
            make_quote(source="binance", last="100", bid="99.9", ask="100.1"),
            make_quote(source="bybit", last="103", bid="102.9", ask="103.1"),
        ]

    def test_sorted_ascending_with_min_max_and_diff(self):
        c = compare_exchanges("BTC/USDT", self.quotes(), Metric.LAST, fresh)
        assert [r.source for r in c.rows] == ["binance", "okx", "bybit"]
        assert c.lowest.source == "binance" and c.highest.source == "bybit"
        assert c.diff == D("3") and c.diff_pct == D("3")  # (103-100)/100

    def test_metric_switch_uses_bid_or_ask(self):
        c = compare_exchanges("BTC/USDT", self.quotes(), Metric.ASK, fresh)
        assert c.lowest.value == D("100.1") and c.highest.value == D("103.1")

    def test_stale_shown_but_excluded_from_extremes_and_expired_dropped(self):
        quotes = self.quotes() + [
            make_quote(source="kucoin", last="90", received_at=NOW - timedelta(seconds=100)),  # устарела
            make_quote(source="bingx", last="80", received_at=NOW - timedelta(seconds=900)),  # нет данных
        ]
        c = compare_exchanges("BTC/USDT", quotes, Metric.LAST, by_age)
        assert "kucoin" in [r.source for r in c.rows] and c.rows[0].freshness is Freshness.STALE
        assert c.lowest.source == "binance"  # 90 не считается минимумом
        assert [q.source for q in c.expired] == ["bingx"] and c.has_stale

    def test_source_without_metric_is_reported_separately(self):
        quotes = self.quotes() + [make_quote(source="ton", bid=None, ask=None, last="5")]
        c = compare_exchanges("BTC/USDT", quotes, Metric.BID, fresh)
        assert [q.source for q in c.without_metric] == ["ton"]

    def test_single_source_has_no_diff(self):
        c = compare_exchanges("BTC/USDT", self.quotes()[:1], Metric.LAST, fresh)
        assert c.diff is None and c.diff_pct is None

    def test_other_symbols_ignored(self):
        c = compare_exchanges("ETH/USDT", self.quotes(), Metric.LAST, fresh)
        assert c.rows == []


class TestCompareBanks:
    def bank(self, source, bid, ask, **kw):
        return make_quote(source=source, symbol="USD/UAH", bid=bid, ask=ask, last=None, kind=SourceKind.BANK, **kw)

    def test_best_buy_and_sell_are_picked_in_clients_favour(self):
        c = compare_banks("USD/UAH", [self.bank("monobank", "44.91", "45.40"), self.bank("privatbank", "44.75", "45.45")], fresh)
        assert c.best_for_selling.source == "monobank"  # продать дороже: 44.91 > 44.75
        assert c.best_for_buying.source == "monobank"  # купить дешевле: 45.40 < 45.45
        assert c.buy_diff == D("0.16") and c.sell_diff == D("0.05")

    def test_cross_only_has_no_buy_sell(self):
        cross = make_quote(source="monobank", symbol="GBP/UAH", bid=None, ask=None, last=None, kind=SourceKind.BANK)
        object.__setattr__(cross, "cross_rate", D("59.6")) if False else None
        c = compare_banks("GBP/UAH", [cross.model_copy(update={"cross_rate": D("59.6")})], fresh)
        assert c.quotes == [] and len(c.cross_only) == 1 and c.best_for_buying is None

    def test_stale_bank_not_used_for_recommendation(self):
        stale = self.bank("privatbank", "50", "40", received_at=NOW - timedelta(hours=2))
        ok = self.bank("monobank", "44.91", "45.40")
        c = compare_banks("USD/UAH", [ok, stale], lambda q: q.freshness(900, 4))
        assert c.best_for_selling.source == "monobank" and [q.source for q in c.expired] == ["privatbank"]
