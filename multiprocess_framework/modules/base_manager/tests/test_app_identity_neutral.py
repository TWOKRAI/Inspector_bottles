# -*- coding: utf-8 -*-
"""Нейтральная идентичность приложения (D4) — фреймворк не знает своего продукта.

Что доказывается:
- дефолт нейтрален: ни в одном виде не содержит имени конкретного продукта;
- env ``MPF_APP_NAME`` читается ПРИ ВЫЗОВЕ, а не при импорте (composition root
  выставляет её позже, чем отрабатывают импорты фреймворка);
- пустая/пробельная env считается незаданной (иначе безымянные артефакты);
- slug пригоден для имени файла и НЕ схлопывает разные имена в одно.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.base_manager.utils import (
    APP_NAME_ENV,
    DEFAULT_APP_NAME,
    app_name_slug,
    resolve_app_name,
)


class TestResolveAppName:
    def test_default_is_neutral(self, monkeypatch):
        """Без env — нейтральное имя, без следа конкретного продукта."""
        monkeypatch.delenv(APP_NAME_ENV, raising=False)
        assert resolve_app_name() == DEFAULT_APP_NAME
        assert "inspector" not in DEFAULT_APP_NAME.lower()
        assert "bottle" not in DEFAULT_APP_NAME.lower()

    def test_env_is_read_at_call_time(self, monkeypatch):
        """Значение берётся при вызове: снимок на импорте замёрз бы до composition root."""
        monkeypatch.delenv(APP_NAME_ENV, raising=False)
        assert resolve_app_name() == DEFAULT_APP_NAME
        monkeypatch.setenv(APP_NAME_ENV, "AcmeApp")
        assert resolve_app_name() == "AcmeApp"
        monkeypatch.setenv(APP_NAME_ENV, "OtherApp")
        assert resolve_app_name() == "OtherApp"

    @pytest.mark.parametrize("blank", ["", "   ", "\t"])
    def test_blank_env_counts_as_unset(self, monkeypatch, blank):
        """MPF_APP_NAME='' — не «имя пустое», а «имя не задано»."""
        monkeypatch.setenv(APP_NAME_ENV, blank)
        assert resolve_app_name() == DEFAULT_APP_NAME

    def test_explicit_environ_argument_wins_over_process_env(self, monkeypatch):
        """Явно переданный словарь окружения не смотрит в os.environ."""
        monkeypatch.setenv(APP_NAME_ENV, "FromProcess")
        assert resolve_app_name({APP_NAME_ENV: "FromArg"}) == "FromArg"


class TestAppNameSlug:
    def test_spaces_become_safe_separator(self, monkeypatch):
        monkeypatch.setenv(APP_NAME_ENV, "Inspector Bottles")
        assert app_name_slug() == "Inspector_Bottles"

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Acme/App", "Acme_App"),
            ("a\\b", "a_b"),
            ("app:1", "app_1"),
            ("../etc", "etc"),
            ("ok-name_1.2", "ok-name_1.2"),
        ],
    )
    def test_filename_unsafe_characters_removed(self, raw, expected):
        """Slug едет в имя файла в общей temp — разделители пути обязаны исчезнуть."""
        assert app_name_slug(raw) == expected

    def test_degenerate_name_does_not_become_empty(self):
        """Имя из одних недопустимых символов даёт дефолтный slug, а не пустую строку."""
        assert app_name_slug("///") == app_name_slug(DEFAULT_APP_NAME)
        assert app_name_slug("///") != ""

    def test_distinct_names_stay_distinct(self):
        """Разные приложения не схлопываются в один slug — иначе делили бы pid-реестр."""
        assert app_name_slug("App One") != app_name_slug("App Two")
        assert app_name_slug("acme") != app_name_slug("Acme")
