# multiprocess_prototype/frontend/launcher/__init__.py
"""
FrontendLauncher — тонкий оркестратор frontend.

Собирает конфиги, регистры, окна по аналогии с SystemLauncher.
GuiProcess делегирует run() в launcher.

Внутренняя структура пакета:
  register_binder  — привязка регистров к StateStore
  hooks_setup      — доменные менеджеры, роутинг, контекст приложения
  ui_builder       — фабрики окон и регистрация в WindowManager
"""
from typing import Any

from multiprocess_framework.modules.frontend_module import FrontendLaunchHooks, run_process_attached_frontend
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config

from multiprocess_prototype.frontend.commands import GuiCommandHandler
from multiprocess_prototype.frontend.configs.frontend_config import build_frontend_config
from multiprocess_prototype.frontend.managers.theme_manager import ThemeManager
from multiprocess_prototype.frontend.widgets import build_camera_tab_callbacks
from multiprocess_prototype.frontend.widgets.tabs_setting.sources_tab.camera_panel.schemas import (
    CameraTabUiConfig,
)
from multiprocess_prototype.registers import create_registers

from multiprocess_prototype.frontend.launcher.hooks_setup import build_domain_context
from multiprocess_prototype.frontend.launcher.register_binder import setup_state_adapters
from multiprocess_prototype.frontend.launcher.ui_builder import (
    make_loading_window_factory,
    make_main_window_factory,
    register_all_windows,
)

_theme_manager = ThemeManager()


class FrontendLauncher:
    """Конструктор frontend: config, registers, windows."""

    def __init__(self, process_ref: Any, app_config: dict[str, Any]):
        self._process = process_ref
        self._app_config = app_config or {}

    def build_config(self) -> dict[str, Any]:
        return build_frontend_config(self._app_config)

    def build_registers(self):
        return create_registers()

    def register_windows(
        self,
        window_manager: Any,
        frontend_manager: Any,
        config: dict[str, Any],
        sender: Any,
        app: Any,
        process_ref: Any,
    ) -> None:
        _theme_manager.apply_theme(_theme_manager.current_theme)
        wm = window_manager
        fm = frontend_manager
        process = process_ref
        cmd = GuiCommandHandler(process_ref)
        assert sender is process_ref._routed_command_sender
        regs = fm.get_registers() if fm else None

        cam_tab_ui = coerce_schema_config(config.get("camera_tab") or {}, CameraTabUiConfig)
        camera_callbacks_map = build_camera_tab_callbacks(
            cmd,
            webcam_enum_max_index=cam_tab_ui.webcam_enum_max_index,
        )
        camera_type = config.get("camera_type", "simulator")
        state_proxy = getattr(process, "_state_proxy", None)

        camera_registry = setup_state_adapters(process, regs, state_proxy, config)

        app_ctx, _display_router, window_manager_display, topology_bridge = build_domain_context(
            process=process,
            config=config,
            regs=regs,
            cmd=cmd,
            camera_callbacks_map=camera_callbacks_map,
            camera_type=camera_type,
            camera_registry=camera_registry,
            app=app,
            theme_manager=_theme_manager,
        )

        window_names = set((config.get("window_registry") or {}).keys())

        def header_on_unmatched(action_id: str) -> None:
            if wm and action_id in window_names:
                wm.show_window(action_id)

        main_factory = make_main_window_factory(
            config=config,
            fm=fm,
            camera_callbacks_map=camera_callbacks_map,
            camera_type=camera_type,
            app_ctx=app_ctx,
            topology_bridge=topology_bridge,
            process=process,
            cmd=cmd,
            app=app,
            window_manager_display=window_manager_display,
            on_unmatched=header_on_unmatched if wm else None,
        )
        loading_factory = make_loading_window_factory(config)
        register_all_windows(wm, config, {"main": main_factory, "loading": loading_factory})

    def _on_registers_boot(self, rm: Any, config: dict[str, Any]) -> None:
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
        return run_process_attached_frontend(
            self._process,
            hooks=self._launch_hooks(),
            initial_window=initial_window,
            loading_delay_ms=loading_delay_ms,
        )
