"""Генерация графиков цены (matplotlib, Agg) в PNG для отправки в Telegram.

Оформление: тонкие линии (2 px), приглушённая сетка, подписи цветом текста (не цветом серии), тема подобрана
отдельно для светлого и тёмного фона. Для одного ряда легенда не нужна (название — в заголовке); для двух
рядов (покупка/продажа банка) есть легенда и прямые подписи на концах линий.
"""

from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from app.utils.fmt import format_price, get_tz  # noqa: E402

THEMES = {
    "light": {
        "surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "s1": "#2a78d6", "s2": "#eb6834",
    },
    "dark": {
        "surface": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "s1": "#3987e5", "s2": "#d95926",
    },
}

LABELS = {
    "ru": {"min": "Мин", "max": "Макс", "now": "Сейчас", "source": "Источник", "period": "Период", "tz": "время",
           "change": "Изменение", "last": "цена последней сделки", "mid": "середина bid/ask",
           "buy": "Покупка банком", "sell": "Продажа банком", "cross": "кросс-курс"},
    "uk": {"min": "Мін", "max": "Макс", "now": "Зараз", "source": "Джерело", "period": "Період", "tz": "час",
           "change": "Зміна", "last": "ціна останньої угоди", "mid": "середина bid/ask",
           "buy": "Купівля банком", "sell": "Продаж банком", "cross": "крос-курс"},
    "en": {"min": "Min", "max": "Max", "now": "Now", "source": "Source", "period": "Period", "tz": "time",
           "change": "Change", "last": "last trade price", "mid": "bid/ask mid",
           "buy": "Bank buys", "sell": "Bank sells", "cross": "cross rate"},
}

PERIOD_LABELS = {
    "ru": {"1h": "1 час", "24h": "24 часа", "7d": "7 дней", "30d": "30 дней"},
    "uk": {"1h": "1 година", "24h": "24 години", "7d": "7 днів", "30d": "30 днів"},
    "en": {"1h": "1 hour", "24h": "24 hours", "7d": "7 days", "30d": "30 days"},
}


@dataclass(slots=True)
class ChartPoint:
    at: datetime
    low: Decimal
    high: Decimal
    close: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None


@dataclass(slots=True)
class ChartRequest:
    symbol: str
    source_name: str
    period: str
    points: list[ChartPoint]
    price_kind: str  # last | mid | cross
    current: Decimal | None = None
    is_bank: bool = False
    theme: str = "dark"
    lang: str = "ru"
    tz: str = "UTC"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class ChartStats:
    minimum: Decimal
    maximum: Decimal
    first: Decimal
    last: Decimal

    @property
    def change_pct(self) -> Decimal | None:
        return (self.last - self.first) / self.first * 100 if self.first else None


def compute_stats(req: ChartRequest) -> ChartStats | None:
    if not req.points:
        return None
    if req.is_bank:
        values = [v for p in req.points for v in (p.bid, p.ask) if v is not None] or [p.close for p in req.points]
        first = req.points[0].bid or req.points[0].close
        last = req.current or req.points[-1].bid or req.points[-1].close
    else:
        values = [v for p in req.points for v in (p.low, p.high)]
        first, last = req.points[0].close, req.current or req.points[-1].close
    return ChartStats(min(values), max(values), first, last)


def render_chart(req: ChartRequest) -> bytes:
    """Синхронная отрисовка (вызывать через ``render_chart_async``). Бросает ValueError, если точек меньше двух."""
    if len(req.points) < 2:
        raise ValueError("недостаточно данных для графика")
    colors = THEMES.get(req.theme, THEMES["dark"])
    text = LABELS.get(req.lang, LABELS["ru"])
    stats = compute_stats(req)
    assert stats is not None
    tz = get_tz(req.tz)

    fig = Figure(figsize=(9, 5.2), dpi=130, facecolor=colors["surface"])
    FigureCanvasAgg(fig)
    ax = fig.add_axes((0.095, 0.16, 0.80, 0.66), facecolor=colors["surface"])

    xs = [mdates.date2num(p.at.astimezone(tz)) for p in req.points]
    to_f = float

    if req.is_bank:
        bids = [(x, to_f(p.bid)) for x, p in zip(xs, req.points, strict=True) if p.bid is not None]
        asks = [(x, to_f(p.ask)) for x, p in zip(xs, req.points, strict=True) if p.ask is not None]
        series = []
        if bids:
            series.append((text["buy"], colors["s1"], bids))
        if asks:
            series.append((text["sell"], colors["s2"], asks))
        if not series:
            series.append((text["cross"], colors["s1"], [(x, to_f(p.close)) for x, p in zip(xs, req.points, strict=True)]))
        for label, color, data in series:
            ax.step([d[0] for d in data], [d[1] for d in data], where="post", color=color, linewidth=2, label=label)
            ax.plot([data[-1][0]], [data[-1][1]], marker="o", markersize=8, markerfacecolor=color,
                    markeredgecolor=colors["surface"], markeredgewidth=2, linestyle="none", zorder=5)
            ax.annotate(
                format_price(data[-1][1]), xy=(data[-1][0], data[-1][1]), xytext=(8, 0), textcoords="offset points",
                color=colors["ink2"], fontsize=8, va="center", annotation_clip=False,
            )
        if len(series) > 1:
            legend = fig.legend(*ax.get_legend_handles_labels(), loc="upper right", bbox_to_anchor=(0.895, 0.965),
                                frameon=False, fontsize=9, ncol=2)
            for t in legend.get_texts():
                t.set_color(colors["ink2"])
    else:
        closes = [to_f(p.close) for p in req.points]
        ax.fill_between(xs, [to_f(p.low) for p in req.points], [to_f(p.high) for p in req.points],
                        color=colors["s1"], alpha=0.14, linewidth=0)
        ax.plot(xs, closes, color=colors["s1"], linewidth=2)

    # минимум и максимум периода — пунктир, подписи цветом текста
    for value, key, va in ((stats.maximum, "max", "bottom"), (stats.minimum, "min", "top")):
        ax.axhline(to_f(value), color=colors["muted"], linewidth=0.8, linestyle=(0, (4, 4)))
        ax.annotate(
            f"{text[key]} {format_price(value)}", xy=(0.005, to_f(value)), xycoords=("axes fraction", "data"),
            xytext=(0, 3 if va == "bottom" else -3), textcoords="offset points",
            color=colors["ink2"], fontsize=8, va=va, ha="left",
        )

    # текущая цена: маркер 8 px с кольцом цвета фона (у банка маркеры уже стоят на концах обеих линий)
    current = req.current if req.current is not None else req.points[-1].close
    if not req.is_bank:
        ax.plot([xs[-1]], [to_f(current)], marker="o", markersize=8, markerfacecolor=colors["s1"],
                markeredgecolor=colors["surface"], markeredgewidth=2, linestyle="none", zorder=5)

    # оси и сетка
    ax.grid(axis="y", color=colors["grid"], linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(colors["axis"])
    ax.tick_params(colors=colors["muted"], labelsize=8, length=0)
    ax.yaxis.set_major_formatter(lambda v, _p: format_price(Decimal(str(v))))
    locator = mdates.AutoDateLocator(minticks=4, maxticks=7)
    ax.xaxis.set_major_locator(locator)
    span = (max(xs) - min(xs)) or 1e-6
    fmt = "%H:%M" if span <= 2 else "%d.%m"  # span в сутках: до двух суток подписываем время, дальше — даты
    ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt, tz=tz))
    ax.set_xlim(min(xs), max(xs) + span * (0.06 if req.is_bank else 0.02))
    pad = (stats.maximum - stats.minimum) * Decimal("0.12") or abs(stats.maximum) * Decimal("0.001")
    ax.set_ylim(to_f(stats.minimum - pad), to_f(stats.maximum + pad * Decimal("1.4")))

    # заголовок и сводка
    period = PERIOD_LABELS.get(req.lang, PERIOD_LABELS["ru"]).get(req.period, req.period)
    fig.text(0.095, 0.93, req.symbol, color=colors["ink"], fontsize=15, fontweight="bold", va="center")
    kind_label = text["cross"] if req.price_kind == "cross" else text["mid"] if req.is_bank else text[req.price_kind]
    fig.text(0.095, 0.875, f"{text['source']}: {req.source_name} · {text['period']}: {period} · {kind_label}",
             color=colors["ink2"], fontsize=9, va="center")
    change = stats.change_pct
    change_text = f"   {text['change']} {change:+.2f}%" if change is not None else ""
    fig.text(
        0.095, 0.045,
        f"{text['now']} {format_price(current)}   {text['min']} {format_price(stats.minimum)}   "
        f"{text['max']} {format_price(stats.maximum)}{change_text}   ({text['tz']}: {req.tz})",
        color=colors["ink2"], fontsize=9, va="center",
    )

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", facecolor=colors["surface"])
    return buffer.getvalue()


async def render_chart_async(req: ChartRequest) -> bytes:
    """Отрисовка в потоке, чтобы не блокировать цикл событий (и Telegram-бота)."""
    return await asyncio.to_thread(render_chart, req)
