"""FrontendLauncher — assembles frontend for GuiProcess."""

from typing import Any, Dict

from frontend_module import FrontendLaunchHooks, run_process_attached_frontend
from frontend_module.windows import LoadingWindow

from multiprocess_prototype_v3.registers import create_registers
from multiprocess_prototype_v3.managers import RecipeManager
from multiprocess_prototype_v3.managers.recipe_manager import DEFAULT_RECIPE_SLOT_ID
from multiprocess_prototype_v3.frontend.commands import GuiCommandHandler, build_camera_callbacks
from multiprocess_prototype_v3.frontend.diagnostics import attach_ui_diagnostics


def _build_frontend_config(app_cfg: dict) -> dict:
    """Build frontend config dict from app config."""
    return {
        "window": {
            "title": app_cfg.get("window_title", "Inspector Prototype"),
            "width": app_cfg.get("window_width", 1024),
            "height": app_cfg.get("window_height", 600),
        },
        "camera_type": app_cfg.get("camera_type", "simulator"),
        "poll_interval_ms": app_cfg.get("poll_interval_ms", 16),
        "recipes_path": app_cfg.get("recipes_path"),
        "settings_recipes_path": app_cfg.get("settings_recipes_path"),
        "recipe_access": app_cfg.get("recipe_access"),
        "touch_keyboard": app_cfg.get("touch_keyboard"),
        "loading_window": {
            "title": "Загрузка...",
            "min_width": 400,
            "min_height": 300,
        },
    }


class FrontendLauncher:
    """Frontend constructor: config, registers, windows."""

    def __init__(self, process_ref: Any, app_config: Dict[str, Any]):
        self._process = process_ref
        self._app_config = app_config or {}

    def register_windows(self, window_manager, frontend_manager, config, sender, app, process_ref):
        process = process_ref
        fm = frontend_manager
        cmd = GuiCommandHandler(process_ref)
        camera_callbacks = build_camera_callbacks(cmd)

        window_cfg = config.get("window", {})
        camera_type = config.get("camera_type", "simulator")

        recipe_manager = RecipeManager(
            data_path=config.get("recipes_path"),
            app_recipes_path=config.get("settings_recipes_path"),
        )
        regs = fm.get_registers() if fm else None
        if regs is not None:
            recipe_manager.ensure_slot_from_registers(regs, DEFAULT_RECIPE_SLOT_ID)

        def create_main_window(**kwargs):
            from frontend_module.core.qt_imports import QTimer
            from multiprocess_prototype_v3.frontend.main_window import MainWindow

            win = MainWindow(
                config=config,
                registers_manager=regs,
                camera_callbacks_map=camera_callbacks,
                camera_type=camera_type,
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

        window_manager.register("main", create_main_window)
        window_manager.register("loading", create_loading_window)

    def _on_registers_boot(self, rm, config):
        if rm and hasattr(rm, "set_field_value"):
            rm.set_field_value("camera", "camera_type", config.get("camera_type", "simulator"))

    def _launch_hooks(self) -> FrontendLaunchHooks:
        return FrontendLaunchHooks(
            build_ui_config=lambda p: _build_frontend_config(p.get_config("config") or {}),
            build_registers=lambda: create_registers(),
            create_command_sender=lambda p: p._routed_command_sender,
            register_windows=self.register_windows,
            on_registers_boot=self._on_registers_boot,
        )

    def run(self, initial_window="loading", loading_delay_ms=2000) -> int:
        return run_process_attached_frontend(
            self._process,
            hooks=self._launch_hooks(),
            initial_window=initial_window,
            loading_delay_ms=loading_delay_ms,
        )
