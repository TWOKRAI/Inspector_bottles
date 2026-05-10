# multiprocess_prototype/frontend/launcher/ui_builder.py
"""Фабрики UI-окон и регистрация в WindowManager."""
from typing import Any, Callable

from multiprocess_framework.modules.frontend_module.windows import LoadingWindow

from multiprocess_prototype.frontend.diagnostics import attach_ui_diagnostics
from multiprocess_prototype.frontend.windows.main_window import MainWindow, create_tab_widget_factory


def make_main_window_factory(
    config: dict[str, Any],
    fm: Any,
    camera_callbacks_map: Any,
    camera_type: str,
    app_ctx: Any,
    topology_bridge: Any,
    process: Any,
    cmd: Any,
    app: Any,
    window_manager_display: Any,
    on_unmatched: Callable[[str], None] | None = None,
) -> Callable[..., MainWindow]:
    """Вернуть замыкание-фабрику MainWindow."""
    tab_widget_factory = create_tab_widget_factory(app_ctx)

    def create_main_window(**kwargs) -> MainWindow:
        from multiprocess_framework.modules.frontend_module.core.qt_imports import QTimer

        win = MainWindow(
            config=config,
            registers_manager=fm.get_registers() if fm else None,
            camera_callbacks_map=camera_callbacks_map,
            camera_type=camera_type,
            tab_widget_factory=tab_widget_factory,
            header_action_handlers={},
            header_on_unmatched=on_unmatched,
            app_ctx=app_ctx,
            on_restart_requested=lambda: cmd.send_restart_all(),
        )

        topology_bridge.load_from_backend()
        topology_bridge.subscribe_to_changes()

        process._ui_diagnostics = attach_ui_diagnostics(win, config)
        process._window = win
        process._timer = QTimer()
        process._timer.timeout.connect(process._poll_messages)
        process._timer.start(config.get("poll_interval_ms", 16))
        process._stop_timer = QTimer()
        process._stop_timer.timeout.connect(lambda: process._check_stop(app))
        process._stop_timer.start(100)

        app.aboutToQuit.connect(lambda: window_manager_display.destroy_all())
        return win

    return create_main_window


def make_loading_window_factory(config: dict[str, Any]) -> Callable[..., LoadingWindow]:
    """Вернуть замыкание-фабрику LoadingWindow."""
    def create_loading_window(**kwargs) -> LoadingWindow:
        lw = config.get("loading_window") or {}
        return LoadingWindow(
            logo_path=lw.get("logo_path"),
            min_width=lw.get("min_width", 400),
            min_height=lw.get("min_height", 300),
            title=lw.get("title", "Загрузка..."),
        )
    return create_loading_window


def register_all_windows(
    wm: Any,
    config: dict[str, Any],
    factories: dict[str, Callable],
) -> None:
    """Зарегистрировать фабрики в WindowManager согласно window_registry из конфига."""
    registry = config.get("window_registry", {
        "main": {"factory_key": "main"},
        "inspector": {"factory_key": "inspector"},
        "loading": {"factory_key": "loading"},
    })
    for name, entry in registry.items():
        key = entry.get("factory_key", name)
        if key in factories:
            wm.register(name, factories[key])
