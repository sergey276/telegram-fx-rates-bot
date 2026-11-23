from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.domain import Quote, SourceKind

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_lines(name: str) -> list[str]:
    return [line for line in (FIXTURES / name).read_text(encoding="utf-8").splitlines() if line.strip()]


def make_quote(
    source: str = "binance",
    symbol: str = "BTC/USDT",
    bid: str | None = "100",
    ask: str | None = "101",
    last: str | None = "100.5",
    bid_size: str | None = "1",
    ask_size: str | None = "1",
    volume: str | None = None,
    received_at: datetime | None = None,
    kind: SourceKind = SourceKind.EXCHANGE,
    source_ts: datetime | None = None,
) -> Quote:
    def d(v: str | None) -> Decimal | None:
        return Decimal(v) if v is not None else None

    return Quote(
        source=source,
        symbol=symbol,
        kind=kind,
        bid=d(bid),
        ask=d(ask),
        last=d(last),
        bid_size=d(bid_size),
        ask_size=d(ask_size),
        volume_24h=d(volume),
        source_ts=source_ts,
        received_at=received_at or datetime.now(UTC),
    )


@pytest.fixture
def quote_factory():
    return make_quote
