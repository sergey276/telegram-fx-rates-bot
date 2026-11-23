from __future__ import annotations

import re
import string
from pathlib import Path

import pytest

from app.i18n import DEFAULT_LANG, LANGUAGES, TEXTS, normalize_lang, t

APP = Path(__file__).parent.parent / "app"


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def test_every_key_has_all_languages():
    missing = [(k, lang) for k, v in TEXTS.items() for lang in LANGUAGES if not v.get(lang)]
    assert not missing, missing


@pytest.mark.parametrize("key", sorted(TEXTS))
def test_placeholders_match_across_languages(key):
    sets = {lang: placeholders(TEXTS[key][lang]) for lang in LANGUAGES}
    assert len({frozenset(s) for s in sets.values()}) == 1, f"{key}: {sets}"


def test_html_tags_are_balanced_in_every_text():
    for key, variants in TEXTS.items():
        for lang, text in variants.items():
            for tag in ("b", "i", "code"):
                assert text.count(f"<{tag}>") == text.count(f"</{tag}>"), f"{key}[{lang}]"


def test_all_keys_used_in_code_exist():
    used: set[str] = set()
    pattern = re.compile(r"""\bt\(\s*[\w.]+\s*,\s*f?["']([\w.{}\[\]]+)["']""")
    for path in APP.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        for key in pattern.findall(path.read_text(encoding="utf-8")):
            used.add(key)
    dynamic = {k for k in used if "{" in k}
    static = used - dynamic
    missing = sorted(k for k in static if k not in TEXTS)
    assert not missing, missing
    # динамические ключи (period.{p}, metric.{m.value}, alerts.desc.{kind}, settings.theme.{...}, alerts.type.{...})
    for prefix in ("period.", "metric.", "alerts.desc.", "settings.theme.", "alerts.type.", "metric.btn_"):
        assert any(k.startswith(prefix) for k in TEXTS), prefix


def test_dynamic_keys_cover_all_enum_values():
    from app.alerts.types import AlertType
    from app.services.chart_service import PERIODS

    for kind in AlertType:
        assert f"alerts.desc.{kind.value}" in TEXTS and f"alerts.type.{kind.value}" in TEXTS and f"fire.{kind.value}" in TEXTS
    for period in PERIODS:
        assert f"period.{period}" in TEXTS
    for metric in ("last", "bid", "ask"):
        assert f"metric.{metric}" in TEXTS and f"metric.btn_{metric}" in TEXTS
    for theme in ("dark", "light"):
        assert f"settings.theme.{theme}" in TEXTS


def test_t_fallbacks():
    assert t("xx", "menu.rates") == TEXTS["menu.rates"][DEFAULT_LANG]  # неизвестный язык -> русский
    assert t("en", "no.such.key") == "no.such.key"
    assert t("en", "err.invalid_number") != ""  # нехватка параметров не роняет вызов


def test_normalize_lang():
    assert normalize_lang("uk-UA") == "uk" and normalize_lang("EN") == "en"
    assert normalize_lang("de") == "ru" and normalize_lang(None) == "ru"
    assert normalize_lang("zz", default="en") == "en"
