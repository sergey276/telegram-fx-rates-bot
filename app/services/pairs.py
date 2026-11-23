"""Проверка новых торговых пар перед добавлением в каталог."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from app.core import Core
from app.domain import SourceKind
from app.providers.base import ExchangeProvider
from app.utils.symbols import FIAT_CODES, InvalidSymbol, asset_kind, normalize_symbol, split_symbol


class PairRejected(ValueError):
    """Пару нельзя добавить (текст — причина для администратора)."""


@dataclass(slots=True)
class PairProbe:
    symbol: str
    kind: str
    listed: list[str] = field(default_factory=list)
    not_listed: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)


def validate_format(raw: str) -> str:
    try:
        symbol = normalize_symbol(raw)
    except InvalidSymbol as exc:
        raise PairRejected("Неверный формат. Пример: BTC/USDT или USD/UAH") from exc
    base, quote = split_symbol(symbol)
    if asset_kind(symbol) == "fiat":
        return symbol
    if base in FIAT_CODES or quote in FIAT_CODES:
        raise PairRejected("Смешанные пары «фиат/крипто» не поддерживаются: используйте крипто/USDT или фиат/фиат")
    if quote != "USDT":
        raise PairRejected("Для криптовалют поддерживаются только пары к USDT (например SOL/USDT)")
    return symbol


async def probe_pair(core: Core, symbol: str) -> PairProbe:
    """Проверяет, на каких включённых источниках пара реально существует (живые запросы к биржам)."""
    probe = PairProbe(symbol=symbol, kind=asset_kind(symbol))
    if probe.kind == "fiat":
        # Банки уже опрашиваются целиком и лежат в кеше; лишний запрос нарушил бы лимит Monobank.
        for provider in core.providers.values():
            if provider.kind is SourceKind.BANK and core.health.is_enabled(provider.name):
                (probe.listed if core.store.get(provider.name, symbol) else probe.not_listed).append(provider.name)
        return probe

    exchanges = [
        p for p in core.providers.values()
        if isinstance(p, ExchangeProvider) and core.health.is_enabled(p.name)
    ]

    async def one(provider: ExchangeProvider) -> None:
        try:
            result = await provider.fetch_detailed([symbol])
        except Exception as exc:
            probe.errors[provider.name] = f"{type(exc).__name__}: {exc}"
            return
        if result.quotes:
            probe.listed.append(provider.name)
            core.store.put_many(result.quotes)
        elif result.failed:
            probe.errors[provider.name] = str(next(iter(result.failed.values())))
        else:
            probe.not_listed.append(provider.name)

    await asyncio.gather(*(one(p) for p in exchanges))
    probe.listed.sort()
    probe.not_listed.sort()
    return probe
