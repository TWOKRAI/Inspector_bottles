# multiprocess_prototype/backend/processes/gui_process.py
"""
GuiProcess — отображение видео и управление (PyQt5).

Consumer rendered_frame. QTimer для опроса сообщений в главном потоке.
Без воркеров — PyQt в главном потоке.

Интеграция с frontend_module:
- Создаёт FrontendManager с RegistersManager (DrawRegisters) и connection_map
- process.frontend_manager — для доступа к регистрам и конфигу
- Виджеты могут использовать registers для связи с backend (set_field_value → send)
"""

import sys

from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_prototype.frontend.mixins import GuiProcessMixin


def _create_frontend_manager(process: "GuiProcess", app_cfg: dict):
    """Создать FrontendManager с регистрами и connection_map для GuiProcess."""
    try:
        from frontend_module import FrontendManager
        from multiprocess_prototype.registers import create_registers

        registers, connection_map = create_registers()
        config = {
            "window": app_cfg,
            **app_cfg,
        }
        fm = FrontendManager(
            manager_name="GuiFrontend",
            config=config,
            registers=registers,
            router=process,
            connection_map=connection_map,
        )
        fm.initialize()
        return fm
    except ImportError:
        return None


class GuiProcess(GuiProcessMixin, ProcessModule):
    """
    GUI-процесс с PyQt5.

    run() запускает QApplication.exec_() — блокирующий вызов.
    QTimer опрашивает входящие сообщения. Воркеры не создаются.
    gui_* и _handle_* методы — из GuiProcessMixin.
    """

    def _init_application_threads(self):
        """GUI без воркеров — только конфиг."""
        self._log_info("GuiProcess initializing...")

        self._msg = MessageAdapter(sender=self.name)

        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._window_width = app_cfg.get("window_width", 1024)
        self._window_height = app_cfg.get("window_height", 600)
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._log_info("GuiProcess ready (no workers)")

    def _init_system_threads(self):
        """GUI не использует message_processor — опрос через QTimer в главном потоке."""
        pass

    def _stop_system_threads(self):
        """Нет системных потоков для остановки."""
        pass

    def run(self):
        """Основной цикл GUI — QApplication.exec_()."""
        from PyQt5.QtWidgets import QApplication
        from PyQt5.QtCore import QTimer

        from multiprocess_prototype.frontend.windows.inspector_window import InspectorWindow

        app = QApplication(sys.argv)

        app_cfg = self.get_config("config") or {}
        try:
            self._frontend_manager = _create_frontend_manager(self, app_cfg)
        except Exception:
            self._frontend_manager = None

        app.aboutToQuit.connect(self.gui_request_shutdown)

        self._window = InspectorWindow(
            title=self._window_title,
            width=self._window_width,
            height=self._window_height,
            process=self,
            camera_type=self._camera_type,
        )
        self._window.show()

        self._timer = QTimer()
        self._timer.timeout.connect(self._poll_messages)
        self._timer.start(self._poll_interval)

        self._stop_timer = QTimer()
        self._stop_timer.timeout.connect(lambda: self._check_stop(app))
        self._stop_timer.start(100)

        app.exec_()

        if self._frontend_manager:
            self._frontend_manager.shutdown()
