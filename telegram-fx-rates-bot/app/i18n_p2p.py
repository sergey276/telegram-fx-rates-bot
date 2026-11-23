"""Тексты раздела P2P (ru / uk / en). Подмешиваются в app.i18n.TEXTS."""

from __future__ import annotations

P2P_TEXTS: dict[str, dict[str, str]] = {
    "menu.p2p": {"ru": "💱 P2P", "uk": "💱 P2P", "en": "💱 P2P"},
    "p2p.title": {
        "ru": "💱 <b>P2P · {asset}/UAH</b> · сравнение площадок",
        "uk": "💱 <b>P2P · {asset}/UAH</b> · порівняння майданчиків",
        "en": "💱 <b>P2P · {asset}/UAH</b> · platform comparison",
    },
    "p2p.params": {
        "ru": "Сумма сделки: <b>{amount} ₴</b>. Только объявления под эту сумму от продавцов с историей (не менее {orders} сделок и {rate} завершённых). Площадки: {platforms}.",
        "uk": "Сума угоди: <b>{amount} ₴</b>. Лише оголошення під цю суму від продавців з історією (щонайменше {orders} угод і {rate} завершених). Майданчики: {platforms}.",
        "en": "Trade size: <b>{amount} ₴</b>. Only ads for this amount from advertisers with history (at least {orders} orders and {rate} completed). Platforms: {platforms}.",
    },
    "p2p.by_bank": {
        "ru": "<b>По банкам</b> — лучшая цена среди всех площадок:",
        "uk": "<b>По банках</b> — найкраща ціна серед усіх майданчиків:",
        "en": "<b>By bank</b> — best price across all platforms:",
    },
    "p2p.by_platform": {
        "ru": "<b>По площадкам</b> — лучшая цена среди банков:",
        "uk": "<b>По майданчиках</b> — найкраща ціна серед банків:",
        "en": "<b>By platform</b> — best price across banks:",
    },
    "p2p.bank_line": {
        "ru": "{bank}: купить <b>{buy}</b> ({buy_src}) · продать <b>{sell}</b> ({sell_src})",
        "uk": "{bank}: купити <b>{buy}</b> ({buy_src}) · продати <b>{sell}</b> ({sell_src})",
        "en": "{bank}: buy <b>{buy}</b> ({buy_src}) · sell <b>{sell}</b> ({sell_src})",
    },
    "p2p.platform_line": {
        "ru": "{platform}{mark}: купить <b>{buy}</b> ({buy_bank}) · продать <b>{sell}</b> ({sell_bank})",
        "uk": "{platform}{mark}: купити <b>{buy}</b> ({buy_bank}) · продати <b>{sell}</b> ({sell_bank})",
        "en": "{platform}{mark}: buy <b>{buy}</b> ({buy_bank}) · sell <b>{sell}</b> ({sell_bank})",
    },
    "p2p.none": {"ru": "—", "uk": "—", "en": "—"},
    "p2p.best_buy": {
        "ru": "🟢 Дешевле всего купить: <b>{platform}</b> через {bank} — {price} ₴",
        "uk": "🟢 Дешевше за все купити: <b>{platform}</b> через {bank} — {price} ₴",
        "en": "🟢 Cheapest to buy: <b>{platform}</b> via {bank} — {price} ₴",
    },
    "p2p.best_sell": {
        "ru": "🔴 Выгоднее всего продать: <b>{platform}</b> через {bank} — {price} ₴",
        "uk": "🔴 Вигідніше за все продати: <b>{platform}</b> через {bank} — {price} ₴",
        "en": "🔴 Best to sell: <b>{platform}</b> via {bank} — {price} ₴",
    },
    "p2p.cross": {
        "ru": "↔️ Разница между лучшей продажей и лучшей покупкой: <b>{pct}</b> (до издержек, лимитов и рисков; это разные объявления и площадки)",
        "uk": "↔️ Різниця між найкращим продажем і найкращою купівлею: <b>{pct}</b> (до витрат, лімітів і ризиків; це різні оголошення та майданчики)",
        "en": "↔️ Gap between best sell and best buy: <b>{pct}</b> (before costs, limits and risks; different ads and platforms)",
    },
    "p2p.legend": {
        "ru": "«Купить» — цена, по которой вы покупаете {asset} у продавца; «продать» — цена, по которой покупатель берёт у вас {asset}.",
        "uk": "«Купити» — ціна, за якою ви купуєте {asset} у продавця; «продати» — ціна, за якою покупець бере у вас {asset}.",
        "en": "“Buy” is the price you pay a seller for {asset}; “sell” is the price a buyer pays you for {asset}.",
    },
    "p2p.disclaimer": {
        "ru": "⚠️ Цены взяты из публичных объявлений P2P-площадок (неофициальные веб-эндпоинты) и могут измениться или исчезнуть до сделки. У каждого объявления свои лимиты и условия; комиссии банков, правила площадок и риск контрагента не учтены. Перед сделкой проверьте условия в приложении площадки. Это не финансовый совет и не гарантированная прибыль.",
        "uk": "⚠️ Ціни взято з публічних оголошень P2P-майданчиків (неофіційні веб-ендпоінти) і вони можуть змінитися чи зникнути до угоди. У кожного оголошення свої ліміти й умови; комісії банків, правила майданчиків і ризик контрагента не враховано. Перед угодою перевірте умови в застосунку майданчика. Це не фінансова порада і не гарантований прибуток.",
        "en": "⚠️ Prices come from public P2P platform ads (unofficial web endpoints) and may change or vanish before you trade. Each ad has its own limits and terms; bank fees, platform rules and counterparty risk are not included. Check the terms in the platform app before trading. Not financial advice, not guaranteed profit.",
    },
    "p2p.updated": {"ru": "🕒 Обновлено {time}", "uk": "🕒 Оновлено {time}", "en": "🕒 Updated {time}"},
    "p2p.unavailable": {
        "ru": "⛔ P2P сейчас недоступен: площадки не ответили или изменили формат данных. Попробуйте позже.",
        "uk": "⛔ P2P зараз недоступний: майданчики не відповіли або змінили формат даних. Спробуйте пізніше.",
        "en": "⛔ P2P is unavailable right now: the platforms did not respond or changed their data format. Try again later.",
    },
    "p2p.failed": {
        "ru": "⚠️ Не ответили: {items}.",
        "uk": "⚠️ Не відповіли: {items}.",
        "en": "⚠️ No response from: {items}.",
    },
    "p2p.stale": {
        "ru": "🟡 Показаны прошлые данные (обновить не удалось): {items}.",
        "uk": "🟡 Показано попередні дані (оновити не вдалося): {items}.",
        "en": "🟡 Showing previous data (refresh failed): {items}.",
    },
    "p2p.off": {
        "ru": "P2P-раздел отключён администратором.",
        "uk": "Розділ P2P вимкнено адміністратором.",
        "en": "The P2P section is disabled by the administrator.",
    },
    "p2p.detail_title": {
        "ru": "💱 <b>{bank}</b> · {asset}/UAH · сумма {amount} ₴",
        "uk": "💱 <b>{bank}</b> · {asset}/UAH · сума {amount} ₴",
        "en": "💱 <b>{bank}</b> · {asset}/UAH · amount {amount} ₴",
    },
    "p2p.detail_platforms": {
        "ru": "<b>Сравнение площадок</b> (лучшая цена через этот банк):",
        "uk": "<b>Порівняння майданчиків</b> (найкраща ціна через цей банк):",
        "en": "<b>Platform comparison</b> (best price via this bank):",
    },
    "p2p.platform_row": {
        "ru": "{platform}{mark}: купить <b>{buy}</b> · продать <b>{sell}</b>",
        "uk": "{platform}{mark}: купити <b>{buy}</b> · продати <b>{sell}</b>",
        "en": "{platform}{mark}: buy <b>{buy}</b> · sell <b>{sell}</b>",
    },
    "p2p.detail_buy": {
        "ru": "Купить {asset} — лучшие объявления (цена за 1 {asset}):",
        "uk": "Купити {asset} — найкращі оголошення (ціна за 1 {asset}):",
        "en": "Buy {asset} — best ads (price per 1 {asset}):",
    },
    "p2p.detail_sell": {
        "ru": "Продать {asset} — лучшие объявления (цена за 1 {asset}):",
        "uk": "Продати {asset} — найкращі оголошення (ціна за 1 {asset}):",
        "en": "Sell {asset} — best ads (price per 1 {asset}):",
    },
    "p2p.ad_line": {
        "ru": "{n}. <b>{price} ₴</b> · {platform} · доступно {available} {asset} · лимит {low}–{high} ₴ · {orders} сделок, {rate}",
        "uk": "{n}. <b>{price} ₴</b> · {platform} · доступно {available} {asset} · ліміт {low}–{high} ₴ · {orders} угод, {rate}",
        "en": "{n}. <b>{price} ₴</b> · {platform} · {available} {asset} available · limit {low}–{high} ₴ · {orders} orders, {rate}",
    },
    "p2p.no_ads": {"ru": "нет подходящих объявлений", "uk": "немає відповідних оголошень", "en": "no matching ads"},
    "p2p.no_bank": {
        "ru": "нет на площадке",
        "uk": "немає на майданчику",
        "en": "not available on this platform",
    },
}
