"""Тексты интерфейса на трёх языках (ru / uk / en). Админ-панель — только на русском."""

from __future__ import annotations

from typing import Any

LANGUAGES = {"ru": "🇷🇺 Русский", "uk": "🇺🇦 Українська", "en": "🇬🇧 English"}
DEFAULT_LANG = "ru"

# key -> {lang: text}. Плейсхолдеры {name} обязаны совпадать во всех языках (проверяется тестом).
TEXTS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------ меню и общее
    "menu.rates": {"ru": "📊 Курсы валют", "uk": "📊 Курси валют", "en": "📊 Exchange rates"},
    "menu.crypto": {"ru": "🪙 Криптовалюты", "uk": "🪙 Криптовалюти", "en": "🪙 Crypto"},
    "menu.banks": {"ru": "🏦 Банки", "uk": "🏦 Банки", "en": "🏦 Banks"},
    "menu.compare": {"ru": "🔄 Сравнение цен", "uk": "🔄 Порівняння цін", "en": "🔄 Compare prices"},
    "menu.charts": {"ru": "📈 Графики", "uk": "📈 Графіки", "en": "📈 Charts"},
    "menu.alerts": {"ru": "🔔 Уведомления", "uk": "🔔 Сповіщення", "en": "🔔 Alerts"},
    "menu.arbitrage": {"ru": "⚡ Арбитраж", "uk": "⚡ Арбітраж", "en": "⚡ Arbitrage"},
    "menu.settings": {"ru": "⚙️ Настройки", "uk": "⚙️ Налаштування", "en": "⚙️ Settings"},
    "menu.title": {"ru": "🏠 <b>Главное меню</b>", "uk": "🏠 <b>Головне меню</b>", "en": "🏠 <b>Main menu</b>"},
    "btn.back": {"ru": "⬅️ Назад", "uk": "⬅️ Назад", "en": "⬅️ Back"},
    "btn.menu": {"ru": "🏠 Меню", "uk": "🏠 Меню", "en": "🏠 Menu"},
    "btn.refresh": {"ru": "🔄 Обновить", "uk": "🔄 Оновити", "en": "🔄 Refresh"},
    "btn.cancel": {"ru": "✖️ Отмена", "uk": "✖️ Скасувати", "en": "✖️ Cancel"},
    "start.text": {
        "ru": (
            "👋 Привет, <b>{name}</b>!\n\n"
            "Я слежу за курсами валют и криптовалют в реальном времени:\n"
            "🏦 Monobank, PrivatBank\n"
            "🪙 Binance, Bybit, OKX, Bitget, BingX, KuCoin\n\n"
            "Что я умею:\n"
            "• показывать актуальные курсы и сравнивать источники;\n"
            "• рисовать графики за 1 час, 24 часа, 7 и 30 дней;\n"
            "• уведомлять о цене, изменении и разнице между биржами;\n"
            "• искать потенциальные арбитражные ситуации (с учётом комиссий).\n\n"
            "Для начала выберите валюты и криптовалюты, за которыми следить 👇"
        ),
        "uk": (
            "👋 Привіт, <b>{name}</b>!\n\n"
            "Я стежу за курсами валют і криптовалют у реальному часі:\n"
            "🏦 Monobank, PrivatBank\n"
            "🪙 Binance, Bybit, OKX, Bitget, BingX, KuCoin\n\n"
            "Що я вмію:\n"
            "• показувати актуальні курси та порівнювати джерела;\n"
            "• малювати графіки за 1 годину, 24 години, 7 і 30 днів;\n"
            "• сповіщати про ціну, зміну та різницю між біржами;\n"
            "• шукати потенційні арбітражні ситуації (з урахуванням комісій).\n\n"
            "Для початку оберіть валюти та криптовалюти, за якими стежити 👇"
        ),
        "en": (
            "👋 Hi, <b>{name}</b>!\n\n"
            "I track currency and crypto rates in real time:\n"
            "🏦 Monobank, PrivatBank\n"
            "🪙 Binance, Bybit, OKX, Bitget, BingX, KuCoin\n\n"
            "What I can do:\n"
            "• show live rates and compare sources;\n"
            "• draw charts for 1 hour, 24 hours, 7 and 30 days;\n"
            "• alert you on price, change and cross-exchange gaps;\n"
            "• look for potential arbitrage (fees included).\n\n"
            "First, choose the currencies and coins to follow 👇"
        ),
    },
    "start.pick": {"ru": "✅ Выбрать активы", "uk": "✅ Обрати активи", "en": "✅ Choose assets"},
    "help.text": {
        "ru": (
            "<b>Команды</b>\n/start — меню\n/rates — все курсы\n/crypto — криптовалюты\n/banks — курсы банков\n"
            "/compare [пара] — сравнить источники\n/history [пара] [период] — график\n"
            "/alerts — уведомления\n/arbitrage — арбитраж\n/p2p — P2P\n/settings — настройки\n/help — справка"
        ),
        "uk": (
            "<b>Команди</b>\n/start — меню\n/rates — усі курси\n/crypto — криптовалюти\n/banks — курси банків\n"
            "/compare [пара] — порівняти джерела\n/history [пара] [період] — графік\n"
            "/alerts — сповіщення\n/arbitrage — арбітраж\n/p2p — P2P\n/settings — налаштування\n/help — довідка"
        ),
        "en": (
            "<b>Commands</b>\n/start — menu\n/rates — all rates\n/crypto — crypto\n/banks — bank rates\n"
            "/compare [pair] — compare sources\n/history [pair] [period] — chart\n"
            "/alerts — alerts\n/arbitrage — arbitrage\n/p2p — P2P\n/settings — settings\n/help — help"
        ),
    },
    "err.generic": {
        "ru": "⚠️ Что-то пошло не так. Попробуйте ещё раз чуть позже.",
        "uk": "⚠️ Щось пішло не так. Спробуйте ще раз трохи пізніше.",
        "en": "⚠️ Something went wrong. Please try again in a moment.",
    },
    "err.throttled": {"ru": "⏳ Не так быстро", "uk": "⏳ Не так швидко", "en": "⏳ Slow down a bit"},
    "err.unknown_symbol": {
        "ru": "❌ Пара «{symbol}» не отслеживается. Список доступных — в разделе «Настройки → Активы».",
        "uk": "❌ Пару «{symbol}» не відстежується. Список доступних — у розділі «Налаштування → Активи».",
        "en": "❌ Pair “{symbol}” is not tracked. See Settings → Assets for the available list.",
    },
    "err.invalid_number": {
        "ru": "❌ Введите число, например <code>{example}</code>.",
        "uk": "❌ Введіть число, наприклад <code>{example}</code>.",
        "en": "❌ Please enter a number, e.g. <code>{example}</code>.",
    },
    "err.out_of_range": {
        "ru": "❌ Допустимый диапазон: от {min} до {max}.",
        "uk": "❌ Допустимий діапазон: від {min} до {max}.",
        "en": "❌ Allowed range: {min} to {max}.",
    },
    "err.expired_button": {
        "ru": "Кнопка устарела, откройте меню заново",
        "uk": "Кнопка застаріла, відкрийте меню знову",
        "en": "This button is outdated, open the menu again",
    },
    # ------------------------------------------------------------ свежесть данных
    "warn.stale": {
        "ru": "⚠️ Данные устарели: {items}",
        "uk": "⚠️ Дані застаріли: {items}",
        "en": "⚠️ Stale data: {items}",
    },
    "warn.expired": {
        "ru": "⛔ Нет актуальных данных: {items}",
        "uk": "⛔ Немає актуальних даних: {items}",
        "en": "⛔ No up-to-date data: {items}",
    },
    "warn.no_data": {
        "ru": "⛔ По {symbol} нет актуальных данных: источники недоступны или ещё загружаются.",
        "uk": "⛔ По {symbol} немає актуальних даних: джерела недоступні або ще завантажуються.",
        "en": "⛔ No up-to-date data for {symbol}: sources are unavailable or still loading.",
    },
    "note.unlisted": {
        "ru": "ℹ️ Пара не торгуется на: {items}",
        "uk": "ℹ️ Пара не торгується на: {items}",
        "en": "ℹ️ Pair is not traded on: {items}",
    },
    "note.updated": {"ru": "🕒 Обновлено {time}", "uk": "🕒 Оновлено {time}", "en": "🕒 Updated {time}"},
    "note.fx": {
        "ru": "≈ Цены пересчитаны в {cur} по курсу {bank} (USDT принят за USD) — справочно.",
        "uk": "≈ Ціни перераховано в {cur} за курсом {bank} (USDT прийнято за USD) — довідково.",
        "en": "≈ Prices converted to {cur} at {bank} rate (USDT treated as USD) — indicative only.",
    },
    "note.fx_unavailable": {
        "ru": "⚠️ Курс для пересчёта в {cur} недоступен — показаны цены в USDT.",
        "uk": "⚠️ Курс для перерахунку в {cur} недоступний — показано ціни в USDT.",
        "en": "⚠️ No rate available to convert to {cur} — showing USDT prices.",
    },
    # ------------------------------------------------------------ курсы / крипто / банки
    "rates.title": {"ru": "📊 <b>Курсы</b>", "uk": "📊 <b>Курси</b>", "en": "📊 <b>Rates</b>"},
    "rates.banks": {
        "ru": "🏦 <b>Банки</b> · покупка / продажа",
        "uk": "🏦 <b>Банки</b> · купівля / продаж",
        "en": "🏦 <b>Banks</b> · buy / sell",
    },
    "rates.crypto": {
        "ru": "🪙 <b>Криптовалюты</b> · цена последней сделки",
        "uk": "🪙 <b>Криптовалюти</b> · ціна останньої угоди",
        "en": "🪙 <b>Crypto</b> · last trade price",
    },
    "rates.crypto_line": {
        "ru": "{symbol}: <b>{value}</b> · {sources}",
        "uk": "{symbol}: <b>{value}</b> · {sources}",
        "en": "{symbol}: <b>{value}</b> · {sources}",
    },
    "rates.sources_n": {"ru": "{n} бирж", "uk": "{n} бірж", "en": "{n} exchanges"},
    "rates.no_data_line": {
        "ru": "{symbol}: нет актуальных данных",
        "uk": "{symbol}: немає актуальних даних",
        "en": "{symbol}: no up-to-date data",
    },
    "rates.empty": {
        "ru": "Список отслеживаемых активов пуст. Добавьте активы в «Настройки → Активы».",
        "uk": "Список відстежуваних активів порожній. Додайте активи в «Налаштування → Активи».",
        "en": "Your watchlist is empty. Add assets in Settings → Assets.",
    },
    "banks.title": {"ru": "🏦 <b>Курсы банков</b>", "uk": "🏦 <b>Курси банків</b>", "en": "🏦 <b>Bank rates</b>"},
    "banks.rate_line": {
        "ru": "{bank}: покупка <b>{buy}</b> · продажа <b>{sell}</b> · спред {spread}",
        "uk": "{bank}: купівля <b>{buy}</b> · продаж <b>{sell}</b> · спред {spread}",
        "en": "{bank}: buy <b>{buy}</b> · sell <b>{sell}</b> · spread {spread}",
    },
    "banks.time_line": {
        "ru": "   ⏱ котировка банка: {quote_time} · получено {age} назад",
        "uk": "   ⏱ котирування банку: {quote_time} · отримано {age} тому",
        "en": "   ⏱ bank quote time: {quote_time} · fetched {age} ago",
    },
    "banks.no_quote_time": {
        "ru": "не предоставляется API банка",
        "uk": "не надається API банку",
        "en": "not provided by the bank API",
    },
    "banks.cross_line": {
        "ru": "{bank}: кросс-курс <b>{cross}</b> (покупка/продажа в API недоступны)",
        "uk": "{bank}: крос-курс <b>{cross}</b> (купівля/продаж в API недоступні)",
        "en": "{bank}: cross rate <b>{cross}</b> (buy/sell not provided by the API)",
    },
    "banks.missing_line": {
        "ru": "{bank}: нет данных по этой паре",
        "uk": "{bank}: немає даних по цій парі",
        "en": "{bank}: no data for this pair",
    },
    "banks.best_sell": {
        "ru": "💱 Продать валюту выгоднее: <b>{bank}</b> ({rate})",
        "uk": "💱 Продати валюту вигідніше: <b>{bank}</b> ({rate})",
        "en": "💱 Best place to sell: <b>{bank}</b> ({rate})",
    },
    "banks.best_buy": {
        "ru": "💱 Купить валюту выгоднее: <b>{bank}</b> ({rate})",
        "uk": "💱 Купити валюту вигідніше: <b>{bank}</b> ({rate})",
        "en": "💱 Best place to buy: <b>{bank}</b> ({rate})",
    },
    "banks.legend": {
        "ru": "Покупка — курс, по которому банк покупает валюту у вас; продажа — курс, по которому банк её продаёт.",
        "uk": "Купівля — курс, за яким банк купує валюту у вас; продаж — курс, за яким банк її продає.",
        "en": "Buy is the rate at which the bank buys currency from you; sell is the rate at which it sells to you.",
    },
    "banks.empty": {
        "ru": "В списке нет валютных пар. Добавьте их в «Настройки → Активы».",
        "uk": "У списку немає валютних пар. Додайте їх у «Налаштування → Активи».",
        "en": "No currency pairs in your watchlist. Add them in Settings → Assets.",
    },
    "crypto.pick": {
        "ru": "🪙 <b>Криптовалюты</b>\nВыберите пару для подробностей:",
        "uk": "🪙 <b>Криптовалюти</b>\nОберіть пару для подробиць:",
        "en": "🪙 <b>Crypto</b>\nPick a pair for details:",
    },
    "crypto.title": {"ru": "🪙 <b>{symbol}</b>", "uk": "🪙 <b>{symbol}</b>", "en": "🪙 <b>{symbol}</b>"},
    "crypto.row": {
        "ru": "<b>{source}</b> {icon} <b>{last}</b>\n   bid {bid} · ask {ask} · спред {spread}\n   объём 24ч {volume} · {age} назад",
        "uk": "<b>{source}</b> {icon} <b>{last}</b>\n   bid {bid} · ask {ask} · спред {spread}\n   обсяг 24г {volume} · {age} тому",
        "en": "<b>{source}</b> {icon} <b>{last}</b>\n   bid {bid} · ask {ask} · spread {spread}\n   24h volume {volume} · {age} ago",
    },
    "crypto.legend": {
        "ru": "last — цена последней сделки; bid/ask — лучшие цены в стакане (это разные показатели).",
        "uk": "last — ціна останньої угоди; bid/ask — найкращі ціни в стакані (це різні показники).",
        "en": "last is the last trade price; bid/ask are the best order-book prices (different things).",
    },
    "crypto.no_book": {"ru": "нет стакана", "uk": "немає стакана", "en": "no order book"},
    # ------------------------------------------------------------ сравнение
    "compare.pick": {
        "ru": "🔄 <b>Сравнение цен</b>\nВыберите актив:",
        "uk": "🔄 <b>Порівняння цін</b>\nОберіть актив:",
        "en": "🔄 <b>Price comparison</b>\nPick an asset:",
    },
    "compare.title": {
        "ru": "🔄 <b>{symbol}</b> — {metric}",
        "uk": "🔄 <b>{symbol}</b> — {metric}",
        "en": "🔄 <b>{symbol}</b> — {metric}",
    },
    "compare.row": {
        "ru": "{n}. <b>{source}</b> {icon} {value} · {age} назад",
        "uk": "{n}. <b>{source}</b> {icon} {value} · {age} тому",
        "en": "{n}. <b>{source}</b> {icon} {value} · {age} ago",
    },
    "compare.lowest": {
        "ru": "📉 Минимум: <b>{source}</b> — {value}",
        "uk": "📉 Мінімум: <b>{source}</b> — {value}",
        "en": "📉 Lowest: <b>{source}</b> — {value}",
    },
    "compare.highest": {
        "ru": "📈 Максимум: <b>{source}</b> — {value}",
        "uk": "📈 Максимум: <b>{source}</b> — {value}",
        "en": "📈 Highest: <b>{source}</b> — {value}",
    },
    "compare.diff": {
        "ru": "↔️ Разница: <b>{abs}</b> ({pct})",
        "uk": "↔️ Різниця: <b>{abs}</b> ({pct})",
        "en": "↔️ Difference: <b>{abs}</b> ({pct})",
    },
    "compare.need_two": {
        "ru": "Для сравнения нужно минимум два источника с актуальными данными.",
        "uk": "Для порівняння потрібно щонайменше два джерела з актуальними даними.",
        "en": "At least two sources with up-to-date data are needed to compare.",
    },
    "compare.without_metric": {
        "ru": "ℹ️ Нет этого показателя у: {items}",
        "uk": "ℹ️ Немає цього показника у: {items}",
        "en": "ℹ️ Metric not provided by: {items}",
    },
    "compare.bank_title": {
        "ru": "🔄 <b>{symbol}</b> — сравнение банков",
        "uk": "🔄 <b>{symbol}</b> — порівняння банків",
        "en": "🔄 <b>{symbol}</b> — bank comparison",
    },
    "compare.bank_sell_hdr": {
        "ru": "Вы продаёте валюту (курс покупки банком), лучшие сверху:",
        "uk": "Ви продаєте валюту (курс купівлі банком), найкращі зверху:",
        "en": "You sell currency (bank buy rate), best first:",
    },
    "compare.bank_buy_hdr": {
        "ru": "Вы покупаете валюту (курс продажи банком), лучшие сверху:",
        "uk": "Ви купуєте валюту (курс продажу банком), найкращі зверху:",
        "en": "You buy currency (bank sell rate), best first:",
    },
    "metric.last": {"ru": "последняя цена сделки", "uk": "ціна останньої угоди", "en": "last trade price"},
    "metric.bid": {"ru": "лучший bid (покупка)", "uk": "найкращий bid (купівля)", "en": "best bid"},
    "metric.ask": {"ru": "лучший ask (продажа)", "uk": "найкращий ask (продаж)", "en": "best ask"},
    "metric.btn_last": {"ru": "Last", "uk": "Last", "en": "Last"},
    "metric.btn_bid": {"ru": "Bid", "uk": "Bid", "en": "Bid"},
    "metric.btn_ask": {"ru": "Ask", "uk": "Ask", "en": "Ask"},
    # ------------------------------------------------------------ графики
    "charts.pick": {
        "ru": "📈 <b>Графики</b>\nВыберите актив:",
        "uk": "📈 <b>Графіки</b>\nОберіть актив:",
        "en": "📈 <b>Charts</b>\nPick an asset:",
    },
    "charts.pick_period": {
        "ru": "📈 <b>{symbol}</b>\nВыберите период:",
        "uk": "📈 <b>{symbol}</b>\nОберіть період:",
        "en": "📈 <b>{symbol}</b>\nPick a period:",
    },
    "charts.caption": {
        "ru": "<b>{symbol}</b> · {source} · {period}\nМин {min} · Макс {max} · Сейчас {now}\nИзменение за период: {change}",
        "uk": "<b>{symbol}</b> · {source} · {period}\nМін {min} · Макс {max} · Зараз {now}\nЗміна за період: {change}",
        "en": "<b>{symbol}</b> · {source} · {period}\nMin {min} · Max {max} · Now {now}\nChange over period: {change}",
    },
    "charts.partial": {
        "ru": "ℹ️ История накоплена только за {span} из {period}.",
        "uk": "ℹ️ Історія накопичена лише за {span} з {period}.",
        "en": "ℹ️ History covers only {span} of the requested {period}.",
    },
    "charts.no_data": {
        "ru": "📭 Истории по <b>{symbol}</b> ({source}) за этот период пока недостаточно — бот накапливает данные. Выберите период короче или повторите позже.",
        "uk": "📭 Історії по <b>{symbol}</b> ({source}) за цей період поки недостатньо — бот накопичує дані. Оберіть коротший період або повторіть пізніше.",
        "en": "📭 Not enough history for <b>{symbol}</b> ({source}) in this period yet — the bot is still collecting data. Try a shorter period or come back later.",
    },
    "charts.rendering": {"ru": "Рисую график…", "uk": "Малюю графік…", "en": "Drawing the chart…"},
    "period.1h": {"ru": "1 час", "uk": "1 година", "en": "1 hour"},
    "period.24h": {"ru": "24 часа", "uk": "24 години", "en": "24 hours"},
    "period.7d": {"ru": "7 дней", "uk": "7 днів", "en": "7 days"},
    "period.30d": {"ru": "30 дней", "uk": "30 днів", "en": "30 days"},
    # ------------------------------------------------------------ уведомления (меню)
    "alerts.title": {"ru": "🔔 <b>Уведомления</b>", "uk": "🔔 <b>Сповіщення</b>", "en": "🔔 <b>Alerts</b>"},
    "alerts.empty": {
        "ru": "У вас пока нет уведомлений. Нажмите «Создать», чтобы добавить первое.",
        "uk": "У вас поки немає сповіщень. Натисніть «Створити», щоб додати перше.",
        "en": "You have no alerts yet. Tap “Create” to add your first one.",
    },
    "alerts.muted_until": {
        "ru": "🔕 Сигналы отключены до {time}",
        "uk": "🔕 Сигнали вимкнено до {time}",
        "en": "🔕 Alerts muted until {time}",
    },
    "alerts.active_line": {"ru": "{n}. {icon} {desc}", "uk": "{n}. {icon} {desc}", "en": "{n}. {icon} {desc}"},
    "alerts.create": {"ru": "➕ Создать", "uk": "➕ Створити", "en": "➕ Create"},
    "alerts.history": {"ru": "🕘 История", "uk": "🕘 Історія", "en": "🕘 History"},
    "alerts.mute": {"ru": "🔕 Отключить на {h} ч", "uk": "🔕 Вимкнути на {h} г", "en": "🔕 Mute {h}h"},
    "alerts.unmute": {"ru": "🔔 Включить сигналы", "uk": "🔔 Увімкнути сигнали", "en": "🔔 Unmute"},
    "alerts.history_title": {
        "ru": "🕘 <b>Последние срабатывания</b>",
        "uk": "🕘 <b>Останні спрацювання</b>",
        "en": "🕘 <b>Recent triggers</b>",
    },
    "alerts.history_empty": {"ru": "Срабатываний ещё не было.", "uk": "Спрацювань ще не було.", "en": "No triggers yet."},
    "alerts.type_prompt": {
        "ru": "Какое уведомление создать?",
        "uk": "Яке сповіщення створити?",
        "en": "Which alert do you want to create?",
    },
    "alerts.type.price_above": {"ru": "⬆️ Цена выше", "uk": "⬆️ Ціна вище", "en": "⬆️ Price above"},
    "alerts.type.price_below": {"ru": "⬇️ Цена ниже", "uk": "⬇️ Ціна нижче", "en": "⬇️ Price below"},
    "alerts.type.pct_change": {"ru": "📊 Изменение на %", "uk": "📊 Зміна на %", "en": "📊 Change by %"},
    "alerts.type.spread": {
        "ru": "↔️ Разница между биржами",
        "uk": "↔️ Різниця між біржами",
        "en": "↔️ Gap between exchanges",
    },
    "alerts.type.arbitrage": {
        "ru": "⚡ Арбитраж (мин. %)",
        "uk": "⚡ Арбітраж (мін. %)",
        "en": "⚡ Arbitrage (min %)",
    },
    "alerts.pick_asset": {"ru": "Выберите актив:", "uk": "Оберіть актив:", "en": "Pick an asset:"},
    "alerts.pick_source": {
        "ru": "Выберите источник цены для <b>{symbol}</b>:",
        "uk": "Оберіть джерело ціни для <b>{symbol}</b>:",
        "en": "Pick the price source for <b>{symbol}</b>:",
    },
    "alerts.pick_window": {
        "ru": "За какой период отслеживать изменение?",
        "uk": "За який період відстежувати зміну?",
        "en": "Over which period should the change be tracked?",
    },
    "alerts.window": {"ru": "{m} мин", "uk": "{m} хв", "en": "{m} min"},
    "alerts.window_h": {"ru": "{h} ч", "uk": "{h} г", "en": "{h} h"},
    "alerts.enter_price": {
        "ru": "Введите цену для <b>{symbol}</b> ({source}), например <code>{example}</code>.\nСейчас: {now}",
        "uk": "Введіть ціну для <b>{symbol}</b> ({source}), наприклад <code>{example}</code>.\nЗараз: {now}",
        "en": "Enter the price for <b>{symbol}</b> ({source}), e.g. <code>{example}</code>.\nNow: {now}",
    },
    "alerts.enter_pct": {
        "ru": "Введите процент (например <code>{example}</code>):",
        "uk": "Введіть відсоток (наприклад <code>{example}</code>):",
        "en": "Enter the percentage (e.g. <code>{example}</code>):",
    },
    "alerts.created": {
        "ru": "✅ Уведомление создано:\n{desc}\n\nПовторные сигналы подавляются: следующее придёт не раньше чем через {cooldown} мин и только после возврата условия в норму.",
        "uk": "✅ Сповіщення створено:\n{desc}\n\nПовторні сигнали придушуються: наступне прийде не раніше ніж через {cooldown} хв і лише після повернення умови в норму.",
        "en": "✅ Alert created:\n{desc}\n\nRepeats are suppressed: the next one arrives no sooner than {cooldown} min and only after the condition has reset.",
    },
    "alerts.limit": {
        "ru": "❌ Достигнут лимит уведомлений ({n}). Удалите ненужные.",
        "uk": "❌ Досягнуто ліміт сповіщень ({n}). Видаліть непотрібні.",
        "en": "❌ Alert limit reached ({n}). Delete some first.",
    },
    "alerts.deleted": {"ru": "🗑 Удалено", "uk": "🗑 Видалено", "en": "🗑 Deleted"},
    "alerts.not_found": {"ru": "Уведомление не найдено", "uk": "Сповіщення не знайдено", "en": "Alert not found"},
    "alerts.desc.price_above": {
        "ru": "{symbol} · {source} выше {value}",
        "uk": "{symbol} · {source} вище {value}",
        "en": "{symbol} · {source} above {value}",
    },
    "alerts.desc.price_below": {
        "ru": "{symbol} · {source} ниже {value}",
        "uk": "{symbol} · {source} нижче {value}",
        "en": "{symbol} · {source} below {value}",
    },
    "alerts.desc.pct_change": {
        "ru": "{symbol} · {source} изменение ≥ {value} за {window}",
        "uk": "{symbol} · {source} зміна ≥ {value} за {window}",
        "en": "{symbol} · {source} change ≥ {value} in {window}",
    },
    "alerts.desc.spread": {
        "ru": "{symbol} · разница между биржами ≥ {value}",
        "uk": "{symbol} · різниця між біржами ≥ {value}",
        "en": "{symbol} · gap between exchanges ≥ {value}",
    },
    "alerts.desc.arbitrage": {
        "ru": "{symbol} · арбитраж после издержек ≥ {value}",
        "uk": "{symbol} · арбітраж після витрат ≥ {value}",
        "en": "{symbol} · arbitrage after costs ≥ {value}",
    },
    # ------------------------------------------------------------ тексты срабатываний
    "fire.price_above": {
        "ru": "🔔 <b>{symbol}</b> на {source} достиг <b>{price}</b> (порог: выше {threshold})",
        "uk": "🔔 <b>{symbol}</b> на {source} досяг <b>{price}</b> (поріг: вище {threshold})",
        "en": "🔔 <b>{symbol}</b> on {source} reached <b>{price}</b> (threshold: above {threshold})",
    },
    "fire.price_below": {
        "ru": "🔔 <b>{symbol}</b> на {source} опустился до <b>{price}</b> (порог: ниже {threshold})",
        "uk": "🔔 <b>{symbol}</b> на {source} опустився до <b>{price}</b> (поріг: нижче {threshold})",
        "en": "🔔 <b>{symbol}</b> on {source} fell to <b>{price}</b> (threshold: below {threshold})",
    },
    "fire.pct_change": {
        "ru": "🔔 <b>{symbol}</b> на {source} изменился на <b>{change}</b> за {window} (было {old}, сейчас {price})",
        "uk": "🔔 <b>{symbol}</b> на {source} змінився на <b>{change}</b> за {window} (було {old}, зараз {price})",
        "en": "🔔 <b>{symbol}</b> on {source} changed by <b>{change}</b> in {window} (was {old}, now {price})",
    },
    "fire.spread": {
        "ru": "🔔 Обнаружена разница между {low_source} и {high_source}: <b>{pct}</b> по {symbol} ({low} → {high})",
        "uk": "🔔 Виявлено різницю між {low_source} і {high_source}: <b>{pct}</b> по {symbol} ({low} → {high})",
        "en": "🔔 Gap detected between {low_source} and {high_source}: <b>{pct}</b> on {symbol} ({low} → {high})",
    },
    "fire.arbitrage": {
        "ru": (
            "⚡ <b>{symbol}</b>: потенциальная разница\n"
            "Купить: {buy_source} по {buy_price}\nПродать: {sell_source} по {sell_price}\n"
            "До издержек: <b>{gross}</b> · после комиссий, проскальзывания и вывода: <b>{net}</b>\n"
            "⚠️ Это оценка по лучшим ценам стакана, а не гарантированная прибыль."
        ),
        "uk": (
            "⚡ <b>{symbol}</b>: потенційна різниця\n"
            "Купити: {buy_source} за {buy_price}\nПродати: {sell_source} за {sell_price}\n"
            "До витрат: <b>{gross}</b> · після комісій, прослизання та виводу: <b>{net}</b>\n"
            "⚠️ Це оцінка за найкращими цінами стакана, а не гарантований прибуток."
        ),
        "en": (
            "⚡ <b>{symbol}</b>: potential gap\n"
            "Buy: {buy_source} at {buy_price}\nSell: {sell_source} at {sell_price}\n"
            "Before costs: <b>{gross}</b> · after fees, slippage and withdrawal: <b>{net}</b>\n"
            "⚠️ This is an estimate from top-of-book prices, not guaranteed profit."
        ),
    },
    # ------------------------------------------------------------ арбитраж
    "arb.title": {"ru": "⚡ <b>Арбитражный мониторинг</b>", "uk": "⚡ <b>Арбітражний моніторинг</b>", "en": "⚡ <b>Arbitrage monitor</b>"},
    "arb.threshold": {
        "ru": "Порог сигнала: <b>{pct}</b> чистыми (после комиссий, проскальзывания и вывода). Условная сделка: {size} USDT.",
        "uk": "Поріг сигналу: <b>{pct}</b> чистими (після комісій, прослизання та виводу). Умовна угода: {size} USDT.",
        "en": "Signal threshold: <b>{pct}</b> net (after fees, slippage and withdrawal). Assumed trade: {size} USDT.",
    },
    "arb.signals": {"ru": "✅ Сигналы выше порога:", "uk": "✅ Сигнали вище порога:", "en": "✅ Signals above threshold:"},
    "arb.none": {
        "ru": "Сигналов выше порога сейчас нет. Лучшие варианты (ниже порога):",
        "uk": "Сигналів вище порога зараз немає. Найкращі варіанти (нижче порога):",
        "en": "No signals above the threshold right now. Best candidates (below threshold):",
    },
    "arb.no_data": {
        "ru": "Недостаточно свежих данных: для арбитража нужны минимум две биржи с актуальными ценами.",
        "uk": "Недостатньо свіжих даних: для арбітражу потрібні щонайменше дві біржі з актуальними цінами.",
        "en": "Not enough fresh data: arbitrage needs at least two exchanges with up-to-date prices.",
    },
    "arb.item": {
        "ru": (
            "<b>{symbol}</b>: купить <b>{buy_source}</b> {buy_price} → продать <b>{sell_source}</b> {sell_price}\n"
            "   до издержек {gross} · после издержек <b>{net}</b> ({net_profit} USDT)\n"
            "   без перевода (балансы заранее): {net_pre} · объём по лучшим ценам: {volume}"
        ),
        "uk": (
            "<b>{symbol}</b>: купити <b>{buy_source}</b> {buy_price} → продати <b>{sell_source}</b> {sell_price}\n"
            "   до витрат {gross} · після витрат <b>{net}</b> ({net_profit} USDT)\n"
            "   без переказу (баланси заздалегідь): {net_pre} · обсяг за найкращими цінами: {volume}"
        ),
        "en": (
            "<b>{symbol}</b>: buy <b>{buy_source}</b> {buy_price} → sell <b>{sell_source}</b> {sell_price}\n"
            "   before costs {gross} · after costs <b>{net}</b> ({net_profit} USDT)\n"
            "   without transfer (pre-funded): {net_pre} · top-of-book volume: {volume}"
        ),
    },
    "arb.disclaimer": {
        "ru": (
            "⚠️ <b>Это не гарантированная прибыль.</b> Расчёт по лучшим ценам стакана; реальный результат зависит от "
            "глубины стакана, исполнения ордеров, скорости перевода, лимитов и статуса ввода/вывода на биржах. "
            "Комиссии — оценочные значения из настроек бота, а не живые данные бирж."
        ),
        "uk": (
            "⚠️ <b>Це не гарантований прибуток.</b> Розрахунок за найкращими цінами стакана; реальний результат залежить "
            "від глибини стакана, виконання ордерів, швидкості переказу, лімітів і статусу вводу/виводу на біржах. "
            "Комісії — орієнтовні значення з налаштувань бота, а не живі дані бірж."
        ),
        "en": (
            "⚠️ <b>This is not guaranteed profit.</b> Calculated from top-of-book prices; real results depend on order-book "
            "depth, order execution, transfer speed, limits and deposit/withdrawal status. "
            "Fees are estimates from the bot settings, not live exchange data."
        ),
    },
    "arb.detail": {
        "ru": (
            "⚡ <b>{symbol}</b>: {buy_source} → {sell_source}\n\n"
            "Объём: {qty} {base} ≈ {cost} USDT{limit}\n"
            "Валовая разница котировок: {gross} ({gross_profit} USDT)\n"
            "− комиссии торговли: {fees} USDT\n− проскальзывание: {slip} USDT\n− вывод монеты: {withdraw} USDT\n"
            "= <b>итого: {net_profit} USDT ({net})</b>\n"
            "Без перевода (балансы заранее): {net_pre_profit} USDT ({net_pre})"
        ),
        "uk": (
            "⚡ <b>{symbol}</b>: {buy_source} → {sell_source}\n\n"
            "Обсяг: {qty} {base} ≈ {cost} USDT{limit}\n"
            "Валова різниця котирувань: {gross} ({gross_profit} USDT)\n"
            "− комісії торгівлі: {fees} USDT\n− прослизання: {slip} USDT\n− вивід монети: {withdraw} USDT\n"
            "= <b>разом: {net_profit} USDT ({net})</b>\n"
            "Без переказу (баланси заздалегідь): {net_pre_profit} USDT ({net_pre})"
        ),
        "en": (
            "⚡ <b>{symbol}</b>: {buy_source} → {sell_source}\n\n"
            "Size: {qty} {base} ≈ {cost} USDT{limit}\n"
            "Gross quote difference: {gross} ({gross_profit} USDT)\n"
            "− trading fees: {fees} USDT\n− slippage: {slip} USDT\n− coin withdrawal: {withdraw} USDT\n"
            "= <b>total: {net_profit} USDT ({net})</b>\n"
            "Without transfer (pre-funded): {net_pre_profit} USDT ({net_pre})"
        ),
    },
    "arb.limit_note": {
        "ru": " (ограничено ликвидностью лучшей цены)",
        "uk": " (обмежено ліквідністю найкращої ціни)",
        "en": " (limited by top-of-book liquidity)",
    },
    "arb.liq_unknown": {
        "ru": "объём неизвестен",
        "uk": "обсяг невідомий",
        "en": "volume unknown",
    },
    "arb.set_threshold": {"ru": "⚙️ Порог", "uk": "⚙️ Поріг", "en": "⚙️ Threshold"},
    "arb.threshold_prompt": {
        "ru": "Выберите минимальный чистый процент для показа сигналов:",
        "uk": "Оберіть мінімальний чистий відсоток для показу сигналів:",
        "en": "Pick the minimum net percentage for showing signals:",
    },
    # ------------------------------------------------------------ настройки
    "settings.title": {"ru": "⚙️ <b>Настройки</b>", "uk": "⚙️ <b>Налаштування</b>", "en": "⚙️ <b>Settings</b>"},
    "settings.summary": {
        "ru": "Язык: {language}\nВалюта отображения: {cur}\nЧастота уведомлений: не чаще раза в {interval}\nГрафики: период {period}, тема {theme}\nПорог арбитража: {arb}\nАктивов в списке: {assets}",
        "uk": "Мова: {language}\nВалюта відображення: {cur}\nЧастота сповіщень: не частіше ніж раз на {interval}\nГрафіки: період {period}, тема {theme}\nПоріг арбітражу: {arb}\nАктивів у списку: {assets}",
        "en": "Language: {language}\nDisplay currency: {cur}\nAlert frequency: at most once per {interval}\nCharts: period {period}, theme {theme}\nArbitrage threshold: {arb}\nAssets in list: {assets}",
    },
    "settings.lang": {"ru": "🌐 Язык", "uk": "🌐 Мова", "en": "🌐 Language"},
    "settings.assets": {"ru": "🎯 Активы", "uk": "🎯 Активи", "en": "🎯 Assets"},
    "settings.interval": {"ru": "⏱ Частота уведомлений", "uk": "⏱ Частота сповіщень", "en": "⏱ Alert frequency"},
    "settings.currency": {"ru": "💱 Валюта отображения", "uk": "💱 Валюта відображення", "en": "💱 Display currency"},
    "settings.charts": {"ru": "📈 Графики", "uk": "📈 Графіки", "en": "📈 Charts"},
    "settings.arb": {"ru": "⚡ Порог арбитража", "uk": "⚡ Поріг арбітражу", "en": "⚡ Arbitrage threshold"},
    "settings.lang_prompt": {"ru": "Выберите язык интерфейса:", "uk": "Оберіть мову інтерфейсу:", "en": "Choose the interface language:"},
    "settings.assets_prompt": {
        "ru": "🎯 <b>Отслеживаемые активы</b>\nНажимайте, чтобы включить ✅ или выключить ▫️:",
        "uk": "🎯 <b>Відстежувані активи</b>\nНатискайте, щоб увімкнути ✅ або вимкнути ▫️:",
        "en": "🎯 <b>Tracked assets</b>\nTap to switch on ✅ or off ▫️:",
    },
    "settings.interval_prompt": {
        "ru": "Как часто можно присылать уведомления по одному условию? (минимальный интервал между повторами)",
        "uk": "Як часто можна надсилати сповіщення за однією умовою? (мінімальний інтервал між повторами)",
        "en": "How often may the same alert repeat? (minimum interval between repeats)",
    },
    "settings.currency_prompt": {
        "ru": "В какой валюте показывать цены криптовалют? Пересчёт ориентировочный: по курсу банка, USDT принимается за USD.",
        "uk": "У якій валюті показувати ціни криптовалют? Перерахунок орієнтовний: за курсом банку, USDT приймається за USD.",
        "en": "Which currency should crypto prices be shown in? Conversion is indicative: bank rate, USDT treated as USD.",
    },
    "settings.charts_prompt": {
        "ru": "Настройки графиков:\nПериод по умолчанию: <b>{period}</b>\nТема: <b>{theme}</b>",
        "uk": "Налаштування графіків:\nПеріод за замовчуванням: <b>{period}</b>\nТема: <b>{theme}</b>",
        "en": "Chart settings:\nDefault period: <b>{period}</b>\nTheme: <b>{theme}</b>",
    },
    "settings.arb_prompt": {
        "ru": "Минимальный чистый процент для арбитражных сигналов (после издержек):",
        "uk": "Мінімальний чистий відсоток для арбітражних сигналів (після витрат):",
        "en": "Minimum net percentage for arbitrage signals (after costs):",
    },
    "settings.theme.dark": {"ru": "🌙 Тёмная", "uk": "🌙 Темна", "en": "🌙 Dark"},
    "settings.theme.light": {"ru": "☀️ Светлая", "uk": "☀️ Світла", "en": "☀️ Light"},
    "settings.saved": {"ru": "✅ Сохранено", "uk": "✅ Збережено", "en": "✅ Saved"},
    "settings.interval_opt": {"ru": "{m} мин", "uk": "{m} хв", "en": "{m} min"},
    "settings.interval_hour": {"ru": "1 час", "uk": "1 година", "en": "1 hour"},
    "settings.assets_crypto": {"ru": "🪙 Криптовалюты", "uk": "🪙 Криптовалюти", "en": "🪙 Crypto"},
    "settings.assets_fiat": {"ru": "💵 Валюты", "uk": "💵 Валюти", "en": "💵 Currencies"},
    "settings.assets_done": {"ru": "✅ Готово", "uk": "✅ Готово", "en": "✅ Done"},
}


def t(lang: str, key: str, **kwargs: Any) -> str:
    entry = TEXTS.get(key)
    if entry is None:
        return key
    template = entry.get(lang) or entry[DEFAULT_LANG]
    try:
        return template.format(**kwargs) if kwargs else template
    except (KeyError, IndexError):
        return template


def normalize_lang(code: str | None, default: str = DEFAULT_LANG) -> str:
    if not code:
        return default
    short = code.lower().split("-")[0]
    return short if short in LANGUAGES else default

from app.i18n_p2p import P2P_TEXTS  # noqa: E402

TEXTS.update(P2P_TEXTS)
