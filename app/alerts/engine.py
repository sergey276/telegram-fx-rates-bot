"""Движок уведомлений.

Защита от повторов (три уровня):
1. *срабатывание по фронту*: после сигнала уведомление «разряжается» и снова «заряжается» только когда условие
   перестало выполняться — пока цена остаётся выше порога, сообщения не повторяются;
2. *интервал*: не чаще, чем max(интервал уведомления, интервал пользователя в настройках);
3. *временное отключение*: на время паузы сигналы не отправляются (после паузы придёт сигнал, если условие всё ещё выполняется).

Условие вычисляется только по свежим котировкам: данные устарели — состояние уведомления не меняется.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.alerts.types import AlertType, window_label
from app.analytics import Metric
from app.cache import QuoteStore
from app.config import Settings
from app.database import Database
from app.database.repositories import ActiveAlert, AlertRepo, HistoryRepo, UserRepo
from app.domain import Freshness, source_name, utcnow
from app.i18n import t
from app.services.quotes import QuoteService
from app.services.runtime_settings import RuntimeSettings
from app.utils.fmt import format_pct, format_price

log = logging.getLogger(__name__)

# Возвращает True — доставлено, False — временная ошибка, None — пользователь заблокировал бота.
SendFn = Callable[[int, str], Awaitable[bool | None]]

_RELOAD_SECONDS = 30
_REFERENCE_TTL = 60


@dataclass(slots=True)
class Fired:
    text: str
    value: Decimal


class AlertEngine:
    def __init__(
        self,
        db: Database,
        store: QuoteStore,
        quotes: QuoteService,
        runtime: RuntimeSettings,
        settings: Settings,
        send: SendFn,
    ) -> None:
        self._db = db
        self._store = store
        self._quotes = quotes
        self._runtime = runtime
        self._settings = settings
        self._send = send
        self._alerts: list[ActiveAlert] = []
        self._loaded_at = 0.0
        self._reference: dict[tuple[str, str, int], tuple[float, Decimal | None]] = {}
        self._task: asyncio.Task[None] | None = None

    # ----- жизненный цикл -----
    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="alert-engine")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    def invalidate(self) -> None:
        """Вызывается после создания/удаления/изменения уведомлений и настроек пользователя."""
        self._loaded_at = 0.0

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("ошибка цикла уведомлений")
            await asyncio.sleep(self._settings.alerts_check_seconds)

    # ----- один проход -----
    async def tick(self, now: datetime | None = None) -> int:
        """Проверяет все активные уведомления. Возвращает число отправленных сообщений."""
        if not self._runtime.get("alerts_enabled"):
            return 0
        now = now or utcnow()
        if time.monotonic() - self._loaded_at > _RELOAD_SECONDS:
            async with self._db.session() as session:
                self._alerts = await AlertRepo(session).list_active()
            self._loaded_at = time.monotonic()
        sent = 0
        for alert in list(self._alerts):
            try:
                sent += int(await self._process(alert, now))
            except Exception:
                log.exception("уведомление %s: ошибка обработки", alert.id)
        return sent

    async def _process(self, alert: ActiveAlert, now: datetime) -> bool:
        fired = await self._evaluate(alert)
        if fired is None:
            if self._unknown(alert):
                return False
            if not alert.armed:  # условие перестало выполняться — «заряжаем» снова
                await self._set_state(alert, armed=True)
            return False
        if not alert.armed:
            return False
        if alert.muted_until is not None and alert.muted_until > now:
            return False
        cooldown = timedelta(minutes=max(alert.cooldown_minutes, alert.notify_interval_min))
        if alert.last_triggered_at is not None and now - alert.last_triggered_at < cooldown:
            return False

        delivered = await self._send(alert.telegram_id, fired.text)
        if delivered is None:
            async with self._db.session() as session:
                await UserRepo(session).set_blocked(alert.telegram_id, True)
            self.invalidate()
            return False
        if not delivered:
            return False  # временный сбой: попробуем на следующем проходе, состояние не меняем
        async with self._db.session() as session:
            repo = AlertRepo(session)
            await repo.add_history(alert, fired.text, fired.value, True, now)
            await repo.set_state(alert.id, armed=False, triggered_at=now)
        alert.armed, alert.last_triggered_at = False, now
        return True

    async def _set_state(self, alert: ActiveAlert, armed: bool) -> None:
        async with self._db.session() as session:
            await AlertRepo(session).set_state(alert.id, armed=armed)
        alert.armed = armed

    # ----- вычисление условий -----
    def _unknown(self, alert: ActiveAlert) -> bool:
        """True, если по свежим данным условие вычислить нельзя (тогда состояние не трогаем)."""
        return not self._has_fresh_data(alert)

    def _has_fresh_data(self, alert: ActiveAlert) -> bool:
        kind = AlertType(alert.type)
        if kind.needs_source:
            quote = self._store.get(alert.source or "", alert.symbol)
            return quote is not None and self._store.freshness(quote) is Freshness.FRESH
        return len(self._store.usable(self._quotes.exchange_quotes(alert.symbol))) >= 2

    async def _evaluate(self, alert: ActiveAlert) -> Fired | None:
        """Fired — условие выполнено (с готовым текстом); None — не выполнено или данных недостаточно."""
        kind = AlertType(alert.type)
        lang = alert.language
        if kind.needs_source:
            quote = self._store.get(alert.source or "", alert.symbol)
            if quote is None or self._store.freshness(quote) is not Freshness.FRESH or quote.history_price is None:
                return None
            price = quote.history_price[0]
            src = source_name(quote.source)
            if kind is AlertType.PRICE_ABOVE and price >= alert.threshold:
                return Fired(
                    t(lang, "fire.price_above", symbol=alert.symbol, source=src, price=format_price(price),
                      threshold=format_price(alert.threshold)), price)
            if kind is AlertType.PRICE_BELOW and price <= alert.threshold:
                return Fired(
                    t(lang, "fire.price_below", symbol=alert.symbol, source=src, price=format_price(price),
                      threshold=format_price(alert.threshold)), price)
            if kind is AlertType.PCT_CHANGE and alert.window_minutes:
                old = await self._reference_price(alert.source or "", alert.symbol, alert.window_minutes)
                if old is None or old == 0:
                    return None
                change = (price - old) / old * 100
                if abs(change) >= alert.threshold:
                    return Fired(
                        t(lang, "fire.pct_change", symbol=alert.symbol, source=src, change=format_pct(change, 2, True),
                          window=window_label(lang, alert.window_minutes), old=format_price(old),
                          price=format_price(price)), change)
            return None

        if kind is AlertType.SPREAD:
            cmp = self._quotes.compare_exchanges(alert.symbol, Metric.LAST)
            pct = cmp.diff_pct
            if pct is not None and pct >= alert.threshold and cmp.lowest and cmp.highest:
                return Fired(
                    t(lang, "fire.spread", symbol=alert.symbol, low_source=source_name(cmp.lowest.source),
                      high_source=source_name(cmp.highest.source), pct=format_pct(pct),
                      low=format_price(cmp.lowest.value), high=format_price(cmp.highest.value)), pct)
            return None

        best = self._quotes.best_opportunity(alert.symbol)
        if best is not None and best.net_pct >= alert.threshold:
            return Fired(
                t(lang, "fire.arbitrage", symbol=alert.symbol, buy_source=source_name(best.buy_source),
                  buy_price=format_price(best.buy_price), sell_source=source_name(best.sell_source),
                  sell_price=format_price(best.sell_price), gross=format_pct(best.gross_pct),
                  net=format_pct(best.net_pct)), best.net_pct)
        return None

    async def _reference_price(self, source: str, symbol: str, window_minutes: int) -> Decimal | None:
        key = (source, symbol, window_minutes)
        cached = self._reference.get(key)
        if cached and time.monotonic() - cached[0] < _REFERENCE_TTL:
            return cached[1]
        moment = utcnow() - timedelta(minutes=window_minutes)
        tolerance = timedelta(minutes=max(10, window_minutes // 5))
        async with self._db.session() as session:
            value = await HistoryRepo(session, self._db.dialect).price_at(source, symbol, moment, tolerance)
        self._reference[key] = (time.monotonic(), value)
        return value
