"""Форматирование чисел и времени для сообщений и графиков."""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NBSP = " "  # неразрывный пробел как разделитель тысяч


def format_price(value: Decimal | float | int | None) -> str:
    """Цена с адекватным числом знаков: 61 469.2 · 1.6 · 0.00001234."""
    if value is None:
        return "—"
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    magnitude = abs(number)
    if magnitude >= 1000:
        places = 2
    elif magnitude >= 1:
        places = 4
    elif magnitude >= Decimal("0.01"):
        places = 5
    else:
        places = 8
    quantized = number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    text = f"{quantized:,.{places}f}".replace(",", NBSP)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def format_pct(value: Decimal | float | None, places: int = 2, signed: bool = False) -> str:
    if value is None:
        return "—"
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    text = f"{number:{'+' if signed else ''}.{places}f}"
    return f"{text}%"


def format_volume(value: Decimal | None) -> str:
    if value is None:
        return "—"
    for limit, suffix in ((Decimal(10) ** 9, "B"), (Decimal(10) ** 6, "M"), (Decimal(10) ** 3, "K")):
        if value >= limit:
            return f"{value / limit:.2f}{suffix}"
    return f"{value:.2f}"


def get_tz(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return UTC


def to_local(moment: datetime, tz_name: str) -> datetime:
    return moment.astimezone(get_tz(tz_name))


def format_time(moment: datetime | None, tz_name: str, with_date: bool = False) -> str:
    if moment is None:
        return "—"
    local = to_local(moment, tz_name)
    return local.strftime("%d.%m %H:%M:%S" if with_date else "%H:%M:%S")


_AGE_UNITS = {
    "ru": ("с", "мин", "ч", "дн"),
    "uk": ("с", "хв", "г", "дн"),
    "en": ("s", "min", "h", "d"),
}


def format_age(seconds: float, lang: str = "ru") -> str:
    sec, minute, hour, day = _AGE_UNITS.get(lang, _AGE_UNITS["ru"])
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} {sec}"
    if seconds < 3600:
        return f"{seconds // 60} {minute}"
    if seconds < 86400:
        return f"{seconds // 3600} {hour} {seconds % 3600 // 60} {minute}"
    return f"{seconds // 86400} {day}"
