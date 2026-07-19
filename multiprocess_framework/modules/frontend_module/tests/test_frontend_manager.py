# -*- coding: utf-8 -*-
"""
LEGACY Gen-1 (frozen 2026-07-18) — unit-тесты FrontendManager (Task C1).

Покрываем: initialize, shutdown, run_app, shutdown_app,
_on_config_changed, update_config, set_connection_map, set_router,
getters (get_registers, get_window_manager, get_thread_manager, get_config),
get_stats.

Все Qt-зависимости (QApplication, WindowManager, ThreadManager) замокированы
через unittest.mock.patch / MagicMock, что позволяет запускать тесты без дисплея.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from multiprocess_framework.modules.frontend_module.application.frontend_manager import FrontendManager

pytestmark = pytest.mark.legacy_gen1


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_mock_registers_manager() -> MagicMock:
    """Минимальный мок RegistersManager."""
    rm = MagicMock()
    rm.register_names.return_value = []
    rm.set_send_callback.return_value = None
    rm.set_connection.return_value = None
    return rm


def _make_mock_bridge() -> MagicMock:
    """Мок FrontendRegistersBridge."""
    bridge = MagicMock()
    bridge.register_names.return_value = []
    bridge.set_connection_map.return_value = None
    bridge.set_router.return_value = None
    return bridge


def _make_mock_window_manager() -> MagicMock:
    """Мок WindowManager."""
    wm = MagicMock()
    wm.close_all.return_value = None
    wm.show_initial_window.return_value = None
    wm.update_config.return_value = None
    # _registry.list_windows() — для get_stats
    wm._registry.list_windows.return_value = []
    return wm


def _make_mock_thread_manager() -> MagicMock:
    """Мок ThreadManager."""
    tm = MagicMock()
    tm.stop_all.return_value = None
    tm.create_all.return_value = None
    tm.start_all.return_value = None
    return tm


def _make_mock_qt_app() -> MagicMock:
    """Мок QApplication."""
    app = MagicMock()
    app.exec.return_value = 0
    return app


# ---------------------------------------------------------------------------
# Фикстура: полностью замокированный FrontendManager после initialize
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_manager():
    """
    Возвращает FrontendManager с замоканными Qt и внутренними зависимостями.
    initialize() уже вызван и вернул True.
    """
    mock_registers_raw = _make_mock_registers_manager()
    mock_qt_app = _make_mock_qt_app()

    with (
        patch(
            "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
            return_value=_make_mock_bridge(),
        ) as MockBridge,
        patch(
            "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
            return_value=_make_mock_window_manager(),
        ) as MockWM,
        patch(
            "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
            return_value=_make_mock_thread_manager(),
        ) as MockTM,
        patch(
            "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
        ) as MockQApp,
    ):
        # instance() возвращает None → создаём новый экземпляр
        MockQApp.instance.return_value = None
        MockQApp.return_value = mock_qt_app

        manager = FrontendManager(
            manager_name="TestFrontend",
            registers=mock_registers_raw,
        )
        result = manager.initialize()

        assert result is True, "Фикстура: initialize должен вернуть True"

        yield manager, MockBridge, MockWM, MockTM, MockQApp


# ---------------------------------------------------------------------------
# test_initialize_sets_managers: проверяем, что атрибуты заполнены после initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    def test_initialize_sets_managers(self):
        """
        Given: FrontendManager с замоканными зависимостями
        When: вызываем initialize()
        Then: _registers_bridge, _window_manager, _thread_manager, _qt_app заполнены,
              is_initialized == True
        """
        mock_registers_raw = _make_mock_registers_manager()
        mock_qt_app = _make_mock_qt_app()

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            MockQApp.instance.return_value = None
            MockQApp.return_value = mock_qt_app

            manager = FrontendManager(
                manager_name="TestFrontend",
                registers=mock_registers_raw,
            )
            result = manager.initialize()

        # --- проверки ---
        assert result is True
        assert manager.is_initialized is True
        assert manager._registers_bridge is not None
        assert manager._window_manager is not None
        assert manager._thread_manager is not None
        assert manager._qt_app is not None

    def test_initialize_attaches_adapters(self):
        """
        Given: FrontendManager
        When: initialize()
        Then: адаптеры 'registers', 'window_manager', 'thread_manager' прикреплены
        """
        mock_registers_raw = _make_mock_registers_manager()

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            MockQApp.instance.return_value = None
            MockQApp.return_value = _make_mock_qt_app()

            manager = FrontendManager(registers=mock_registers_raw)
            manager.initialize()

        adapters = manager.list_adapters()
        assert "registers" in adapters
        assert "window_manager" in adapters
        assert "thread_manager" in adapters

    def test_initialize_without_process_does_not_raise(self):
        """
        Given: FrontendManager без process
        When: initialize()
        Then: не бросает исключение, возвращает True
        """
        mock_registers_raw = _make_mock_registers_manager()

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            MockQApp.instance.return_value = None
            MockQApp.return_value = _make_mock_qt_app()

            # process=None (по умолчанию)
            manager = FrontendManager(process=None, registers=mock_registers_raw)
            result = manager.initialize()

        assert result is True

    def test_initialize_uses_existing_qt_app(self):
        """
        Given: QApplication.instance() уже возвращает существующий экземпляр
        When: initialize()
        Then: новый QApplication не создаётся — используется существующий
        """
        mock_registers_raw = _make_mock_registers_manager()
        existing_app = _make_mock_qt_app()

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            # Уже есть экземпляр — не создаём новый
            MockQApp.instance.return_value = existing_app

            manager = FrontendManager(registers=mock_registers_raw)
            manager.initialize()

        # Конструктор QApplication вызван НЕ должен быть
        MockQApp.assert_not_called()
        assert manager._qt_app is existing_app

    def test_initialize_with_config_manager(self):
        """
        Given: в managers передан config_mgr с get_config
        When: initialize()
        Then: конфиг обновляется из ConfigManager, subscribe вызывается
        """
        mock_registers_raw = _make_mock_registers_manager()
        mock_cfg_obj = MagicMock()
        mock_cfg_obj.data = {"theme": "dark"}
        mock_cfg_obj.subscribe = MagicMock()

        mock_config_mgr = MagicMock()
        mock_config_mgr.get_config.return_value = mock_cfg_obj

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            MockQApp.instance.return_value = None
            MockQApp.return_value = _make_mock_qt_app()

            manager = FrontendManager(
                registers=mock_registers_raw,
                managers={"config": mock_config_mgr},
            )
            manager.initialize()

        # subscribe был вызван для hot-reload
        mock_cfg_obj.subscribe.assert_called_once()
        # конфиг обновлён
        assert manager._config.get("theme") == "dark"


# ---------------------------------------------------------------------------
# test_shutdown_calls_cleanup: проверяем вызов teardown-методов
# ---------------------------------------------------------------------------


class TestShutdown:
    def test_shutdown_calls_cleanup(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: shutdown()
        Then: thread_manager.stop_all() и window_manager.close_all() вызваны,
              is_initialized == False
        """
        # Given
        manager, _, _, _, _ = patched_manager
        wm = manager._window_manager
        tm = manager._thread_manager

        # When
        result = manager.shutdown()

        # Then
        assert result is True
        assert manager.is_initialized is False
        tm.stop_all.assert_called_once()
        wm.close_all.assert_called_once()

    def test_shutdown_clears_references(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: shutdown()
        Then: _registers_bridge, _window_manager, _thread_manager = None
        """
        manager, _, _, _, _ = patched_manager
        manager.shutdown()

        assert manager._registers_bridge is None
        assert manager._window_manager is None
        assert manager._thread_manager is None

    def test_shutdown_unsubscribes_config(self, patched_manager):
        """
        Given: FrontendManager с config_obj
        When: shutdown()
        Then: config_obj.unsubscribe вызывается
        """
        manager, _, _, _, _ = patched_manager
        mock_cfg_obj = MagicMock()
        manager._config_obj = mock_cfg_obj

        manager.shutdown()

        mock_cfg_obj.unsubscribe.assert_called_once_with(manager._on_config_changed, "*")


# ---------------------------------------------------------------------------
# test_run_app_calls_window_manager: run_app вызывает window_manager.show_initial_window
# ---------------------------------------------------------------------------


class TestRunApp:
    def test_run_app_calls_window_manager(self, patched_manager):
        """
        Given: инициализированный FrontendManager с замоканным qt_app
        When: run_app("main")
        Then: thread_manager.create_all, start_all и window_manager.show_initial_window("main") вызваны
        """
        manager, _, _, _, _ = patched_manager
        wm = manager._window_manager
        tm = manager._thread_manager

        manager.run_app("main")

        tm.create_all.assert_called_once()
        tm.start_all.assert_called_once()
        wm.show_initial_window.assert_called_once_with("main")

    def test_run_app_returns_exit_code(self, patched_manager):
        """
        Given: qt_app.exec() возвращает 0
        When: run_app()
        Then: возвращается 0
        """
        manager, _, _, _, _ = patched_manager
        manager._qt_app.exec.return_value = 0

        code = manager.run_app()

        assert code == 0

    def test_run_app_without_init_calls_initialize(self):
        """
        Given: не инициализированный FrontendManager
        When: run_app() без предварительного initialize()
        Then: initialize() вызывается автоматически
        """
        mock_registers_raw = _make_mock_registers_manager()
        mock_qt_app = _make_mock_qt_app()

        with (
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.FrontendRegistersBridge",
                return_value=_make_mock_bridge(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.WindowManager",
                return_value=_make_mock_window_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.ThreadManager",
                return_value=_make_mock_thread_manager(),
            ),
            patch(
                "multiprocess_framework.modules.frontend_module.application.frontend_manager.QApplication",
            ) as MockQApp,
        ):
            MockQApp.instance.return_value = None
            MockQApp.return_value = mock_qt_app

            manager = FrontendManager(registers=mock_registers_raw)
            assert manager.is_initialized is False

            manager.run_app()

        # После run_app — менеджер должен быть инициализирован
        assert manager.is_initialized is True

    def test_run_app_returns_1_when_no_qt_app(self, patched_manager):
        """
        Given: _qt_app = None (например Qt недоступен)
        When: run_app()
        Then: возвращается 1 (ошибка)
        """
        manager, _, _, _, _ = patched_manager
        manager._qt_app = None

        code = manager.run_app()

        assert code == 1


# ---------------------------------------------------------------------------
# test_shutdown_app: останавливает приложение и флаг _is_running
# ---------------------------------------------------------------------------


class TestShutdownApp:
    def test_shutdown_app_calls_shutdown(self, patched_manager):
        """
        Given: _is_running = True
        When: shutdown_app()
        Then: shutdown() вызывается, _is_running = False
        """
        manager, _, _, _, _ = patched_manager
        manager._is_running = True

        with patch.object(manager, "shutdown", wraps=manager.shutdown) as mock_shutdown:
            manager.shutdown_app()

        mock_shutdown.assert_called_once()
        assert manager._is_running is False

    def test_shutdown_app_sets_stop_event(self, patched_manager):
        """
        Given: _stop_event с методом set()
        When: shutdown_app()
        Then: _stop_event.set() вызывается
        """
        manager, _, _, _, _ = patched_manager
        manager._is_running = True
        stop_event = MagicMock()
        manager._stop_event = stop_event

        manager.shutdown_app()

        stop_event.set.assert_called_once()

    def test_shutdown_app_no_op_when_not_running(self, patched_manager):
        """
        Given: _is_running = False
        When: shutdown_app()
        Then: shutdown() не вызывается
        """
        manager, _, _, _, _ = patched_manager
        manager._is_running = False

        with patch.object(manager, "shutdown") as mock_shutdown:
            manager.shutdown_app()

        mock_shutdown.assert_not_called()


# ---------------------------------------------------------------------------
# test_config_hotreload: _on_config_changed обновляет конфиг и уведомляет WindowManager
# ---------------------------------------------------------------------------


class TestConfigHotReload:
    def test_on_config_changed_updates_config(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: _on_config_changed вызывается (hot-reload)
        Then: _config обновляется через _get_full_config
        """
        manager, _, _, _, _ = patched_manager
        manager._config = {"old_key": "old_value"}

        with patch.object(manager, "_get_full_config", return_value={"new_key": "new_value"}):
            manager._on_config_changed("new_key", None, "new_value")

        assert manager._config == {"new_key": "new_value"}

    def test_on_config_changed_calls_window_manager_update(self, patched_manager):
        """
        Given: инициализированный FrontendManager с window_manager
        When: _on_config_changed вызывается
        Then: window_manager.update_config вызывается с новым конфигом
        """
        manager, _, _, _, _ = patched_manager
        wm = manager._window_manager
        new_config = {"brightness": 80}

        with patch.object(manager, "_get_full_config", return_value=new_config):
            manager._on_config_changed("brightness", 60, 80)

        wm.update_config.assert_called_once_with(new_config)

    def test_on_config_changed_no_window_manager(self, patched_manager):
        """
        Given: _window_manager = None
        When: _on_config_changed вызывается
        Then: не бросает исключение
        """
        manager, _, _, _, _ = patched_manager
        manager._window_manager = None

        with patch.object(manager, "_get_full_config", return_value={}):
            # Не должно бросать
            manager._on_config_changed("key", None, "value")


# ---------------------------------------------------------------------------
# test_update_config: ручное обновление конфига
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_update_config_updates_internal_config(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: update_config({"theme": "dark"})
        Then: _config["theme"] == "dark"
        """
        manager, _, _, _, _ = patched_manager
        manager._config = {"theme": "light"}

        manager.update_config({"theme": "dark"})

        assert manager._config["theme"] == "dark"

    def test_update_config_calls_window_manager(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: update_config(new_config)
        Then: window_manager.update_config(new_config) вызывается
        """
        manager, _, _, _, _ = patched_manager
        wm = manager._window_manager
        new_cfg = {"resolution": "1080p"}

        manager.update_config(new_cfg)

        wm.update_config.assert_called_with(manager._config)


# ---------------------------------------------------------------------------
# test_set_connection_map: обновление карты соединений
# ---------------------------------------------------------------------------


class TestSetConnectionMap:
    def test_set_connection_map_updates_bridge(self, patched_manager):
        """
        Given: инициализированный FrontendManager с bridge
        When: set_connection_map({"reg": "chan"})
        Then: bridge.set_connection_map вызывается с новой картой
        """
        manager, _, _, _, _ = patched_manager
        bridge = manager._registers_bridge
        new_map = {"register_x": "channel_y"}

        manager.set_connection_map(new_map)

        bridge.set_connection_map.assert_called_once_with(new_map)

    def test_set_connection_map_updates_internal_state(self, patched_manager):
        """
        Given: FrontendManager
        When: set_connection_map({"reg": "chan"})
        Then: _connection_map обновлён
        """
        manager, _, _, _, _ = patched_manager
        new_map = {"reg": "chan"}

        manager.set_connection_map(new_map)

        assert manager._connection_map == new_map


# ---------------------------------------------------------------------------
# test_set_router: обновление router
# ---------------------------------------------------------------------------


class TestSetRouter:
    def test_set_router_updates_bridge(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: set_router(new_router)
        Then: bridge.set_router(new_router) вызывается
        """
        manager, _, _, _, _ = patched_manager
        bridge = manager._registers_bridge
        new_router = MagicMock()

        manager.set_router(new_router)

        bridge.set_router.assert_called_once_with(new_router)

    def test_set_router_updates_internal_state(self, patched_manager):
        """
        Given: FrontendManager
        When: set_router(router)
        Then: _router обновлён
        """
        manager, _, _, _, _ = patched_manager
        new_router = MagicMock()

        manager.set_router(new_router)

        assert manager._router is new_router


# ---------------------------------------------------------------------------
# test getters: get_registers, get_window_manager, get_thread_manager, get_config
# ---------------------------------------------------------------------------


class TestGetters:
    def test_get_registers_returns_bridge(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: get_registers()
        Then: возвращает _registers_bridge
        """
        manager, _, _, _, _ = patched_manager
        result = manager.get_registers()
        assert result is manager._registers_bridge

    def test_get_window_manager_returns_manager(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: get_window_manager()
        Then: возвращает _window_manager
        """
        manager, _, _, _, _ = patched_manager
        result = manager.get_window_manager()
        assert result is manager._window_manager

    def test_get_thread_manager_returns_manager(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: get_thread_manager()
        Then: возвращает _thread_manager
        """
        manager, _, _, _, _ = patched_manager
        result = manager.get_thread_manager()
        assert result is manager._thread_manager

    def test_get_config_returns_full_config(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: get_config()
        Then: возвращает dict
        """
        manager, _, _, _, _ = patched_manager
        manager._config = {"key": "value"}

        result = manager.get_config()

        assert isinstance(result, dict)

    def test_qt_app_property(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: обращение к свойству qt_app
        Then: возвращает _qt_app
        """
        manager, _, _, _, _ = patched_manager
        assert manager.qt_app is manager._qt_app


# ---------------------------------------------------------------------------
# test_get_stats: статистика менеджера
# ---------------------------------------------------------------------------


class TestGetStats:
    def test_get_stats_returns_dict(self, patched_manager):
        """
        Given: инициализированный FrontendManager
        When: get_stats()
        Then: возвращает dict с ключами manager_name и is_initialized
        """
        manager, _, _, _, _ = patched_manager
        stats = manager.get_stats()

        assert isinstance(stats, dict)
        assert "manager_name" in stats
        assert "is_initialized" in stats

    def test_get_stats_includes_registers_count(self, patched_manager):
        """
        Given: bridge.register_names() возвращает 2 регистра
        When: get_stats()
        Then: stats["registers_count"] == 2
        """
        manager, _, _, _, _ = patched_manager
        manager._registers_bridge.register_names.return_value = ["reg_a", "reg_b"]

        stats = manager.get_stats()

        assert stats["registers_count"] == 2

    def test_get_stats_includes_windows_count(self, patched_manager):
        """
        Given: window_manager._registry.list_windows() возвращает 3 окна
        When: get_stats()
        Then: stats["windows_registered"] == 3
        """
        manager, _, _, _, _ = patched_manager
        manager._window_manager._registry.list_windows.return_value = ["w1", "w2", "w3"]

        stats = manager.get_stats()

        assert stats["windows_registered"] == 3

    def test_get_stats_without_bridge(self, patched_manager):
        """
        Given: _registers_bridge = None
        When: get_stats()
        Then: stats["registers_count"] == 0 (не бросает)
        """
        manager, _, _, _, _ = patched_manager
        manager._registers_bridge = None

        stats = manager.get_stats()

        assert stats["registers_count"] == 0


# ---------------------------------------------------------------------------
# test_default_name: имя менеджера по умолчанию
# ---------------------------------------------------------------------------


class TestDefaultValues:
    def test_default_manager_name(self):
        """
        Given: FrontendManager без явного имени
        When: создан
        Then: manager_name == "FrontendManager"
        """
        manager = FrontendManager()
        assert manager.manager_name == "FrontendManager"

    def test_not_initialized_by_default(self):
        """
        Given: FrontendManager создан
        When: без вызова initialize()
        Then: is_initialized == False
        """
        manager = FrontendManager()
        assert manager.is_initialized is False

    def test_config_passed_in_constructor(self):
        """
        Given: config передан в конструктор
        When: создан FrontendManager(config={"key": "val"})
        Then: _config["key"] == "val"
        """
        manager = FrontendManager(config={"key": "val"})
        assert manager._config["key"] == "val"

    def test_connection_map_passed_in_constructor(self):
        """
        Given: connection_map передан в конструктор
        When: создан
        Then: _connection_map содержит переданные данные
        """
        cmap = {"reg_a": "chan_1"}
        manager = FrontendManager(connection_map=cmap)
        assert manager._connection_map == cmap
