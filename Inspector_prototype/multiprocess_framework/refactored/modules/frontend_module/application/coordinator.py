# -*- coding: utf-8 -*-
"""
ApplicationCoordinator — фасад приложения, делегирует в FrontendManager.

Инициализация: FrontendManager (регистры, конфиг, окна, потоки).
Приложение регистрирует окна и потоки через window_manager/thread_manager.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

try:
    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import QObject, pyqtSignal
    _HAS_QT = True
except ImportError:
    _HAS_QT = False

if _HAS_QT:
    from frontend_module.application.window_manager import WindowManager
    from frontend_module.application.thread_manager import ThreadManager
    from frontend_module.application.frontend_manager import FrontendManager


if _HAS_QT:

    class ApplicationCoordinator(QObject):
        """
        Фасад приложения. Делегирует в FrontendManager.
        1. initialize() — создаёт FrontendManager
        2. Регистрирует окна и потоки через window_manager/thread_manager
        3. run() — запуск главного цикла
        """
        initialized = pyqtSignal()
        started = pyqtSignal()
        shutting_down = pyqtSignal()
        finished = pyqtSignal()

        def __init__(
            self,
            queue_manager: Optional[Any] = None,
            stop_event: Optional[Any] = None,
            config_path: Optional[Path] = None,
            config: Optional[Dict[str, Any]] = None,
            parent=None,
        ):
            super().__init__(parent)
            self._queue_manager = queue_manager
            self._stop_event = stop_event
            self._config_path = config_path
            self._config: Dict[str, Any] = config or {}
            self._frontend_manager: Optional[FrontendManager] = None
            self._qt_app: Optional[QApplication] = None
            self._is_initialized = False
            self._is_running = False

        def initialize(
            self,
            config: Optional[Dict[str, Any]] = None,
            registers: Optional[Any] = None,
            router: Optional[Any] = None,
            connection_map: Optional[Dict[str, str]] = None,
            managers: Optional[Dict[str, Any]] = None,
        ) -> bool:
            """
            Инициализация FrontendManager.
            Приложение передаёт config, registers, router, connection_map, managers.
            """
            if self._is_initialized:
                return True
            try:
                if config is not None:
                    self._config = config
                self._qt_app = QApplication.instance()
                if self._qt_app is None:
                    import sys
                    self._qt_app = QApplication(sys.argv)

                self._frontend_manager = FrontendManager(
                    manager_name="FrontendManager",
                    managers=managers or {},
                    config=self._config,
                    registers=registers,
                    router=router,
                    connection_map=connection_map or {},
                )
                self._frontend_manager._queue_manager = self._queue_manager
                self._frontend_manager._stop_event = self._stop_event
                if not self._frontend_manager.initialize():
                    return False
                self._is_initialized = True
                self.initialized.emit()
                return True
            except Exception as e:
                print(f"[Coordinator] Initialization failed: {e}")
                import traceback
                traceback.print_exc()
                return False

        def run(self, initial_window: str = "main") -> int:
            """Запуск главного цикла. Блокирующий."""
            if not self._is_initialized:
                if not self.initialize():
                    return 1
            self._is_running = True
            fm = self._frontend_manager
            if fm:
                tm = fm.get_thread_manager()
                wm = fm.get_window_manager()
                if tm:
                    tm.create_all()
                    tm.start_all()
                if wm:
                    wm.show_initial_window(initial_window)
            self.started.emit()
            return self._qt_app.exec_()

        def shutdown(self) -> None:
            if not self._is_running:
                return
            self.shutting_down.emit()
            if self._frontend_manager:
                self._frontend_manager.shutdown()
            if self._stop_event:
                self._stop_event.set()
            self._is_running = False
            self.finished.emit()

        @property
        def config(self) -> Dict[str, Any]:
            return self._frontend_manager.get_config() if self._frontend_manager else self._config

        @property
        def registers(self) -> Optional[Any]:
            return self._frontend_manager.get_registers() if self._frontend_manager else None

        @property
        def window_manager(self) -> Optional[WindowManager]:
            return self._frontend_manager.get_window_manager() if self._frontend_manager else None

        @property
        def thread_manager(self) -> Optional[ThreadManager]:
            return self._frontend_manager.get_thread_manager() if self._frontend_manager else None

        @property
        def frontend_manager(self) -> Optional[FrontendManager]:
            return self._frontend_manager

        def __enter__(self):
            self.initialize()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            self.shutdown()
            return False

else:
    ApplicationCoordinator = None  # type: ignore
