# multiprocess_prototype/backend/processes/gui_process.py
"""
GuiProcess — единственный GUI-процесс прототипа (PyQt5 + frontend_module).

Consumer rendered_frame. QTimer опрашивает сообщения в главном потоке.
run() делегирует в FrontendLauncher (MainWindow, WindowManager, регистры).
"""

from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_prototype.backend.gui_process_mixin import GuiProcessMixin


class GuiProcess(GuiProcessMixin, ProcessModule):
    """
    GUI-процесс: FrontendManager → WindowManager, RegistersManager, QTimer в фабрике main-окна.

    gui_* и _handle_* — GuiProcessMixin.
    """

    def _init_application_threads(self):
        self._log_info("GuiProcess initializing...")
        self._msg = MessageAdapter(sender=self.name)
        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._window_width = app_cfg.get("window_width", 1024)
        self._window_height = app_cfg.get("window_height", 600)
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._log_info("GuiProcess ready (frontend_module stack)")

    def _init_system_threads(self):
        pass

    def _stop_system_threads(self):
        pass

    def run(self):
        from multiprocess_prototype.frontend.launcher import FrontendLauncher

        app_cfg = self.get_config("config") or {}
        launcher = FrontendLauncher(process_ref=self, app_config=app_cfg)
        launcher.run(initial_window="loading", loading_delay_ms=2000)
