"""Состояние источников: подключения, ошибки, ручное отключение администратором."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.database import Database
from app.database.repositories import StatusRepo
from app.domain import SourceKind, utcnow

log = logging.getLogger(__name__)

_MAX_RECENT = 300


@dataclass(slots=True)
class SourceHealth:
    source: str
    kind: SourceKind
    enabled: bool = True
    ws_connected: bool = False
    supports_ws: bool = False
    last_success_at: datetime | None = None
    last_message_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_errors: int = 0
    total_errors: int = 0
    unlisted: tuple[str, ...] = ()  # пары, которых нет у источника

    @property
    def last_activity_at(self) -> datetime | None:
        points = [p for p in (self.last_success_at, self.last_message_at) if p is not None]
        return max(points) if points else None

    def state(self, now: datetime, fresh_seconds: float) -> str:
        """ok | degraded | down | disabled | unknown."""
        if not self.enabled:
            return "disabled"
        activity = self.last_activity_at
        if activity is None:
            return "down" if self.consecutive_errors else "unknown"
        age = (now - activity).total_seconds()
        if self.consecutive_errors >= 3 or age > fresh_seconds * 4:
            return "down"
        if self.consecutive_errors > 0 or age > fresh_seconds or (self.supports_ws and not self.ws_connected):
            return "degraded"
        return "ok"


class HealthRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourceHealth] = {}
        self._recent: deque[tuple[datetime, str, str]] = deque(maxlen=_MAX_RECENT)
        self._pending_errors: list[tuple[str, str, datetime]] = []
        self._dirty: set[str] = set()
        self._on_enabled_changed: list[Callable[[], None]] = []

    def register(self, source: str, kind: SourceKind, supports_ws: bool = False) -> SourceHealth:
        health = self._sources.get(source)
        if health is None:
            health = self._sources[source] = SourceHealth(source=source, kind=kind, supports_ws=supports_ws)
        health.kind = kind
        health.supports_ws = supports_ws
        self._dirty.add(source)
        return health

    def get(self, source: str) -> SourceHealth | None:
        return self._sources.get(source)

    def all(self) -> list[SourceHealth]:
        return list(self._sources.values())

    def is_enabled(self, source: str) -> bool:
        health = self._sources.get(source)
        return health.enabled if health else True

    def disabled_sources(self) -> set[str]:
        return {s.source for s in self._sources.values() if not s.enabled}

    def on_enabled_changed(self, callback: Callable[[], None]) -> None:
        self._on_enabled_changed.append(callback)

    # ----- события -----
    def record_success(self, source: str) -> None:
        health = self._sources.get(source)
        if health is None:
            return
        health.last_success_at = utcnow()
        health.consecutive_errors = 0
        self._dirty.add(source)

    def record_message(self, source: str) -> None:
        """Горячий путь (каждое сообщение WebSocket): только метка времени, без записи в БД."""
        health = self._sources.get(source)
        if health is not None:
            health.last_message_at = utcnow()
            health.consecutive_errors = 0

    def record_error(self, source: str, message: str) -> None:
        now = utcnow()
        health = self._sources.get(source)
        if health is not None:
            health.last_error_at = now
            health.last_error = message[:500]
            health.consecutive_errors += 1
            health.total_errors += 1
            self._dirty.add(source)
        self._recent.append((now, source, message[:500]))
        # не засоряем БД повторами одной и той же ошибки подряд
        if not self._pending_errors or self._pending_errors[-1][:2] != (source, message[:1000]):
            self._pending_errors.append((source, message[:1000], now))
        log.warning("источник %s: %s", source, message)

    def set_ws(self, source: str, connected: bool) -> None:
        health = self._sources.get(source)
        if health is not None and health.ws_connected != connected:
            health.ws_connected = connected
            self._dirty.add(source)

    def set_unlisted(self, source: str, symbols: set[str]) -> None:
        health = self._sources.get(source)
        if health is not None:
            health.unlisted = tuple(sorted(symbols))

    def set_enabled(self, source: str, enabled: bool) -> bool:
        health = self._sources.get(source)
        if health is None:
            return False
        health.enabled = enabled
        self._dirty.add(source)
        for callback in self._on_enabled_changed:
            callback()
        return True

    def recent_errors(self, limit: int = 20, source: str | None = None) -> list[tuple[datetime, str, str]]:
        items = [e for e in reversed(self._recent) if source is None or e[1] == source]
        return items[:limit]

    # ----- БД -----
    async def load(self, db: Database) -> None:
        """Восстанавливает признак «отключён администратором» после перезапуска."""
        async with db.session() as session:
            stored = await StatusRepo(session, db.dialect).load_all()
        for source, row in stored.items():
            health = self._sources.get(source)
            if health is not None:
                health.enabled = row.is_enabled
                health.total_errors = row.total_errors
                health.last_error = row.last_error
                health.last_error_at = row.last_error_at

    async def persist(self, db: Database) -> None:
        if not self._dirty and not self._pending_errors:
            return
        dirty, self._dirty = self._dirty, set()
        errors, self._pending_errors = self._pending_errors, []
        rows = []
        for source in dirty:
            h = self._sources[source]
            rows.append(
                {
                    "source": h.source,
                    "kind": h.kind.value,
                    "is_enabled": h.enabled,
                    "ws_connected": h.ws_connected,
                    "last_success_at": h.last_activity_at,
                    "last_message_at": h.last_message_at,
                    "last_error_at": h.last_error_at,
                    "last_error": h.last_error,
                    "consecutive_errors": h.consecutive_errors,
                    "total_errors": h.total_errors,
                    "updated_at": utcnow(),
                }
            )
        try:
            async with db.session() as session:
                repo = StatusRepo(session, db.dialect)
                await repo.upsert_many(rows)
                await repo.add_errors(errors)
        except Exception:
            self._dirty |= dirty
            self._pending_errors = errors + self._pending_errors
            log.exception("не удалось сохранить статус источников")
