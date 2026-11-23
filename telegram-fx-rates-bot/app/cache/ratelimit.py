"""Ограничение частоты запросов пользователей (фиксированное окно). Redis, либо память при его отсутствии."""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from redis.asyncio import Redis

log = logging.getLogger(__name__)


class UserRateLimiter:
    def __init__(self, redis: Redis | None, limit: int, window_seconds: int) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window_seconds
        self._hits: dict[int, deque[float]] = defaultdict(deque)

    async def allow(self, user_id: int) -> bool:
        if self._redis is not None:
            try:
                key = f"fx:rl:{user_id}"
                count = await self._redis.incr(key)
                if count == 1:
                    await self._redis.expire(key, self._window)
                return int(count) <= self._limit
            except Exception as exc:  # Redis упал — не блокируем пользователей, используем память
                log.warning("rate limit: Redis недоступен (%s), используется память", exc)
        return self._allow_in_memory(user_id)

    def _allow_in_memory(self, user_id: int) -> bool:
        now = time.monotonic()
        hits = self._hits[user_id]
        while hits and now - hits[0] > self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True
