"""Настройка логирования: консоль + ротация файла. Секреты (токен бота) маскируются."""

from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_TOKEN_RE = re.compile(r"(?<!\d)\d{6,}:[A-Za-z0-9_-]{30,}")  # токен идёт в URL как /bot<токен>/, границы слова перед ним нет


class RedactFilter(logging.Filter):
    """Не даёт токену Telegram попасть в логи (он присутствует в URL запросов aiogram)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if _TOKEN_RE.search(message):
            record.msg = _TOKEN_RE.sub("<bot-token>", message)
            record.args = None
        return True


def setup_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.addFilter(RedactFilter())
    root.addHandler(console)

    try:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            Path(log_dir) / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(RedactFilter())
        root.addHandler(file_handler)
    except OSError as exc:  # нет прав на запись — продолжаем только с консолью
        root.warning("Файловый лог недоступен (%s), используется только консоль", exc)

    logging.getLogger("aiohttp").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
