# multiprocess_prototype/frontend/launcher.py
"""
FrontendLauncher — конструктор frontend.

Собирает конфиги, регистры, окна по аналогии с SystemLauncher.
GuiProcessFrontend делегирует run() в launcher.
"""

from typing import Any, Dict, Optional

from frontend_module import FrontendManager
from frontend_module.windows import LoadingWindow

from multiprocess_prototype.registers import create_registers
from multiprocess_prototype.frontend.configs.frontend_config import build_frontend_config
from multiprocess_prototype.frontend.commands import GuiCommandHandler
from multiprocess_prototype.frontend.windows.main_window import MainWindow


class FrontendLauncher:
    """
    Конструктор frontend: config, registers, windows.

    run() создаёт FrontendManager, инициализирует, запускает приложение.
    """

    def __init__(self, process_ref: Any, app_config: Dict[str, Any]):
        """
        Args:
            process_ref: GuiProcessFrontend (process с _msg, send_message, get_config).
            app_config: dict из get_config("config").
        """
        self._process = process_ref
        self._app_config = app_config or {}

    def build_config(self) -> Dict[str, Any]:
        """Конфиг для FrontendManager (schema-driven, Dict at Boundary)."""
        return build_frontend_config(self._app_config)

    def build_registers(self):
        """(RegistersManager, connection_map)."""
        return create_registers()

    def build_command_handler(self) -> GuiCommandHandler:
        """GuiCommandHandler для callbacks виджетов."""
        return GuiCommandHandler(self._process)

    def _camera_callbacks(self, cmd: GuiCommandHandler) -> Dict[str, Any]:
        """Callbacks для CameraTabWidget."""
        return {
            "on_start": cmd.send_start_capture,
            "on_stop": cmd.send_stop_capture,
            "on_set_fps": cmd.send_set_fps,
            "on_enum_devices": cmd.send_enum_devices,
            "on_open": lambda camera_index=0: cmd.send_open_camera(camera_index=camera_index),
            "on_close": cmd.send_close_camera,
            "on_start_grabbing": cmd.send_start_grabbing,
            "on_stop_grabbing": cmd.send_stop_grabbing,
            "on_get_parameters": cmd.send_get_parameters,
            "on_set_parameters": lambda fr, exp, gain: cmd.send_set_parameters(fr, exp, gain),
            "on_camera_type_changed": cmd.send_camera_type_changed,
        }

    def _processing_callbacks(self, cmd: GuiCommandHandler) -> Dict[str, Any]:
        """Callbacks для ProcessingTabWidget."""
        return {
            "on_set_color_range": lambda b_l, g_l, r_l, b_u, g_u, r_u: cmd.send_set_color_range(
                b_l, g_l, r_l, b_u, g_u, r_u
            ),
            "on_set_min_area": cmd.send_set_min_area,
            "on_set_max_area": cmd.send_set_max_area,
            "on_set_show_original": cmd.send_set_show_original,
            "on_set_show_mask": cmd.send_set_show_mask,
            "on_set_draw_contours": cmd.send_set_draw_contours,
        }

    def register_windows(
        self,
        window_manager: Any,
        frontend_manager: Any,
        config: Dict[str, Any],
        cmd: GuiCommandHandler,
        app: Any,
    ) -> None:
        """Регистрация фабрик окон в WindowManager."""
        wm = window_manager
        fm = frontend_manager
        process = self._process
        camera_type = config.get("camera_type", "simulator")
        window_cfg = config.get("window", {})
        title = window_cfg.get("title", "Inspector")
        width = window_cfg.get("width", window_cfg.get("min_width", 1024))
        height = window_cfg.get("height", window_cfg.get("min_height", 600))

        def tab_widget_factory(widget_key: str, tab_config: dict):
            from multiprocess_prototype.frontend.widgets import (
                CameraTabWidget,
                ProcessingTabWidget,
                RecipesTabWidget,
                SettingsTabWidget,
            )

            registers = fm.get_registers() if fm else None
            if widget_key == "recipes":
                return RecipesTabWidget(registers_manager=registers)
            if widget_key == "settings":
                st_cfg = config.get("settings_tab", {})
                controls = st_cfg.get("controls", [])
                group_title = st_cfg.get("group_title", "Параметры отображения")
                return SettingsTabWidget(
                    registers_manager=registers,
                    controls_config=controls,
                    group_title=group_title,
                )
            if widget_key == "processing":
                return ProcessingTabWidget(callbacks=self._processing_callbacks(cmd))
            if widget_key == "camera":
                return CameraTabWidget(
                    camera_type=camera_type,
                    callbacks=self._camera_callbacks(cmd),
                )
            return None

        def create_main_window(**kwargs):
            from frontend_module.core.qt_imports import QTimer

            win = MainWindow(
                config=config,
                show_window_callback=wm.show_window if wm else None,
                registers_manager=fm.get_registers() if fm else None,
                camera_callbacks=self._camera_callbacks(cmd),
                processing_callbacks=self._processing_callbacks(cmd),
                camera_type=camera_type,
                tab_widget_factory=tab_widget_factory,
            )
            process._window = win
            process._timer = QTimer()
            process._timer.timeout.connect(process._poll_messages)
            process._timer.start(config.get("poll_interval_ms", 16))
            process._stop_timer = QTimer()
            process._stop_timer.timeout.connect(lambda: process._check_stop(app))
            process._stop_timer.start(100)
            return win

        def create_loading_window(**kwargs):
            return LoadingWindow(
                logo_path=None,
                min_width=400,
                min_height=300,
            )

        # Регистрация окон из конфига (config-driven)
        registry = config.get("window_registry", {
            "main": {"factory_key": "main"},
            "inspector": {"factory_key": "inspector"},
            "loading": {"factory_key": "loading"},
        })
        factories = {
            "main": create_main_window,
            #"inspector": create_inspector_window,
            "loading": create_loading_window,
        }
        for name, entry in registry.items():
            key = entry.get("factory_key", name)
            if key in factories:
                wm.register(name, factories[key])

    def run(
        self,
        initial_window: str = "loading",
        loading_delay_ms: int = 2000,
    ) -> int:
        """
        Создать FrontendManager, инициализировать, запустить приложение.

        Returns:
            exit code приложения.
        """
        from frontend_module.core.qt_imports import QTimer

        config = self.build_config()
        registers, connection_map = self.build_registers()
        cmd = self.build_command_handler()

        fm = FrontendManager(
            config=config,
            registers=registers,
            router=self._process,
            connection_map=connection_map,
        )
        fm._queue_manager = getattr(self._process, "_queue_manager", None)
        fm._stop_event = getattr(self._process, "_stop_event", None)

        if not fm.initialize():
            self._process._log_error("FrontendManager initialization failed")
            return 1

        app = fm.qt_app
        app.aboutToQuit.connect(self._process.gui_request_shutdown)

        wm = fm.get_window_manager()
        self.register_windows(wm, fm, config, cmd, app)

        # Установить registers_manager в MainWindow после создания
        def _patch_main_registers(win):
            if hasattr(win, "_registers_manager") and win._registers_manager is None:
                win._registers_manager = fm.get_registers()
        # MainWindow создаётся при show_initial_window — registers уже есть в fm

        def _switch_to_main():
            wm.hide_window("loading")
            wm.show_window("main")

        QTimer.singleShot(loading_delay_ms, _switch_to_main)

        fm.run_app(initial_window=initial_window)
        fm.shutdown_app()
        return 0
