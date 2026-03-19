# multiprocess_prototype/frontend/process.py
"""
GuiProcessFrontend — альтернатива GuiProcess на полном стеке frontend_module.

Использует FrontendManager (run_app, shutdown_app) вместо ручного создания окна.
Функциональность идентична GuiProcess: InspectorWindow, QTimer, все gui_* методы.

Переключение: в main.py или GuiConfig указать class_path GuiProcessFrontend.
"""

from multiprocess_framework.refactored.modules.message_module import MessageAdapter
from multiprocess_framework.refactored.modules.process_module import ProcessModule
from multiprocess_prototype.frontend.mixins import GuiProcessMixin


class GuiProcessFrontend(GuiProcessMixin, ProcessModule):
    """
    GUI-процесс на frontend_module.

    run() использует FrontendManager → WindowManager.
    Окно создаётся через фабрику, QTimer настраивается при создании окна.
    gui_* и _handle_* методы — из GuiProcessMixin.
    """

    def _init_application_threads(self):
        """GUI без воркеров."""
        self._log_info("GuiProcessFrontend initializing...")
        self._msg = MessageAdapter(sender=self.name)
        app_cfg = self.get_config("config") or {}
        self._poll_interval = app_cfg.get("poll_interval_ms", 16)
        self._window_title = app_cfg.get("window_title", "Inspector Prototype")
        self._window_width = app_cfg.get("window_width", 1024)
        self._window_height = app_cfg.get("window_height", 600)
        self._camera_type = app_cfg.get("camera_type", "simulator")
        self._log_info("GuiProcessFrontend ready (frontend_module stack)")

    def _init_system_threads(self):
        pass

    def _stop_system_threads(self):
        pass

    def run(self):
        """Основной цикл через FrontendLauncher."""
        from multiprocess_prototype.frontend.launcher import FrontendLauncher

        app_cfg = self.get_config("config") or {}
        launcher = FrontendLauncher(process_ref=self, app_config=app_cfg)
        launcher.run(initial_window="loading", loading_delay_ms=2000)
