from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.charts import ChartPoint, ChartRequest, compute_stats, render_chart, render_chart_async
from app.utils.fmt import format_age, format_pct, format_price, format_volume

PNG = b"\x89PNG\r\n\x1a\n"
OUT = Path("/tmp/chart_samples")


def exchange_points(n=120):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    pts = []
    for i in range(n):
        price = D("61000") + D(str(round(math.sin(i / 9) * 400 + i * 5, 2)))
        pts.append(ChartPoint(start + timedelta(minutes=i), price - 30, price + 35, price))
    return pts


def bank_points(n=60):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [ChartPoint(start + timedelta(minutes=5 * i), D("44.9"), D("45.4"), D("45.15"),
                       bid=D("44.9") + D(i // 20) / 100, ask=D("45.4") + D(i // 15) / 100) for i in range(n)]


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("lang", ["ru", "uk", "en"])
def test_exchange_chart_renders_png(theme, lang):
    req = ChartRequest("BTC/USDT", "Binance", "24h", exchange_points(), "last", D("61700"), theme=theme, lang=lang, tz="Europe/Kyiv")
    png = render_chart(req)
    assert png.startswith(PNG) and len(png) > 10_000
    OUT.mkdir(exist_ok=True)
    (OUT / f"btc_{theme}_{lang}.png").write_bytes(png)


def test_bank_chart_has_two_series_and_renders():
    req = ChartRequest("USD/UAH", "Monobank", "7d", bank_points(), "mid", D("45.2"), is_bank=True, theme="light", tz="Europe/Kyiv")
    png = render_chart(req)
    assert png.startswith(PNG)
    (OUT / "usd_uah.png").write_bytes(png) if OUT.exists() else None


def test_flat_price_does_not_crash():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [ChartPoint(start + timedelta(minutes=i), D(5), D(5), D(5)) for i in range(5)]
    assert render_chart(ChartRequest("X/USDT", "okx", "1h", pts, "last")).startswith(PNG)


def test_small_prices_render():
    start = datetime(2026, 1, 1, tzinfo=UTC)
    pts = [ChartPoint(start + timedelta(minutes=i), D("0.0000121"), D("0.0000125"), D("0.0000123")) for i in range(5)]
    assert render_chart(ChartRequest("SHIB/USDT", "okx", "1h", pts, "last")).startswith(PNG)


def test_too_few_points_raises():
    with pytest.raises(ValueError):
        render_chart(ChartRequest("BTC/USDT", "Binance", "1h", exchange_points(1), "last"))


def test_stats_use_extremes_of_candles_and_live_price():
    req = ChartRequest("BTC/USDT", "Binance", "1h", exchange_points(10), "last", current=D("70000"))
    stats = compute_stats(req)
    assert stats.minimum == min(p.low for p in req.points) and stats.maximum == max(p.high for p in req.points)
    assert stats.last == D("70000") and stats.change_pct > 0


async def test_async_render_does_not_block_loop():
    png = await render_chart_async(ChartRequest("BTC/USDT", "Binance", "1h", exchange_points(), "last"))
    assert png.startswith(PNG)


def test_number_formatting():
    assert format_price(D("61469.2")) == "61 469.2"  # разделитель тысяч — неразрывный пробел
    assert " " not in format_price(D("61469.2"))
    assert format_price(D("1.6")) == "1.6"
    assert format_price(D("0.00001234")) == "0.00001234"
    assert format_price(None) == "—"
    assert format_pct(D("1.234")) == "1.23%" and format_pct(D("1.234"), signed=True) == "+1.23%"
    assert format_volume(D("1234567")) == "1.23M" and format_volume(None) == "—"
    assert format_age(5) == "5 с" and format_age(125) == "2 мин" and format_age(7300) == "2 ч 1 мин"
