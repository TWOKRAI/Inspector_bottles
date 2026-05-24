# -*- coding: utf-8 -*-
"""
Unit-тесты WindowManager (Task C2).

Покрываем: register, show_window, hide_window, close_all,
set_access_context, set_access_level (deprecated), _config_get,
window_shown/window_hidden сигналы, update_config, get_window,
get_current_window_name.

QApplication создаётся через pytest-qt (qapp fixture).
Окна — мок-объекты без реального Qt.
WindowRegistry используется реальный.
"""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from multiprocess_framework.modules.frontend_module.application.window_manager import (
    WindowManager,
    _config_get,
)
from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_mock_window(name: str = "win") -> MagicMock:
    """Создаёт мок-окно с методами Qt-виджета."""
    w = MagicMock(name=name)
    w.show = MagicMock()
    w.hide = MagicMock()
    w.close = MagicMock()
    w.raise_ = MagicMock()
    w.activateWindow = MagicMock()
    w.setCursor = MagicMock()
    w.showFullScreen = MagicMock()
    w.showNormal = MagicMock()
    w.setFixedSize = MagicMock()
    w.setMaximumSize = MagicMock()
    w.setMinimumSize = MagicMock()
    return w


def _make_manager(config: dict | None = None) -> WindowManager:
    """Создаёт WindowManager с минимальным конфигом."""
    registers = MagicMock()
    return WindowManager(
        config=config or {},
        registers_manager=registers,
    )


# ---------------------------------------------------------------------------
# Фикстура
# ---------------------------------------------------------------------------


@pytest.fixture
def manager(qapp):
    """WindowManager с реальным QApplication из pytest-qt."""
    return _make_manager()


# ===========================================================================
# Тесты _config_get (standalone-функция, не требует QApplication)
# ===========================================================================


class TestConfigGet:
    """Тесты хелпера _config_get."""

    def test_none_config_returns_default(self):
        """
        Given: config = None
        When: _config_get(None, "key")
        Then: возвращается default
        """
        assert _config_get(None, "key", "default_val") == "default_val"

    def test_dict_top_level_key(self):
        """
        Given: dict {"a": 1}
        When: _config_get(config, "a")
        Then: возвращается 1
        """
        assert _config_get({"a": 1}, "a") == 1

    def test_dict_dot_notation_nested(self):
        """
        Given: dict {"window": {"min_width": 800}}
        When: _config_get(config, "window.min_width")
        Then: возвращается 800
        """
        cfg = {"window": {"min_width": 800}}
        assert _config_get(cfg, "window.min_width") == 800

    def test_dict_missing_key_returns_default(self):
        """
        Given: dict без ключа
        When: _config_get(config, "missing", 42)
        Then: возвращается 42
        """
        assert _config_get({"a": 1}, "missing", 42) == 42

    def test_dict_partial_path_returns_default(self):
        """
        Given: dict {"window": "not_a_dict"}
        When: _config_get(config, "window.min_width", 0)
        Then: путь прерывается → возвращается 0
        """
        cfg = {"window": "not_a_dict"}
        assert _config_get(cfg, "window.min_width", 0) == 0

    def test_iconfig_like_object_with_get(self):
        """
        Given: объект с методом get() (IConfig-подобный, не dict)
        When: _config_get(config, "key")
        Then: вызывается config.get("key", default)
        """
        mock_config = MagicMock(spec_set=["get"])
        mock_config.get.return_value = "val"
        result = _config_get(mock_config, "key", "def")
        mock_config.get.assert_called_once_with("key", "def")
        assert result == "val"

    def test_object_without_get_returns_default(self):
        """
        Given: произвольный объект без get и не dict
        When: _config_get(obj, "key")
        Then: возвращается default
        """
        assert _config_get(object(), "key", "fallback") == "fallback"


# ===========================================================================
# Тесты WindowManager
# ===========================================================================


class TestRegister:
    """Тесты метода register()."""

    def test_register_window_adds_to_registry(self, manager):
        """
        Given: пустой WindowManager
        When: register("main", factory)
        Then: окно появляется в реестре (list_windows содержит "main")
        """
        # Given / When
        manager.register("main", lambda: _make_mock_window("main"))

        # Then
        assert "main" in manager._registry.list_windows()

    def test_register_returns_self_chainable(self, manager):
        """
        Given: WindowManager
        When: register(...)
        Then: возвращается сам менеджер (chainable)
        """
        result = manager.register("w1", lambda: _make_mock_window())
        assert result is manager

    def test_register_multiple_windows(self, manager):
        """
        Given: пустой WindowManager
        When: зарегистрировано несколько окон
        Then: все они в реестре
        """
        manager.register("w1", lambda: _make_mock_window())
        manager.register("w2", lambda: _make_mock_window())

        windows = manager._registry.list_windows()
        assert "w1" in windows
        assert "w2" in windows

    def test_register_duplicate_raises_value_error(self, manager):
        """
        Given: окно "main" уже зарегистрировано
        When: register("main", ...) снова
        Then: поднимается ValueError (поведение WindowRegistry)
        """
        manager.register("main", lambda: _make_mock_window())

        with pytest.raises(ValueError, match="main"):
            manager.register("main", lambda: _make_mock_window())


class TestShowWindow:
    """Тесты show_window()."""

    def test_show_registered_window_calls_show(self, manager):
        """
        Given: зарегистрировано окно "main"
        When: show_window("main")
        Then: window.show() вызван
        """
        # Given
        mock_win = _make_mock_window("main")
        manager.register("main", lambda: mock_win)

        # When
        manager.show_window("main")

        # Then
        mock_win.show.assert_called_once()

    def test_show_window_sets_current_window(self, manager):
        """
        Given: зарегистрировано окно "main"
        When: show_window("main")
        Then: get_current_window_name() == "main"
        """
        mock_win = _make_mock_window("main")
        manager.register("main", lambda: mock_win)

        manager.show_window("main")

        assert manager.get_current_window_name() == "main"

    def test_show_window_emits_signal(self, manager, qtbot):
        """
        Given: зарегистрировано окно "settings"
        When: show_window("settings")
        Then: сигнал window_shown эмитируется с именем "settings"
        """
        mock_win = _make_mock_window("settings")
        manager.register("settings", lambda: mock_win)

        signals_received = []
        manager.window_shown.connect(lambda name: signals_received.append(name))

        manager.show_window("settings")

        assert "settings" in signals_received

    def test_show_window_creates_if_not_created(self, manager):
        """
        Given: окно зарегистрировано, но не создано
        When: show_window("main")
        Then: фабрика вызвана, окно создано и показано
        """
        created = []
        mock_win = _make_mock_window("main")

        def factory():
            created.append(True)
            return mock_win

        manager.register("main", factory)

        # Окно ещё не создано
        assert not manager._registry.is_created("main")

        manager.show_window("main")

        assert len(created) == 1
        mock_win.show.assert_called_once()

    def test_show_window_calls_raise_and_activate(self, manager):
        """
        Given: зарегистрировано окно
        When: show_window(name)
        Then: вызываются raise_() и activateWindow()
        """
        mock_win = _make_mock_window("w")
        manager.register("w", lambda: mock_win)

        manager.show_window("w")

        mock_win.raise_.assert_called_once()
        mock_win.activateWindow.assert_called_once()

    def test_show_unknown_window_does_not_raise(self, manager):
        """
        Given: окно не зарегистрировано
        When: show_window("unknown")
        Then: не поднимается исключение (create возвращает None, _show ничего не делает)
        """
        # WindowManager не поднимает ValueError — WindowRegistry.create возвращает None
        # и _show молча пропускает None-окно
        try:
            manager.show_window("unknown")
        except Exception as exc:
            pytest.fail(f"show_window('unknown') поднял исключение: {exc}")


class TestHideWindow:
    """Тесты hide_window()."""

    def test_hide_window_calls_hide(self, manager):
        """
        Given: окно создано
        When: hide_window(name)
        Then: window.hide() вызван
        """
        mock_win = _make_mock_window("w")
        manager.register("w", lambda: mock_win)
        manager._registry.create("w")  # явно создаём

        manager.hide_window("w")

        mock_win.hide.assert_called_once()

    def test_hide_window_emits_signal(self, manager, qtbot):
        """
        Given: окно создано
        When: hide_window(name)
        Then: сигнал window_hidden эмитируется
        """
        mock_win = _make_mock_window("w")
        manager.register("w", lambda: mock_win)
        manager._registry.create("w")

        signals_received = []
        manager.window_hidden.connect(lambda name: signals_received.append(name))

        manager.hide_window("w")

        assert "w" in signals_received

    def test_hide_unknown_window_no_error(self, manager):
        """
        Given: окно не существует
        When: hide_window("ghost")
        Then: не поднимается исключение
        """
        try:
            manager.hide_window("ghost")
        except Exception as exc:
            pytest.fail(f"hide_window('ghost') поднял исключение: {exc}")


class TestCloseAll:
    """Тесты close_all()."""

    def test_close_all_clears_current_window(self, manager):
        """
        Given: открыто окно "main"
        When: close_all()
        Then: get_current_window_name() == None
        """
        mock_win = _make_mock_window("main")
        manager.register("main", lambda: mock_win)
        manager.show_window("main")
        assert manager.get_current_window_name() == "main"

        manager.close_all()

        assert manager.get_current_window_name() is None

    def test_close_all_calls_close_on_windows(self, manager):
        """
        Given: созданы окна w1 и w2
        When: close_all()
        Then: на обоих вызван close()
        """
        mock_w1 = _make_mock_window("w1")
        mock_w2 = _make_mock_window("w2")

        manager.register("w1", lambda: mock_w1)
        manager.register("w2", lambda: mock_w2)

        # Явно создаём окна
        manager._registry.create("w1")
        manager._registry.create("w2")

        manager.close_all()

        mock_w1.close.assert_called_once()
        mock_w2.close.assert_called_once()


class TestAccessContext:
    """Тесты set_access_context и set_access_level."""

    def test_set_access_context_stores_level(self, manager):
        """
        Given: WindowManager
        When: set_access_context(AccessContext(level=5))
        Then: _access_level == 5, _access_context.level == 5
        """
        ctx = AccessContext(level=5)
        manager.set_access_context(ctx)

        assert manager._access_level == 5
        assert manager._access_context.level == 5

    def test_set_access_context_emits_signal(self, manager, qtbot):
        """
        Given: WindowManager
        When: set_access_context(ctx)
        Then: сигнал update_access_context эмитируется с ctx
        """
        received = []
        manager.update_access_context.connect(lambda c: received.append(c))

        ctx = AccessContext(level=3)
        manager.set_access_context(ctx)

        assert len(received) == 1
        assert received[0] is ctx

    def test_set_access_context_calls_update_on_windows_with_new_method(self, manager):
        """
        Given: окно с методом update_access_context создано и зарегистрировано
        When: set_access_context(ctx)
        Then: window.update_access_context(ctx) вызван
        """
        mock_win = _make_mock_window("secure")
        mock_win.update_access_context = MagicMock()
        manager.register("secure", lambda: mock_win, needs_access_level=True)
        manager._registry.create("secure")

        ctx = AccessContext(level=7)
        manager.set_access_context(ctx)

        mock_win.update_access_context.assert_called_once_with(ctx)

    def test_set_access_context_legacy_fallback(self, manager):
        """
        Given: окно только с методом update_access_level (legacy API)
        When: set_access_context(ctx)
        Then: window.update_access_level(ctx.level) вызван
        """
        mock_win = MagicMock(spec=["update_access_level", "show", "hide", "close"])
        mock_win.update_access_level = MagicMock()
        manager.register("legacy_win", lambda: mock_win, needs_access_level=True)
        manager._registry.create("legacy_win")

        ctx = AccessContext(level=4)
        manager.set_access_context(ctx)

        mock_win.update_access_level.assert_called_once_with(4)

    def test_set_access_level_deprecated_warning(self, manager):
        """
        Given: вызов set_access_level(3)
        When: вызывается deprecated метод
        Then: поднимается DeprecationWarning
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            manager.set_access_level(3)

        deprecation_warnings = [w for w in caught if issubclass(w.category, DeprecationWarning)]
        assert len(deprecation_warnings) == 1

    def test_set_access_level_delegates_to_context(self, manager):
        """
        Given: set_access_level(6)
        When: deprecated метод
        Then: _access_level == 6 (делегируется через AccessContext)
        """
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            manager.set_access_level(6)

        assert manager._access_level == 6

    def test_access_level_does_not_call_update_on_no_access_windows(self, manager):
        """
        Given: окно зарегистрировано с needs_access_level=False
        When: set_access_context(ctx)
        Then: update_access_context НЕ вызван на этом окне
        """
        mock_win = _make_mock_window("public")
        mock_win.update_access_context = MagicMock()
        manager.register("public", lambda: mock_win, needs_access_level=False)
        manager._registry.create("public")

        manager.set_access_context(AccessContext(level=9))

        mock_win.update_access_context.assert_not_called()


class TestUpdateConfig:
    """Тесты update_config()."""

    def test_update_config_updates_dict(self, qapp):
        """
        Given: WindowManager с dict-конфигом
        When: update_config({"key": "new_val"})
        Then: _config["key"] == "new_val"
        """
        manager = _make_manager(config={"key": "old_val"})
        manager.update_config({"key": "new_val"})

        assert manager._config["key"] == "new_val"

    def test_update_config_calls_apply_config_on_windows(self, manager):
        """
        Given: окно с методом apply_config создано
        When: update_config(new_cfg)
        Then: window.apply_config(new_cfg) вызван
        """
        mock_win = _make_mock_window("w")
        mock_win.apply_config = MagicMock()
        manager.register("w", lambda: mock_win)
        manager._registry.create("w")

        new_cfg = {"brightness": 80}
        manager.update_config(new_cfg)

        mock_win.apply_config.assert_called_once_with(new_cfg)

    def test_update_config_skips_windows_without_apply_config(self, manager):
        """
        Given: окно без метода apply_config
        When: update_config(new_cfg)
        Then: не поднимается исключение
        """
        mock_win = _make_mock_window("w")
        # mock_win не имеет apply_config в spec
        manager.register("w", lambda: mock_win)
        manager._registry.create("w")

        try:
            manager.update_config({"x": 1})
        except Exception as exc:
            pytest.fail(f"update_config поднял исключение: {exc}")


class TestGetWindow:
    """Тесты get_window()."""

    def test_get_window_returns_created_instance(self, manager):
        """
        Given: окно "main" зарегистрировано и создано
        When: get_window("main")
        Then: возвращается созданный инстанс
        """
        mock_win = _make_mock_window("main")
        manager.register("main", lambda: mock_win)
        manager._registry.create("main")

        result = manager.get_window("main")

        assert result is mock_win

    def test_get_window_returns_none_if_not_created(self, manager):
        """
        Given: окно зарегистрировано, но не создано
        When: get_window(name)
        Then: возвращается None
        """
        manager.register("w", lambda: _make_mock_window())

        assert manager.get_window("w") is None

    def test_get_window_returns_none_for_unknown(self, manager):
        """
        Given: окно не зарегистрировано
        When: get_window("ghost")
        Then: возвращается None
        """
        assert manager.get_window("ghost") is None


class TestShowInitialWindow:
    """Тесты show_initial_window()."""

    def test_show_initial_window_creates_and_shows(self, manager):
        """
        Given: зарегистрировано окно "main"
        When: show_initial_window("main")
        Then: окно создано и show() вызван
        """
        mock_win = _make_mock_window("main")
        manager.register("main", lambda: mock_win)

        manager.show_initial_window("main")

        assert manager._registry.is_created("main")
        mock_win.show.assert_called_once()

    def test_show_initial_window_sets_current(self, manager):
        """
        Given: зарегистрировано окно "loading"
        When: show_initial_window("loading")
        Then: get_current_window_name() == "loading"
        """
        mock_win = _make_mock_window("loading")
        manager.register("loading", lambda: mock_win)

        manager.show_initial_window("loading")

        assert manager.get_current_window_name() == "loading"
