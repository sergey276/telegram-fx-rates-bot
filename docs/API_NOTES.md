# Анализ API источников

Все эндпоинты ниже **проверены живыми запросами** (REST — `curl`, WebSocket — скрипт на aiohttp) перед реализацией.
Используются только публичные методы без авторизации и без API-ключей.

## Банки

| Источник | Эндпоинт | Покупка / продажа | Время котировки | Ограничения |
|---|---|---|---|---|
| Monobank | `GET https://api.monobank.ua/bank/currency` | `rateBuy` / `rateSell` | `date` (unix, сек) | данные обновляются не чаще раза в 5 минут; запрос чаще раза в минуту → HTTP 429 |
| PrivatBank | `GET https://api.privatbank.ua/p24api/pubinfo?exchange&coursid=5` | `buy` / `sale` | **отсутствует** | `coursid=5` — наличный курс в отделениях, `coursid=11` — безналичный (карты). Отдаёт только USD и EUR |

Особенности:

* Monobank кодирует валюты числами ISO 4217 (`840` = USD, `980` = UAH). Часть записей (GBP/UAH и др.) содержит
  только `rateCross` без `rateBuy`/`rateSell`. Бот **не выдумывает** покупку/продажу для таких пар, а показывает
  кросс-курс и явно пишет, что покупка/продажа недоступны.
* Поле `date` Monobank у разных пар может отличаться на часы (курс не менялся) — это не признак устаревания данных.
  Свежесть считается по времени **последнего успешного запроса**, а время котировки показывается отдельно.
* PrivatBank не возвращает время котировки. Бот показывает «время котировки недоступно» и использует время получения.

## Криптобиржи (spot)

REST (по одной паре — массовые эндпоинты тяжёлые: 6–11 секунд на OKX/KuCoin/Bitget):

| Биржа | Эндпоинт | bid / ask (+ объёмы) | last | Объём 24ч |
|---|---|---|---|---|
| Binance | `GET /api/v3/ticker/24hr?symbol=BTCUSDT` | `bidPrice/bidQty`, `askPrice/askQty` | `lastPrice` | `volume` (base), `quoteVolume` |
| Bybit | `GET /v5/market/tickers?category=spot&symbol=BTCUSDT` | `bid1Price/bid1Size`, `ask1Price/ask1Size` | `lastPrice` | `volume24h`, `turnover24h` |
| OKX | `GET /api/v5/market/ticker?instId=BTC-USDT` | `bidPx/bidSz`, `askPx/askSz` | `last` | `vol24h`, `volCcy24h` |
| Bitget | `GET /api/v2/spot/market/tickers?symbol=BTCUSDT` | `bidPr/bidSz`, `askPr/askSz` | `lastPr` | `baseVolume`, `quoteVolume` |
| KuCoin | `GET /api/v1/market/orderbook/level1?symbol=BTC-USDT` + `GET /api/v1/market/stats?symbol=BTC-USDT` | `bestBid/bestBidSize`, `bestAsk/bestAskSize` | `price` | `vol`, `volValue` (stats) |
| BingX | `GET /openApi/spot/v1/ticker/24hr?symbol=BTC-USDT&timestamp=<ms>` | `bidPrice/bidQty`, `askPrice/askQty` | `lastPrice` | `volume`, `quoteVolume` |

Базовые URL: `https://api.binance.com`, `https://api.bybit.com`, `https://www.okx.com`, `https://api.bitget.com`,
`https://api.kucoin.com`, `https://open-api.bingx.com`. Все переопределяются через `.env`
(например, `BINANCE_REST_URL=https://data-api.binance.vision` при гео-блокировке).

WebSocket:

| Биржа | URL | Подписка | Keep-alive | Примечание |
|---|---|---|---|---|
| Binance | `wss://stream.binance.com:9443/stream?streams=btcusdt@ticker/...` | в URL | ping-фреймы (aiohttp отвечает сам) | `@ticker` содержит `b,B,a,A,c,v,q`; соединение сбрасывается раз в 24 ч |
| Bybit | `wss://stream.bybit.com/v5/public/spot` | `{"op":"subscribe","args":["tickers.BTCUSDT","orderbook.1.BTCUSDT"]}` | `{"op":"ping"}` каждые 20 с | **`tickers` в spot НЕ содержит bid/ask** — они берутся из `orderbook.1` |
| OKX | `wss://ws.okx.com/ws/v5/public` (порт 443; 8443 выводится из эксплуатации) | `{"op":"subscribe","args":[{"channel":"tickers","instId":"BTC-USDT"}]}` | текст `ping` → `pong` | |
| Bitget | `wss://ws.bitget.com/v2/ws/public` | `{"op":"subscribe","args":[{"instType":"SPOT","channel":"ticker","instId":"BTCUSDT"}]}` | текст `ping` → `pong` каждые 30 с | |
| KuCoin | URL и токен из `POST /api/v1/bullet-public` | `{"id":..,"type":"subscribe","topic":"/market/ticker:BTC-USDT"}` | `{"id":..,"type":"ping"}` по `pingInterval` | в потоке нет объёма — берётся из REST |
| BingX | `wss://open-api-ws.bingx.com/market` | `{"id":..,"reqType":"sub","dataType":"BTC-USDT@bookTicker"}` и `@lastPrice` | сервер шлёт `Ping` → ответить `Pong` | **все сообщения сжаты gzip** (binary); объёма в потоке нет |

## Проверенные ограничения

* **TON/USDT** на момент проверки есть только на Binance (и там без bid/ask — нулевые значения). На Bybit, OKX, Bitget,
  KuCoin, BingX пара не найдена (`Not supported symbols`, `51001`, `40034`, `data: null`, `100204`). Бот обрабатывает
  такие ответы как «пара не торгуется на бирже», а нулевые bid/ask — как отсутствие стакана, и не сравнивает их.
* Остальные популярные пары (ETH, SOL, XRP, BNB, DOGE, ADA, TRX, LTC, AVAX, LINK, DOT, POL, SHIB, NEAR, ATOM)
  найдены на всех шести биржах.
* Комиссии за вывод публичными методами без авторизации получить нельзя (нужен подписанный запрос). Поэтому
  комиссии торговли и вывода в арбитражном модуле — **настраиваемые оценки**, а не живые данные биржи.
* Binance и Bybit могут быть недоступны с IP некоторых стран (HTTP 403/451). Бот продолжает работать с остальными
  источниками и показывает причину в `/sources`.
