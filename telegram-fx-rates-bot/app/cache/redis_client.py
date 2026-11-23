"""Подключение к Redis. Если Redis недоступен или не настроен, бот работает на встроенном кеше в памяти."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

log = logging.getLogger(__name__)


async def create_redis(url: str) -> Redis | None:
    if not url:
        log.warning("REDIS_URL не задан: кеш работает только в памяти процесса (после перезапуска данные теряются)")
        return None
    client: Redis = Redis.from_url(url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
    try:
        await client.ping()
    except Exception as exc:
        log.error("Redis недоступен (%s): используется кеш в памяти", exc)
        await client.aclose()
        return None
    log.info("Redis подключён")
    return client
