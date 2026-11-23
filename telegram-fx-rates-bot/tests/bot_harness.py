"""Стенд для проверки Telegram-слоя без сети: настоящий Dispatcher, middleware и обработчики + поддельная сессия Bot."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis.aioredis
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.alerts import AlertEngine
from app.bot.context import AppContext
from app.bot.factory import create_dispatcher
from app.config import Settings
from app.core import Core
from app.database import Database
from app.domain import SourceKind
from app.services.chart_service import ChartService
from app.services.p2p import P2PService
from app.services.quotes import QuoteService
from app.services.users import UserService
from tests.conftest import make_quote
from tests.fake_p2p import fake_platforms

BOT_ID = 777
BOT_USER = User(id=BOT_ID, is_bot=True, first_name="FxBot", username="fx_bot")


class RecordingSession(BaseSession):
    """Запоминает все вызовы Bot API и возвращает правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._ids = itertools.count(1000)

    async def close(self) -> None:
        return None

    async def stream_content(self, *a: Any, **k: Any):  # pragma: no cover
        raise NotImplementedError

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        name = type(method).__name__
        data = method.model_dump(exclude_none=True)
        self.calls.append((name, data))
        if name in ("SendMessage", "SendPhoto", "EditMessageText", "EditMessageMedia", "EditMessageReplyMarkup"):
            chat_id = data.get("chat_id", 1)
            return Message(
                message_id=next(self._ids), date=datetime.now(UTC), chat=Chat(id=chat_id if isinstance(chat_id, int) else 1, type="private"),
                from_user=BOT_USER, text=data.get("text"), caption=data.get("caption"),
            )
        if name == "GetMe":
            return BOT_USER
        return True

    # ----- удобные выборки -----
    def of(self, *names: str) -> list[dict[str, Any]]:
        return [d for n, d in self.calls if n in names]

    def texts(self) -> list[str]:
        return [d.get("text") or d.get("caption") or "" for n, d in self.calls
                if n in ("SendMessage", "EditMessageText", "SendPhoto", "EditMessageMedia")]

    def last_text(self) -> str:
        return self.texts()[-1]

    def last_markup(self) -> list[list[dict[str, Any]]]:
        for n, d in reversed(self.calls):
            if n in ("SendMessage", "EditMessageText", "SendPhoto", "EditMessageMedia") and d.get("reply_markup"):
                return d["reply_markup"]["inline_keyboard"]
        return []

    def button_data(self) -> list[str]:
        return [b["callback_data"] for row in self.last_markup() for b in row if "callback_data" in b]

    def find_button(self, contains: str) -> str:
        for row in self.last_markup():
            for b in row:
                if contains in b.get("text", "") and "callback_data" in b:
                    return b["callback_data"]
        raise AssertionError(f"кнопка «{contains}» не найдена; есть: {[b['text'] for r in self.last_markup() for b in r]}")

    def clear(self) -> None:
        self.calls.clear()


class BotApp:
    def __init__(self) -> None:
        self.update_id = itertools.count(1)
        self.msg_id = itertools.count(1)

    @classmethod
    async def create(cls, admin_ids: tuple[int, ...] = (999,), rate_limit: int = 1000, redis: bool = True) -> BotApp:
        self = cls()
        self.settings = Settings(
            _env_file=None, bot_token="123456:TESTTOKENTESTTOKENTESTTOKENTESTTOKEN", admin_ids=list(admin_ids),
            database_url="sqlite+aiosqlite://", user_rate_limit_count=rate_limit, user_rate_limit_window_seconds=10,
            timezone="Europe/Kyiv",
        )
        self.db = Database(self.settings.database_url)
        await self.db.create_all()
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True) if redis else None
        self.core = Core(self.settings, db=self.db, redis=fake_redis)
        await self.core.start(run_collectors=False)
        quotes = QuoteService(self.core.store, self.core.health, self.core.runtime, self.settings)
        self.ctx = AppContext(core=self.core, quotes=quotes, users=UserService(self.db, self.settings, self.core.assets),
                              charts=ChartService(self.db, quotes), p2p=P2PService(fake_platforms()))
        self.session = RecordingSession()
        self.bot = Bot(token=self.settings.bot_token.get_secret_value(), session=self.session)
        self.sent: list[tuple[int, str]] = []

        async def send(telegram_id: int, text: str) -> bool:
            self.sent.append((telegram_id, text))
            return True

        self.engine = AlertEngine(self.db, self.core.store, quotes, self.core.runtime, self.settings, send)
        self.ctx.alerts = self.engine
        self.ctx.users.on_settings_changed = self.engine.invalidate
        _reload_handlers()
        self.dp = create_dispatcher(self.ctx)
        return self

    async def close(self) -> None:
        await self.core.stop()

    # ----- данные -----
    def load_market(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        store = self.core.store
        prices = {"binance": ("61469.2", "61469.3", "61469.25"), "bybit": ("61470.0", "61470.5", "61470.2"),
                  "okx": ("61460.0", "61460.1", "61460.05"), "bitget": ("61480.0", "61481", "61480.5"),
                  "kucoin": ("61465.0", "61466", "61465.5")}
        for source, (bid, ask, last) in prices.items():
            store.put(make_quote(source=source, symbol="BTC/USDT", bid=bid, ask=ask, last=last, bid_size="2",
                                 ask_size="2", volume="19500", received_at=now))
        for source, (bid, ask) in {"binance": ("1730.1", "1730.2"), "okx": ("1730.0", "1730.1")}.items():
            store.put(make_quote(source=source, symbol="ETH/USDT", bid=bid, ask=ask, last=bid, received_at=now))
        store.put(make_quote(source="monobank", symbol="USD/UAH", kind=SourceKind.BANK, bid="44.91", ask="45.4091", last=None,
                             bid_size=None, ask_size=None, received_at=now, source_ts=now - timedelta(minutes=3)))
        store.put(make_quote(source="privatbank", symbol="USD/UAH", kind=SourceKind.BANK, bid="44.75", ask="45.45", last=None,
                             bid_size=None, ask_size=None, received_at=now))
        store.put(make_quote(source="monobank", symbol="EUR/UAH", kind=SourceKind.BANK, bid="49.26", ask="50", last=None,
                             bid_size=None, ask_size=None, received_at=now))
        for health in self.core.health.all():
            self.core.health.record_success(health.source)

    # ----- ввод от пользователя -----
    def _user(self, user_id: int, name: str, lang: str | None) -> User:
        return User(id=user_id, is_bot=False, first_name=name, username=f"user{user_id}", language_code=lang)

    async def say(self, text: str, user_id: int = 1, name: str = "Test", lang: str | None = "ru") -> RecordingSession:
        message = Message(message_id=next(self.msg_id), date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                          from_user=self._user(user_id, name, lang), text=text)
        await self.dp.feed_update(self.bot, Update(update_id=next(self.update_id), message=message))
        return self.session

    async def press(self, data: str, user_id: int = 1, name: str = "Test", lang: str | None = "ru", photo: bool = False) -> RecordingSession:
        origin = Message(message_id=next(self.msg_id), date=datetime.now(UTC), chat=Chat(id=user_id, type="private"),
                         from_user=BOT_USER, text=None if photo else "старый текст",
                         photo=[{"file_id": "x", "file_unique_id": "y", "width": 1, "height": 1}] if photo else None)  # type: ignore[list-item]
        cb = CallbackQuery(id=str(next(self.update_id)), from_user=self._user(user_id, name, lang), chat_instance="ci",
                           message=origin, data=data)
        await self.dp.feed_update(self.bot, Update(update_id=next(self.update_id), callback_query=cb))
        return self.session


def _reload_handlers() -> None:
    """Роутеры aiogram привязываются к одному Dispatcher; для каждого теста нужны свежие экземпляры."""
    import importlib

    from app.bot.handlers import (
        admin,
        alerts,
        arbitrage,
        banks,
        charts,
        compare,
        crypto,
        menu,
        p2p,
        rates,
        settings,
    )

    for module in (rates, crypto, banks, compare, charts, alerts, arbitrage, p2p, settings, admin, menu):
        importlib.reload(module)
