"""P2P: разбор реальных ответов пяти площадок, сравнение, отказоустойчивость, сообщения бота."""

from __future__ import annotations

import asyncio
from decimal import Decimal as D

import pytest

from app.bot.callbacks import AdminCb, Nav, P2PCb
from app.providers.binance_p2p import BINANCE_PAY_TYPES, parse_ads
from app.providers.p2p_common import P2P_BANKS, P2PAd, Side, banks_in, rate_fraction
from app.providers.p2p_platforms import (
    BYBIT_PAYMENT_IDS,
    all_platforms,
    parse_bitget,
    parse_bybit,
    parse_kucoin,
    parse_okx,
)
from app.services import p2p as p2p_module
from app.services.p2p import AMOUNTS, P2PService, select_ads
from app.utils.http import HttpClient, ProviderError, RateLimitedError
from tests.bot_harness import BotApp
from tests.conftest import load_json
from tests.fake_p2p import FakePlatform, ad, fake_platforms


# --------------------------------------------------------------------------- разбор реальных ответов
class TestParsingRealResponses:
    def test_binance(self):
        for side in ("BUY", "SELL"):
            ads = parse_ads(load_json(f"p2p_binance_{side}.json"))
            assert len(ads) == 6 and all(a.price > 0 and a.min_amount <= a.max_amount for a in ads)
        with pytest.raises(ProviderError):
            parse_ads({"code": "000002", "message": "bad"})

    def test_bybit(self):
        for tag in ("buy", "sell"):
            ads = parse_bybit(load_json(f"p2p_bybit_{tag}.json"))
            assert ads and all(a.price > 0 and 0 <= a.finish_rate <= 1 for a in ads)
        with pytest.raises(ProviderError):
            parse_bybit({"ret_code": 10001, "ret_msg": "x"})

    def test_bybit_payment_ids_match_the_names_bybit_publishes(self):
        names = {str(p["paymentType"]): p["paymentName"] for p in load_json("p2p_bybit_payments.json")["result"]["paymentConfigVo"]}
        for bank, ids in BYBIT_PAYMENT_IDS.items():
            for pid in ids:
                assert bank in banks_in(names[pid]), f"{bank}: id {pid} = {names[pid]!r}"
        assert "alliance" not in BYBIT_PAYMENT_IDS  # у Bybit для UAH такого способа оплаты нет

    def test_okx_groups_by_bank_and_uses_merchants_side(self):
        buy = parse_okx(load_json("p2p_okx_buy.json"), Side.BUY)  # вы покупаете -> список sell мерчантов
        sell = parse_okx(load_json("p2p_okx_sell.json"), Side.SELL)
        assert {"monobank", "privatbank"} <= set(buy) and "monobank" in sell
        assert min(a.price for a in buy["monobank"]) < max(a.price for a in sell["monobank"])  # покупка дешевле продажи
        with pytest.raises(ProviderError):
            parse_okx({"code": 1, "msg": "err"}, Side.BUY)

    def test_kucoin(self):
        for tag in ("buy", "sell"):
            grouped = parse_kucoin(load_json(f"p2p_kucoin_{tag}.json"))
            assert grouped and all(a.price > 0 for ads in grouped.values() for a in ads)
        with pytest.raises(ProviderError):
            parse_kucoin({"success": False, "code": "500"})

    def test_bitget(self):
        for tag in ("buy", "sell"):
            grouped, has_next = parse_bitget(load_json(f"p2p_bitget_{tag}.json"))
            assert grouped and isinstance(has_next, bool)
        with pytest.raises(ProviderError):
            parse_bitget({"code": "40001", "msg": "x"})

    def test_garbage_payloads_raise_provider_error_not_crash(self):
        for fn in (parse_bybit, parse_kucoin, parse_ads):
            with pytest.raises(ProviderError):
                fn([])


class TestBankMatching:
    @pytest.mark.parametrize("name,expected", [
        ("Monobank (Card)", {"monobank"}), ("Monobank (IBAN)", {"monobank"}), ("Monobankiban", {"monobank"}),
        ("PrivatBank (CARD)", {"privatbank"}), ("PRIVAT_BANK", {"privatbank"}), ("Privat Bank", {"privatbank"}),
        ("A-Bank (CARD)", {"abank"}), ("ABank", {"abank"}), ("AbankIBAN", {"abank"}),
        ("PUMB (CARD)", {"pumb"}), ("PUMBBank", {"pumb"}), ("Sense SuperApp (CARD)", {"sense"}), ("SENSE_SUPERAPP", {"sense"}),
        ("ALLIANCE_BANK", {"alliance"}), ("alliancecard", {"alliance"}), ("Alliance bank (Card)", {"alliance"}),
        ("Raiffeisen Bank Aval", set()), ("Oschadbank", set()), ("Bank Vlasnyi Rakhunok", set()), ("", set()),
    ])
    def test_banks_in(self, name, expected):
        assert banks_in(name) == expected

    def test_several_methods_in_one_ad(self):
        assert banks_in("PUMB (CARD)", "Monobank (Card)", "Idea Bank") == {"pumb", "monobank"}

    def test_binance_ids_cover_all_banks(self):
        assert set(BINANCE_PAY_TYPES) == set(P2P_BANKS)

    @pytest.mark.parametrize("raw,expected", [(0.97, D("0.97")), ("0.95", D("0.95")), (97, D("0.97")), (100, D(1)), (None, D(0)), ("x", D(0)), (-1, D(0))])
    def test_rate_fraction(self, raw, expected):
        assert rate_fraction(raw) == expected

    def test_ad_fits_amount(self):
        a = ad("47", low="1000", high="10000", qty="150")
        assert a.fits(D(5000)) and not a.fits(D(500)) and not a.fits(D(20000))
        assert not ad("47", qty="10").fits(D(5000))  # объёма объявления не хватает на сумму


# --------------------------------------------------------------------------- отбор и сравнение
class TestSelection:
    def test_filters_sorts_and_limits(self):
        ads = [ad("46.0", orders=2), ad("46.5", rate="0.5"), ad("47.0"), ad("46.8"), ad("45", low="90000", high="99999")]
        assert [a.price for a in select_ads(ads, Side.BUY, D(5000))] == [D("46.8"), D("47.0")]
        assert [a.price for a in select_ads(ads, Side.SELL, D(5000))] == [D("47.0"), D("46.8")]
        assert len(select_ads([ad(str(40 + i)) for i in range(12)], Side.BUY, D(5000))) == 5


class TestService:
    async def test_compares_all_platforms_and_banks(self):
        service = P2PService(fake_platforms())
        board = await service.board("USDT", 5000)
        assert set(board.platforms) == {"binance", "bybit", "okx", "kucoin", "bitget"}
        # ненадёжные и неподходящие по сумме объявления отсеяны: лучшая цена Monobank на покупку — у OKX
        platform, ad_ = board.best_for_bank("monobank", Side.BUY)
        assert platform == "okx" and ad_.price == D("46.80")
        assert board.best_for_bank("monobank", Side.SELL)[0] == "okx" and board.best_for_bank("monobank", Side.SELL)[1].price == D("49.15")
        assert board.best_for_bank("alliance", Side.BUY)[0] == "binance"  # Alliance есть не везде
        assert board.cheapest_buy()[:2] == ("okx", "monobank") and board.richest_sell()[:2] == ("okx", "privatbank")
        assert board.cross_pct() == (D("49.31") - D("46.80")) / D("46.80") * 100
        assert board.best_for_platform("kucoin", Side.BUY)[0] == "monobank"
        assert not board.failed and not board.stale

    async def test_top_ads_merge_platforms_sorted(self):
        board = await P2PService(fake_platforms()).board("USDT", 5000)
        top = board.top_ads("monobank", Side.BUY)
        prices = [a.price for _, a in top]
        assert prices == sorted(prices) and len(top) == 5 and {p for p, _ in top} >= {"okx", "bybit"}
        sells = [a.price for _, a in board.top_ads("monobank", Side.SELL)]
        assert sells == sorted(sells, reverse=True)

    async def test_amount_is_passed_to_every_platform(self):
        platforms = fake_platforms()
        await P2PService(platforms).board("USDT", 10000)
        assert all(c[2] == D(10000) for p in platforms for c in p.calls) and all(len(p.calls) == 2 for p in platforms)

    async def test_cache_force_and_separate_keys(self):
        platforms = fake_platforms()
        service = P2PService(platforms)
        await service.board("USDT", 5000)
        await service.board("USDT", 5000)
        assert all(len(p.calls) == 2 for p in platforms)
        await service.board("USDT", 5000, force=True)
        assert all(len(p.calls) == 4 for p in platforms)
        await service.board("BTC", 5000)
        assert all(len(p.calls) == 6 for p in platforms)

    async def test_parallel_users_share_one_fetch(self):
        platforms = fake_platforms()
        service = P2PService(platforms)
        await asyncio.gather(*(service.board("USDT", 5000) for _ in range(10)))
        assert all(len(p.calls) == 2 for p in platforms)

    async def test_one_failing_platform_does_not_break_others(self):
        platforms = fake_platforms()
        platforms[1].error = ProviderError("Bybit P2P: недоступен")
        board = await P2PService(platforms).board("USDT", 5000)
        assert board.failed == ["bybit"] and board.has_data
        assert board.best_for_bank("monobank", Side.BUY)[0] == "okx"
        assert board.platforms["bybit"].error and not board.platforms["bybit"].has_data

    async def test_all_platforms_failing_gives_no_data(self):
        platforms = fake_platforms()
        for p in platforms:
            p.error = ProviderError("down")
        board = await P2PService(platforms).board("USDT", 5000)
        assert not board.has_data and len(board.failed) == 5

    async def test_failed_refresh_shows_previous_data_marked_stale(self):
        platforms = fake_platforms()
        service = P2PService(platforms)
        first = await service.board("USDT", 5000)
        platforms[2].error = ProviderError("down")
        again = await service.board("USDT", 5000, force=True)
        assert again.stale == ["okx"] and again.platforms["okx"].has_data and not again.failed
        assert again.best_for_bank("monobank", Side.BUY) == first.best_for_bank("monobank", Side.BUY)

    async def test_rate_limit_pauses_platform_requests(self):
        platforms = fake_platforms()
        platforms[4].error = RateLimitedError("429", retry_after=120)
        service = P2PService(platforms)
        await service.board("USDT", 5000)
        calls = len(platforms[4].calls)
        await service.board("USDT", 5000, force=True)
        assert len(platforms[4].calls) == calls  # пока действует пауза, запросов к Bitget нет
        assert "bitget" in (await service.board("USDT", 5000, force=True)).failed

    async def test_slow_platform_times_out_without_blocking_the_rest(self, monkeypatch):
        monkeypatch.setattr(p2p_module, "PLATFORM_TIMEOUT", 0.2)
        platforms = fake_platforms()
        platforms[3].delay = 2.0
        board = await P2PService(platforms).board("USDT", 5000)
        assert board.failed == ["kucoin"] and board.has_data

    async def test_unexpected_exception_is_contained(self):
        platforms = fake_platforms()
        platforms[0].error = KeyError("поле исчезло")
        board = await P2PService(platforms).board("USDT", 5000)
        assert board.failed == ["binance"] and board.has_data

    async def test_invalid_parameters_rejected(self):
        service = P2PService(fake_platforms())
        for asset, amount in (("DOGE", 5000), ("USDT", 123)):
            with pytest.raises(ValueError):
                await service.board(asset, amount)

    def test_real_platform_set_is_the_five_verified_ones(self):
        names = [p.name for p in all_platforms(HttpClient())]
        assert names == ["binance", "bybit", "okx", "kucoin", "bitget"]


# --------------------------------------------------------------------------- бот
@pytest.fixture
async def app():
    a = await BotApp.create()
    yield a
    await a.close()


class TestBot:
    async def test_main_screen_compares_banks_and_platforms(self, app):
        s = await app.say("/start")
        assert any("P2P" in b["text"] for r in s.last_markup() for b in r)
        text = (await app.say("/p2p")).last_text()
        for bank in ("Monobank", "PrivatBank", "Alliance", "Sense Bank", "A-Bank", "PUMB"):
            assert bank in text
        for platform in ("Binance", "Bybit", "OKX", "KuCoin", "Bitget"):
            assert platform in text
        assert "По банкам" in text and "По площадкам" in text and "5 000" in text.replace("\xa0", " ")
        assert "Monobank: купить <b>46.8</b> (OKX)" in text and "продать <b>49.15</b> (OKX)" in text
        assert "Дешевле всего купить: <b>OKX</b> через Monobank" in text and "Выгоднее всего продать: <b>OKX</b> через PrivatBank" in text
        assert "не гарантированная прибыль" in text.lower() and len(text) < 4000

    async def test_bank_detail_compares_every_platform(self, app):
        s = await app.press(P2PCb(act="bank", asset="USDT", amount=5000, bank="monobank").pack())
        text = s.last_text()
        for platform in ("Binance", "Bybit", "OKX", "KuCoin", "Bitget"):
            assert platform in text
        assert "Сравнение площадок" in text and "лимит" in text and "1." in text
        assert P2PCb(act="view", asset="USDT", amount=5000).pack() in s.button_data()

    async def test_bank_missing_on_some_platforms_is_shown_gracefully(self, app):
        text = (await app.press(P2PCb(act="bank", asset="USDT", amount=5000, bank="alliance").pack())).last_text()
        assert "Bybit" in text and "нет подходящих объявлений" in text  # Alliance есть только у Binance

    async def test_amount_and_asset_switching(self, app):
        s = await app.press(P2PCb(act="view", asset="USDT", amount=10000).pack())
        assert "10 000" in s.last_text().replace("\xa0", " ")
        s = await app.press(P2PCb(act="view", asset="BTC", amount=10000).pack())
        assert "BTC/UAH" in s.last_text()
        assert set(AMOUNTS) == {1000, 5000, 10000, 50000}

    async def test_partial_outage_is_reported_but_data_still_shown(self, app):
        app.ctx.p2p._platforms["bitget"].error = ProviderError("429")
        text = (await app.say("/p2p")).last_text()
        assert "Не ответили: Bitget" in text and "Bitget ⚠️" in text and "Monobank" in text

    async def test_total_outage_shows_message(self, app):
        for p in app.ctx.p2p._platforms.values():
            p.error = ProviderError("down")
        text = (await app.say("/p2p")).last_text()
        assert "P2P сейчас недоступен" in text

    async def test_invalid_callbacks_rejected(self, app):
        for data in (P2PCb(act="view", asset="HACK", amount=5000), P2PCb(act="view", asset="USDT", amount=7),
                     P2PCb(act="bank", asset="USDT", amount=5000, bank="nobank")):
            app.session.clear()
            s = await app.press(data.pack())
            assert any(c[1].get("show_alert") for c in s.calls if c[0] == "AnswerCallbackQuery")

    async def test_navigation_and_admin_switch(self, app):
        assert "P2P" in (await app.press(Nav(to="p2p").pack())).last_text()
        await app.press(AdminCb(act="flip", v="p2p_enabled").pack(), user_id=999)
        assert "отключён администратором" in (await app.say("/p2p")).last_text()

    async def test_languages(self, app):
        assert "Cheapest to buy" in (await app.say("/p2p", user_id=5, lang="en")).last_text()
        assert "Дешевше за все купити" in (await app.say("/p2p", user_id=6, lang="uk")).last_text()


def test_fake_platform_interface():
    assert isinstance(fake_platforms()[0], FakePlatform) and isinstance(ad("1"), P2PAd)


def test_idea_bank_is_not_mistaken_for_a_bank():
    """Регрессия: «Idea Bank» содержит подстроку «abank» и попадал бы в объявления A-Bank."""
    assert banks_in("Idea Bank") == set() and banks_in("IdeaBankIBAN") == set()
    assert banks_in("A Bank (Card)") == {"abank"} and banks_in("a-bank") == {"abank"}


def test_kucoin_percent_string_rate_is_understood():
    """Регрессия: KuCoin отдаёт «97.68%» строкой; раньше рейтинг читался как 0 и все объявления KuCoin отсеивались."""
    assert rate_fraction("97.68%") == D("0.9768") and rate_fraction("100.00%") == D(1) and rate_fraction("1.00%") == D("0.01")
    ads = parse_kucoin(load_json("p2p_kucoin_buy.json"))
    assert all(a.finish_rate > D("0.9") for lst in ads.values() for a in lst)
    assert select_ads(ads["monobank"], Side.BUY, D(5000)), "после фильтров у KuCoin должны остаться объявления"
