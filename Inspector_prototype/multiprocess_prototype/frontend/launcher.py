# multiprocess_prototype/frontend/launcher.py
"""
FrontendLauncher — конструктор frontend.

Собирает конфиги, регистры, окна по аналогии с SystemLauncher.
GuiProcess делегирует run() в launcher.
"""

from typing import Any, Dict, Optional

from frontend_module import FrontendLaunchHooks, run_process_attached_frontend
from frontend_module.styling import create_app_style_session
from frontend_module.windows import LoadingWindow

from frontend_module.core.schema_config import coerce_schema_config

from multiprocess_prototype.registers import create_registers
from multiprocess_prototype.managers import RecipeManager
from multiprocess_prototype.managers.app_recipe_aggregate import (
    aggregate_to_snapshot,
    build_default_app_aggregate,
)
from multiprocess_prototype.frontend.configs.frontend_config import build_frontend_config
from multiprocess_prototype.frontend.diagnostics import attach_ui_diagnostics
from multiprocess_prototype.frontend.commands import GuiCommandHandler
from multiprocess_prototype.frontend.widgets import build_camera_tab_callbacks
from multiprocess_prototype.frontend.widgets.tabs_setting.camera_tab.schemas import CameraTabUiConfig
from multiprocess_prototype.frontend.app_context import FrontendAppContext
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

    def register_windows(
        self,
        window_manager: Any,
        frontend_manager: Any,
        config: Dict[str, Any],
        sender: Any,
        app: Any,
        process_ref: Any,
    ) -> None:
        """Регистрация фабрик окон в WindowManager."""
        wm = window_manager
        fm = frontend_manager
        process = process_ref
        cmd = GuiCommandHandler(process_ref)
        assert sender is process_ref._routed_command_sender
        cam_tab_ui = coerce_schema_config(config.get("camera_tab") or {}, CameraTabUiConfig)
        camera_callbacks_map = build_camera_tab_callbacks(
            cmd,
            webcam_enum_max_index=cam_tab_ui.webcam_enum_max_index,
        )
        window_cfg = config.get("window", {})
        title = window_cfg.get("title", "Inspector")
        width = window_cfg.get("width", window_cfg.get("min_width", 1024))
        height = window_cfg.get("height", window_cfg.get("min_height", 600))

        recipe_manager = RecipeManager(data_path=config.get("recipes_path"))
        regs = fm.get_registers() if fm else None
        if regs is not None:
            recipe_manager.ensure_slot_from_registers(regs, "default_value")
        recipe_manager.ensure_app_slot_from_snapshot(
            "default_value",
            aggregate_to_snapshot(build_default_app_aggregate()),
        )

        camera_type = config.get("camera_type", "simulator")
        style_session = create_app_style_session(ui_theme=config.get("ui_theme"))
        app_ctx = FrontendAppContext(
            config=config,
            registers_manager=regs,
            camera_callbacks_map=camera_callbacks_map,
            camera_type=camera_type,
            recipe_manager=recipe_manager,
            command_handler=cmd,
            style_session=style_session,
        )
        tab_widget_factory = create_tab_widget_factory(app_ctx)

        window_names = set((config.get("window_registry") or {}).keys())

        def header_on_unmatched(action_id: str) -> None:
            if wm and action_id in window_names:
                wm.show_window(action_id)

        def create_main_window(**kwargs):
            from frontend_module.core.qt_imports import QTimer

            win = MainWindow(
                config=config,
                registers_manager=fm.get_registers() if fm else None,
                camera_callbacks_map=camera_callbacks_map,
                camera_type=camera_type,
                tab_widget_factory=tab_widget_factory,
                header_action_handlers={},
                header_on_unmatched=header_on_unmatched if wm else None,
                style_session=style_session,
            )
            process._ui_diagnostics = attach_ui_diagnostics(win, config)
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

    def _on_registers_boot(self, rm: Any, config: Dict[str, Any]) -> None:
        if rm and hasattr(rm, "set_field_value"):
            ct = config.get("camera_type", "simulator")
            rm.set_field_value("camera", "camera_type", ct)

    def _launch_hooks(self) -> FrontendLaunchHooks:
        return FrontendLaunchHooks(
            build_ui_config=lambda p: build_frontend_config(p.get_config("config") or {}),
            build_registers=lambda: create_registers(),
            create_command_sender=lambda p: p._routed_command_sender,
            register_windows=self.register_windows,
            on_registers_boot=self._on_registers_boot,
        )

    def run(
        self,
        initial_window: str = "loading",
        loading_delay_ms: int = 2000,
    ) -> int:
        """
        Делегирует в ``run_process_attached_frontend`` (единая последовательность в фреймворке).

        Returns:
            exit code приложения.
        """
        return run_process_attached_frontend(
            self._process,
            hooks=self._launch_hooks(),
            initial_window=initial_window,
            loading_delay_ms=loading_delay_ms,
        )
