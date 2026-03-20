# multiprocess_prototype/frontend/launcher.py
"""
FrontendLauncher — конструктор frontend.

Собирает конфиги, регистры, окна по аналогии с SystemLauncher.
GuiProcess делегирует run() в launcher.
"""

from typing import Any, Dict, Optional

from frontend_module import FrontendManager
from frontend_module.windows import LoadingWindow

from multiprocess_prototype.registers import create_registers
from multiprocess_prototype.frontend.configs.frontend_config import build_frontend_config
from multiprocess_prototype.frontend.commands import GuiCommandHandler
from multiprocess_prototype.frontend.windows.main_window import MainWindow, create_tab_widget_factory


class FrontendLauncher:
    """
    Конструктор frontend: config, registers, windows.

    run() создаёт FrontendManager, инициализирует, запускает приложение.
    """

    def __init__(self, process_ref: Any, app_config: Dict[str, Any]):
        """
        Args:
            process_ref: GuiProcess (ProcessModule: _msg, send_message, get_config).
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
        """
        Callbacks для ProcessingTabWidget (legacy, если вкладка без RegistersManager).

        При работе через FrontendManager поля идут через register_update (см. ADR-049).
        """
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

        tab_widget_factory = create_tab_widget_factory(
            config=config,
            registers_manager=fm.get_registers() if fm else None,
            camera_callbacks=self._camera_callbacks(cmd),
            processing_callbacks=self._processing_callbacks(cmd),
            camera_type=camera_type,
        )

        window_names = set((config.get("window_registry") or {}).keys())

        def header_on_unmatched(action_id: str) -> None:
            if wm and action_id in window_names:
                wm.show_window(action_id)

        def create_main_window(**kwargs):
            from frontend_module.core.qt_imports import QTimer

            win = MainWindow(
                config=config,
                registers_manager=fm.get_registers() if fm else None,
                camera_callbacks=self._camera_callbacks(cmd),
                processing_callbacks=self._processing_callbacks(cmd),
                camera_type=camera_type,
                tab_widget_factory=tab_widget_factory,
                header_action_handlers={},
                header_on_unmatched=header_on_unmatched if wm else None,
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
            lw = config.get("loading_window") or {}
            return LoadingWindow(
                logo_path=lw.get("logo_path"),
                min_width=lw.get("min_width", 400),
                min_height=lw.get("min_height", 300),
                title=lw.get("title", "Загрузка..."),
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

        rm = registers
        if rm and hasattr(rm, "set_field_value"):
            ct = config.get("camera_type", "simulator")
            rm.set_field_value("camera", "camera_type", ct)

        fm = FrontendManager(
            config=config,
            registers=registers,
            router=self._process,
            connection_map=connection_map,
            queue_manager=getattr(self._process, "_queue_manager", None),
            stop_event=getattr(self._process, "_stop_event", None),
        )

        if not fm.initialize():
            self._process._log_error("FrontendManager initialization failed")
            return 1

        app = fm.qt_app
        app.aboutToQuit.connect(self._process.gui_request_shutdown)

        wm = fm.get_window_manager()
        self.register_windows(wm, fm, config, cmd, app)

        def _switch_to_main():
            wm.hide_window("loading")
            wm.show_window("main")

        QTimer.singleShot(loading_delay_ms, _switch_to_main)

        fm.run_app(initial_window=initial_window)
        fm.shutdown_app()
        return 0
