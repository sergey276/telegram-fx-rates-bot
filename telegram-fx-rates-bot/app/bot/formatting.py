"""Построение текстов сообщений (HTML) из котировок и результатов аналитики."""

from __future__ import annotations

from decimal import Decimal
from html import escape

from app.analytics import BankComparison, Comparison, Metric
from app.analytics.arbitrage import Opportunity
from app.bot.context import AppContext
from app.domain import Freshness, Quote, source_name, utcnow
from app.i18n import t
from app.services.users import UserCtx
from app.utils.fmt import format_age, format_pct, format_price, format_time, format_volume
from app.utils.symbols import split_symbol

ICON = {Freshness.FRESH: "🟢", Freshness.STALE: "🟡", Freshness.EXPIRED: "⛔"}


def h(value: object) -> str:
    return escape(str(value), quote=False)


class Money:
    """Форматирование цен в валюте отображения пользователя (USDT / UAH / EUR)."""

    def __init__(self, ctx: AppContext, currency: str, lang: str) -> None:
        self.currency = currency
        self.lang = lang
        self._fx = ctx.quotes.fx_factor(currency)
        self.available = self._fx is not None
        self._bank = self._fx[1] if self._fx else ""

    def fmt(self, price: Decimal | None) -> str:
        if price is None:
            return "—"
        if self._fx is None or self.currency == "USDT":
            return format_price(price)
        return format_price(price * self._fx[0])

    def note(self) -> str | None:
        if self.currency == "USDT":
            return None
        if self._fx is None:
            return t(self.lang, "note.fx_unavailable", cur=self.currency)
        return t(self.lang, "note.fx", cur=self.currency, bank=source_name(self._bank))

    @property
    def suffix(self) -> str:
        return self.currency if self.available else "USDT"


def warnings_for(ctx: AppContext, lang: str, quotes: list[Quote]) -> list[str]:
    """Предупреждения об устаревших и отсутствующих данных."""
    stale, expired = [], []
    for q in quotes:
        state = ctx.quotes.freshness(q)
        if state is Freshness.STALE:
            stale.append(f"{source_name(q.source)} ({format_age(q.age_seconds(), lang)})")
        elif state is Freshness.EXPIRED:
            expired.append(f"{source_name(q.source)} ({format_age(q.age_seconds(), lang)})")
    lines = []
    if stale:
        lines.append(t(lang, "warn.stale", items=h(", ".join(stale))))
    if expired:
        lines.append(t(lang, "warn.expired", items=h(", ".join(expired))))
    return lines


def unlisted_note(ctx: AppContext, lang: str, symbol: str) -> str | None:
    names = [source_name(s) for s in ctx.quotes.unlisted_on(symbol)]
    return t(lang, "note.unlisted", items=h(", ".join(names))) if names else None


def now_line(ctx: AppContext, lang: str) -> str:
    return t(lang, "note.updated", time=format_time(utcnow(), ctx.settings.timezone))


# --------------------------------------------------------------------------- курсы
def rates_text(ctx: AppContext, u: UserCtx) -> str:
    lang = u.lang
    watch = ctx.users.active_watchlist(u)
    fiat = [s for s in watch if s in ctx.assets.fiat]
    crypto = [s for s in watch if s in ctx.assets.crypto]
    if not watch:
        return t(lang, "rates.empty")
    money = Money(ctx, u.display_currency, lang)
    lines = [t(lang, "rates.title"), now_line(ctx, lang), ""]
    warnings: list[str] = []

    if fiat:
        lines.append(t(lang, "rates.banks"))
        for symbol in fiat:
            comparison = ctx.quotes.compare_banks(symbol)
            parts = []
            for q in comparison.quotes:
                state = ctx.quotes.freshness(q)
                parts.append(f"{source_name(q.source)} {ICON[state]} {format_price(q.bid)} / {format_price(q.ask)}")
            for q in comparison.cross_only:
                parts.append(f"{source_name(q.source)} ≈{format_price(q.cross_rate)}")
            if parts:
                lines.append(f"<b>{symbol}</b>: " + "  ·  ".join(parts))
            else:
                lines.append(t(lang, "rates.no_data_line", symbol=symbol))
            warnings += warnings_for(ctx, lang, ctx.quotes.bank_quotes(symbol))
        lines.append("")

    if crypto:
        lines.append(t(lang, "rates.crypto"))
        for symbol in crypto:
            exchange_cmp = ctx.quotes.compare_exchanges(symbol, Metric.LAST)
            fresh = exchange_cmp.fresh_rows
            if not fresh:
                lines.append(t(lang, "rates.no_data_line", symbol=symbol))
            else:
                low, high = fresh[0].value, fresh[-1].value
                value = money.fmt(low) if low == high else f"{money.fmt(low)} — {money.fmt(high)}"
                lines.append(
                    t(lang, "rates.crypto_line", symbol=symbol, value=value,
                      sources=t(lang, "rates.sources_n", n=len(fresh)))
                )
            warnings += warnings_for(ctx, lang, ctx.quotes.exchange_quotes(symbol))
        note = money.note()
        if note:
            lines += ["", note]
        lines.append("")

    unique = list(dict.fromkeys(warnings))
    return "\n".join(lines + unique).strip()


# --------------------------------------------------------------------------- криптовалюты
def crypto_detail_text(ctx: AppContext, u: UserCtx, symbol: str) -> str:
    lang = u.lang
    money = Money(ctx, u.display_currency, lang)
    quotes = ctx.quotes.sort_exchanges(ctx.quotes.exchange_quotes(symbol))
    lines = [t(lang, "crypto.title", symbol=symbol), now_line(ctx, lang), ""]
    if not quotes:
        lines.append(t(lang, "warn.no_data", symbol=symbol))
    for q in quotes:
        state = ctx.quotes.freshness(q)
        if state is Freshness.EXPIRED:
            continue
        spread = format_pct(q.spread_pct, 3) if q.spread_pct is not None else t(lang, "crypto.no_book")
        lines.append(
            t(lang, "crypto.row", source=source_name(q.source), icon=ICON[state], last=money.fmt(q.last),
              bid=money.fmt(q.bid), ask=money.fmt(q.ask), spread=spread, volume=format_volume(q.volume_24h),
              age=format_age(q.age_seconds(), lang))
        )
    if quotes and all(ctx.quotes.freshness(q) is Freshness.EXPIRED for q in quotes):
        lines.append(t(lang, "warn.no_data", symbol=symbol))
    lines += ["", *warnings_for(ctx, lang, quotes)]
    for extra in (unlisted_note(ctx, lang, symbol), money.note()):
        if extra:
            lines.append(extra)
    lines += ["", f"<i>{t(lang, 'crypto.legend')}</i>"]
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- банки
def bank_pair_block(ctx: AppContext, lang: str, symbol: str) -> list[str]:
    comparison = ctx.quotes.compare_banks(symbol)
    lines = [f"<b>{symbol}</b>"]
    seen = set()
    for q in comparison.quotes:
        seen.add(q.source)
        spread = format_price(q.spread) if q.spread is not None else "—"
        lines.append(
            f"{ICON[ctx.quotes.freshness(q)]} "
            + t(lang, "banks.rate_line", bank=source_name(q.source), buy=format_price(q.bid),
                sell=format_price(q.ask), spread=spread)
        )
        quote_time = (
            format_time(q.source_ts, ctx.settings.timezone, with_date=True)
            if q.source_ts else t(lang, "banks.no_quote_time")
        )
        lines.append(t(lang, "banks.time_line", quote_time=quote_time, age=format_age(q.age_seconds(), lang)))
    for q in comparison.cross_only:
        seen.add(q.source)
        lines.append(t(lang, "banks.cross_line", bank=source_name(q.source), cross=format_price(q.cross_rate)))
    for q in comparison.expired:
        seen.add(q.source)
    for provider in ctx.core.providers.values():
        if provider.kind.value == "bank" and provider.name not in seen and ctx.health.is_enabled(provider.name):
            lines.append(t(lang, "banks.missing_line", bank=source_name(provider.name)))
    for q in comparison.expired:
        lines.append(t(lang, "warn.expired", items=f"{source_name(q.source)} ({format_age(q.age_seconds(), lang)})"))
    best_sell, best_buy = comparison.best_for_selling, comparison.best_for_buying
    if best_sell and len(comparison.quotes) > 1:
        lines.append(t(lang, "banks.best_sell", bank=source_name(best_sell.source), rate=format_price(best_sell.bid)))
    if best_buy and len(comparison.quotes) > 1:
        lines.append(t(lang, "banks.best_buy", bank=source_name(best_buy.source), rate=format_price(best_buy.ask)))
    return lines


def banks_text(ctx: AppContext, u: UserCtx, symbols: list[str]) -> str:
    lang = u.lang
    if not symbols:
        return t(lang, "banks.empty")
    lines = [t(lang, "banks.title"), now_line(ctx, lang), ""]
    for symbol in symbols:
        lines += bank_pair_block(ctx, lang, symbol) + [""]
    for symbol in symbols:
        warn = [w for w in warnings_for(ctx, lang, ctx.quotes.bank_quotes(symbol)) if "⚠️" in w]
        lines += warn
    lines.append(f"<i>{t(lang, 'banks.legend')}</i>")
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- сравнение
def compare_exchanges_text(ctx: AppContext, u: UserCtx, symbol: str, metric: Metric) -> str:
    lang = u.lang
    money = Money(ctx, u.display_currency, lang)
    cmp: Comparison = ctx.quotes.compare_exchanges(symbol, metric)
    lines = [t(lang, "compare.title", symbol=symbol, metric=t(lang, f"metric.{metric.value}")), now_line(ctx, lang), ""]
    for i, row in enumerate(cmp.rows, 1):
        lines.append(
            t(lang, "compare.row", n=i, source=source_name(row.source), icon=ICON[row.freshness],
              value=money.fmt(row.value), age=format_age(row.quote.age_seconds(), lang))
        )
    if not cmp.rows:
        lines.append(t(lang, "warn.no_data", symbol=symbol))
    elif cmp.lowest and cmp.highest and cmp.diff is not None:
        lines += [
            "",
            t(lang, "compare.lowest", source=source_name(cmp.lowest.source), value=money.fmt(cmp.lowest.value)),
            t(lang, "compare.highest", source=source_name(cmp.highest.source), value=money.fmt(cmp.highest.value)),
            t(lang, "compare.diff", abs=money.fmt(cmp.diff), pct=format_pct(cmp.diff_pct, 3)),
        ]
    else:
        lines += ["", t(lang, "compare.need_two")]
    if cmp.expired:
        lines.append(t(lang, "warn.expired", items=h(", ".join(source_name(q.source) for q in cmp.expired))))
    if any(r.freshness is Freshness.STALE for r in cmp.rows):
        stale = [f"{source_name(r.source)}" for r in cmp.rows if r.freshness is Freshness.STALE]
        lines.append(t(lang, "warn.stale", items=h(", ".join(stale))))
    if cmp.without_metric:
        lines.append(t(lang, "compare.without_metric", items=h(", ".join(source_name(q.source) for q in cmp.without_metric))))
    for extra in (unlisted_note(ctx, lang, symbol), money.note()):
        if extra:
            lines.append(extra)
    return "\n".join(lines).strip()


def compare_banks_text(ctx: AppContext, u: UserCtx, symbol: str) -> str:
    lang = u.lang
    cmp: BankComparison = ctx.quotes.compare_banks(symbol)
    lines = [t(lang, "compare.bank_title", symbol=symbol), now_line(ctx, lang), ""]
    if not cmp.quotes and not cmp.cross_only:
        lines.append(t(lang, "warn.no_data", symbol=symbol))
    else:
        by_sell = sorted((q for q in cmp.quotes if q.bid is not None), key=lambda q: q.bid, reverse=True)  # type: ignore[arg-type,return-value]
        by_buy = sorted((q for q in cmp.quotes if q.ask is not None), key=lambda q: q.ask)  # type: ignore[arg-type,return-value]
        lines.append(t(lang, "compare.bank_sell_hdr"))
        for i, q in enumerate(by_sell, 1):
            lines.append(f"{i}. <b>{source_name(q.source)}</b> {ICON[cmp.freshness[q.source]]} {format_price(q.bid)}")
        if cmp.buy_diff is not None:
            lines.append(f"↔️ {format_price(cmp.buy_diff)}")
        lines += ["", t(lang, "compare.bank_buy_hdr")]
        for i, q in enumerate(by_buy, 1):
            lines.append(f"{i}. <b>{source_name(q.source)}</b> {ICON[cmp.freshness[q.source]]} {format_price(q.ask)}")
        if cmp.sell_diff is not None:
            lines.append(f"↔️ {format_price(cmp.sell_diff)}")
        for q in cmp.cross_only:
            lines.append(t(lang, "banks.cross_line", bank=source_name(q.source), cross=format_price(q.cross_rate)))
    for q in cmp.expired:
        lines.append(t(lang, "warn.expired", items=f"{source_name(q.source)} ({format_age(q.age_seconds(), lang)})"))
    lines += ["", f"<i>{t(lang, 'banks.legend')}</i>"]
    return "\n".join(lines).strip()


# --------------------------------------------------------------------------- арбитраж
def _item(lang: str, o: Opportunity) -> str:
    volume = t(lang, "arb.liq_unknown") if o.liquidity_unknown else f"{format_price(o.available_notional)} USDT"
    return t(
        lang, "arb.item", symbol=o.symbol, buy_source=source_name(o.buy_source), buy_price=format_price(o.buy_price),
        sell_source=source_name(o.sell_source), sell_price=format_price(o.sell_price), gross=format_pct(o.gross_pct, 3),
        net=format_pct(o.net_pct, 3), net_profit=format_price(o.net_profit), net_pre=format_pct(o.net_pct_prefunded, 3),
        volume=volume,
    )


def arbitrage_text(ctx: AppContext, u: UserCtx, symbols: list[str]) -> tuple[str, list[Opportunity]]:
    lang = u.lang
    size = Decimal(ctx.runtime.get("arb_trade_size_usdt"))
    lines = [
        t(lang, "arb.title"),
        now_line(ctx, lang),
        t(lang, "arb.threshold", pct=format_pct(u.arb_min_net_pct), size=format_price(size)),
        "",
    ]
    above = ctx.quotes.opportunities(symbols, u.arb_min_net_pct)
    shown = above
    if above:
        lines.append(t(lang, "arb.signals"))
    else:
        shown = ctx.quotes.opportunities(symbols, None)[:3]
        lines.append(t(lang, "arb.none") if shown else t(lang, "arb.no_data"))
    for o in shown:
        lines += ["", _item(lang, o)]
    lines += ["", t(lang, "arb.disclaimer")]
    return "\n".join(lines), shown


def arbitrage_detail_text(ctx: AppContext, lang: str, o: Opportunity) -> str:
    base, _ = split_symbol(o.symbol)
    limit = t(lang, "arb.limit_note") if o.liquidity_limited else ""
    text = t(
        lang, "arb.detail", symbol=o.symbol, buy_source=source_name(o.buy_source), sell_source=source_name(o.sell_source),
        qty=format_price(o.quantity), base=base, cost=format_price(o.cost), limit=limit,
        gross=format_pct(o.gross_pct, 3), gross_profit=format_price(o.gross_profit), fees=format_price(o.trade_fees),
        slip=format_price(o.slippage_cost), withdraw=format_price(o.withdraw_fee_cost),
        net_profit=format_price(o.net_profit), net=format_pct(o.net_pct, 3),
        net_pre_profit=format_price(o.net_profit_prefunded), net_pre=format_pct(o.net_pct_prefunded, 3),
    )
    return f"{text}\n\n{t(lang, 'arb.disclaimer')}"
