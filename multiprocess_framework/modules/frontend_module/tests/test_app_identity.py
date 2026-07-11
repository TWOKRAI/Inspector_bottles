# -*- coding: utf-8 -*-
"""
Тесты AppIdentity (Task NEW-2 — de-brand frontend_module).

frontend_module — generic UI-фреймворк, не должен знать имя конкретного продукта
("Inspector Bottles" и т.п.). AppIdentity — точка инъекции org/app_name/title/logo_text
из composition root приложения (multiprocess_prototype). Дефолт — нейтральный.

Покрываем:
  - дефолтная идентичность нейтральна (не "Inspector"), берётся из env MPF_APP_NAME
  - set_app_identity/get_app_identity — инъекция и чтение
  - AppIdentity — frozen (иммутабельность)
  - __post_init__: window_title/logo_text по умолчанию = app_name, если не заданы явно
  - prefs_store читает org из текущей AppIdentity (QSettings namespace)
  - LoadingWindow: fallback-текст логотипа берётся из AppIdentity, если logo_text не передан явно
"""

from __future__ import annotations

import dataclasses

import pytest

from multiprocess_framework.modules.frontend_module.core.app_identity import (
    AppIdentity,
    get_app_identity,
    set_app_identity,
)


@pytest.fixture(autouse=True)
def _restore_identity():
    """Изолировать тесты друг от друга — identity глобальна (module-level singleton)."""
    original = get_app_identity()
    yield
    set_app_identity(original)


class TestAppIdentityDefault:
    def test_default_identity_is_neutral(self) -> None:
        """Дефолт НЕ должен быть зашит под конкретный продукт ('Inspector')."""
        identity = get_app_identity()
        assert "inspector" not in identity.org.lower()
        assert "inspector" not in identity.app_name.lower()

    def test_default_identity_from_env(self, monkeypatch) -> None:
        """Без MPF_APP_NAME — 'MultiprocessApp'; с ним — значение из env."""
        import multiprocess_framework.modules.frontend_module.core.app_identity as mod

        monkeypatch.delenv("MPF_APP_NAME", raising=False)
        assert mod._default_identity().org == "MultiprocessApp"

        monkeypatch.setenv("MPF_APP_NAME", "AcmeApp")
        assert mod._default_identity().org == "AcmeApp"
        assert mod._default_identity().app_name == "AcmeApp"


class TestAppIdentitySetGet:
    def test_set_then_get_roundtrip(self) -> None:
        identity = AppIdentity(org="Acme", app_name="Acme App")
        set_app_identity(identity)
        assert get_app_identity() is identity
        assert get_app_identity().org == "Acme"
        assert get_app_identity().app_name == "Acme App"

    def test_is_frozen(self) -> None:
        identity = AppIdentity(org="Acme", app_name="Acme App")
        with pytest.raises(dataclasses.FrozenInstanceError):
            identity.org = "Other"  # type: ignore[misc]

    def test_window_title_and_logo_text_default_to_app_name(self) -> None:
        identity = AppIdentity(org="Acme", app_name="Acme App")
        assert identity.window_title == "Acme App"
        assert identity.logo_text == "Acme App"

    def test_window_title_and_logo_text_explicit_override(self) -> None:
        identity = AppIdentity(
            org="Acme",
            app_name="Acme App",
            window_title="Acme — панель управления",
            logo_text="ACME",
        )
        assert identity.window_title == "Acme — панель управления"
        assert identity.logo_text == "ACME"


class TestPrefsStoreUsesIdentity:
    def test_settings_org_follows_current_identity(self) -> None:
        from multiprocess_framework.modules.frontend_module.core import prefs_store

        set_app_identity(AppIdentity(org="Acme", app_name="Acme App"))
        settings = prefs_store._settings()
        assert settings.organizationName() == "Acme"

        set_app_identity(AppIdentity(org="OtherOrg", app_name="Other App"))
        settings = prefs_store._settings()
        assert settings.organizationName() == "OtherOrg"


class TestLoadingWindowUsesIdentity:
    def test_fallback_logo_text_defaults_to_identity(self, qtbot) -> None:
        from multiprocess_framework.modules.frontend_module.windows.loading_window import (
            LoadingWindow,
        )

        set_app_identity(AppIdentity(org="Acme", app_name="Acme App"))
        window = LoadingWindow()
        qtbot.addWidget(window)
        assert window._logo_text == "Acme App"

    def test_explicit_logo_text_overrides_identity(self, qtbot) -> None:
        from multiprocess_framework.modules.frontend_module.windows.loading_window import (
            LoadingWindow,
        )

        set_app_identity(AppIdentity(org="Acme", app_name="Acme App"))
        window = LoadingWindow(logo_text="Custom Logo")
        qtbot.addWidget(window)
        assert window._logo_text == "Custom Logo"
