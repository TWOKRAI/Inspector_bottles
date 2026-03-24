# -*- coding: utf-8 -*-
"""
FrontendManager — единая точка входа для frontend (BaseManager + ObservableMixin).

Координирует: регистры, конфигурацию, окна, потоки.
Интегрируется с config_module (подписка на изменения для hot-reload),
logger_module, router_module.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from base_manager import BaseManager, ObservableMixin

from frontend_module.core.qt_imports import QApplication
from registers_module import RegistersManager as RegistersManagerClass
from frontend_module.application.thread_manager import ThreadManager
from frontend_module.application.window_manager import WindowManager
from frontend_module.core.registers_bridge import FrontendRegistersBridge

_CONFIG_CHANGED_EVENT = "config_changed"


class FrontendManager(BaseManager, ObservableMixin):
    """
    Менеджер frontend. BaseManager + ObservableMixin для интеграции с фреймворком.

    Адаптеры: registers, window_manager, thread_manager
    Managers (ObservableMixin): logger, stats, error, config, router

    Конфигурация:
    - config: dict — передаётся при initialize или создаётся из ConfigManager
    - subscribe на config_module — при изменении → emit config_changed, обновление UI
    """

    def __init__(
        self,
        manager_name: str = "FrontendManager",
        process: Optional[Any] = None,
        managers: Optional[Dict[str, Any]] = None,
        config: Optional[Dict[str, Any]] = None,
        registers: Optional[Any] = None,
        router: Optional[Any] = None,
        connection_map: Optional[Dict[str, str]] = None,
        queue_manager: Optional[Any] = None,
        stop_event: Optional[Any] = None,
        **kwargs: Any,
    ):
        BaseManager.__init__(self, manager_name=manager_name, process=process)
        ObservableMixin.__init__(self, managers=managers or {}, config={}, auto_proxy=True, **kwargs)

        self._config: Dict[str, Any] = dict(config) if config else {}
        self._registers_raw: Optional[Any] = registers
        self._registers_bridge: Optional[FrontendRegistersBridge] = None
        self._window_manager: Optional[Any] = None
        self._thread_manager: Optional[Any] = None
        self._router = router
        self._connection_map = dict(connection_map) if connection_map else {}
        self._queue_manager = queue_manager
        self._stop_event = stop_event
        self._config_obj: Optional[Any] = None
        self._qt_app: Optional[Any] = None
        self._is_running = False

    def initialize(self) -> bool:
        try:
            # 1. Регистры
            if self._registers_raw is None:
                self._registers_raw = RegistersManagerClass()
            self._registers_bridge = FrontendRegistersBridge(
                registers_manager=self._registers_raw,
                router=self._get_router(),
                process_name=self.manager_name,
                connection_map=self._connection_map,
            )
            self.attach_adapter(self._registers_bridge, "registers")

            # 2. Конфиг из ConfigManager (если есть) + подписка для hot-reload
            config_mgr = self.get_manager("config") if hasattr(self, "get_manager") else None
            if config_mgr and hasattr(config_mgr, "get_config"):
                cfg = config_mgr.get_config("frontend")
                if cfg is None and hasattr(config_mgr, "create_config"):
                    cfg = config_mgr.create_config("frontend", initial_data=self._config)
                if cfg is not None:
                    self._config_obj = cfg
                    data = cfg.data if hasattr(cfg, "data") else {}
                    self._config.update(data)
                    if hasattr(cfg, "subscribe"):
                        cfg.subscribe(callback=self._on_config_changed, key="*")

            # 3. WindowManager и ThreadManager (IConfig или dict)
            wm_config = self._config_obj if self._config_obj is not None else self._config
            self._window_manager = WindowManager(
                config=wm_config,
                registers_manager=self._registers_bridge,
            )
            self._thread_manager = ThreadManager(
                queue_manager=self._queue_manager,
                stop_event=self._stop_event,
            )
            self.attach_adapter(self._window_manager, "window_manager")
            self.attach_adapter(self._thread_manager, "thread_manager")

            # QApplication для run_app
            self._qt_app = QApplication.instance()
            if self._qt_app is None:
                self._qt_app = QApplication(sys.argv)

            self.is_initialized = True
            self._log_info(f"FrontendManager '{self.manager_name}' initialized", module="frontend_module")
            return True
        except Exception as exc:
            self._log_error(f"FrontendManager initialization failed: {exc}", module="frontend_module")
            return False

    def shutdown(self) -> bool:
        try:
            if self._config_obj is not None and hasattr(self._config_obj, "unsubscribe"):
                self._config_obj.unsubscribe(self._on_config_changed, "*")
                self._config_obj = None

            if self._thread_manager and hasattr(self._thread_manager, "stop_all"):
                self._thread_manager.stop_all()
            if self._window_manager and hasattr(self._window_manager, "close_all"):
                self._window_manager.close_all()

            self._registers_bridge = None
            self._window_manager = None
            self._thread_manager = None
            self.is_initialized = False
            self._log_info(f"FrontendManager '{self.manager_name}' shut down", module="frontend_module")
            return True
        except Exception as exc:
            self._log_error(f"FrontendManager shutdown error: {exc}", module="frontend_module")
            return False

    def _get_router(self) -> Optional[Any]:
        if self._router is not None:
            return self._router
        return self.get_manager("router") if hasattr(self, "get_manager") else None

    def _on_config_changed(self, key: str, old_value: Any, new_value: Any) -> None:
        """Вызывается при изменении конфига (hot-reload)."""
        self._config = self._get_full_config()
        self.emit_event(_CONFIG_CHANGED_EVENT, {"key": key, "old": old_value, "new": new_value})
        if self._window_manager and hasattr(self._window_manager, "update_config"):
            self._window_manager.update_config(self._config)

    def _get_full_config(self) -> Dict[str, Any]:
        config_mgr = self.get_manager("config") if hasattr(self, "get_manager") else None
        if config_mgr and hasattr(config_mgr, "get_config"):
            cfg = config_mgr.get_config("frontend")
            if cfg is not None and hasattr(cfg, "data"):
                return dict(cfg.data)
        return dict(self._config)

    def update_config(self, config: Dict[str, Any]) -> None:
        """Обновить конфиг вручную (без ConfigManager)."""
        self._config.update(config)
        if self._window_manager and hasattr(self._window_manager, "update_config"):
            self._window_manager.update_config(self._config)

    def set_connection_map(self, connection_map: Dict[str, str]) -> None:
        self._connection_map = dict(connection_map)
        if self._registers_bridge:
            self._registers_bridge.set_connection_map(self._connection_map)

    def set_router(self, router: Any) -> None:
        self._router = router
        if self._registers_bridge:
            self._registers_bridge.set_router(router)

    def get_registers(self) -> Any:
        return self._registers_bridge

    def get_window_manager(self) -> Optional[Any]:
        return self._window_manager

    def get_thread_manager(self) -> Optional[Any]:
        return self._thread_manager

    def get_config(self) -> Dict[str, Any]:
        return self._get_full_config()

    def get_stats(self) -> Dict[str, Any]:
        stats = super().get_stats()
        stats["registers_count"] = len(self._registers_bridge.register_names()) if self._registers_bridge else 0
        stats["windows_registered"] = (
            len(self._window_manager._registry.list_windows())
            if self._window_manager and hasattr(self._window_manager, "_registry")
            else 0
        )
        return stats

    @property
    def qt_app(self) -> Optional[Any]:
        """QApplication (создаётся в initialize)."""
        return self._qt_app

    def run_app(self, initial_window: str = "main") -> int:
        """Запуск главного цикла. Блокирующий. Возвращает exit code."""
        if not self.is_initialized:
            if not self.initialize():
                return 1
        self._is_running = True
        tm = self.get_thread_manager()
        wm = self.get_window_manager()
        if tm:
            tm.create_all()
            tm.start_all()
        if wm:
            wm.show_initial_window(initial_window)
        return self._qt_app.exec_() if self._qt_app else 1

    def shutdown_app(self) -> None:
        """Остановка приложения: shutdown + stop_event."""
        if not self._is_running:
            return
        self.shutdown()
        stop_ev = getattr(self, "_stop_event", None)
        if stop_ev and hasattr(stop_ev, "set"):
            stop_ev.set()
        self._is_running = False
