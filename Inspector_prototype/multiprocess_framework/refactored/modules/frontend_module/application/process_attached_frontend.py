# -*- coding: utf-8 -*-
"""
Каркас запуска UI, привязанного к процессу (Dict at Boundary, без домена приложения).

Приложение заполняет FrontendLaunchHooks; последовательность initialize / окна / run — одна.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class FrontendLaunchHooks:
    """Колбэки приложения для run_process_attached_frontend."""

    build_ui_config: Callable[[Any], Dict[str, Any]]
    build_registers: Callable[[], Tuple[Any, Dict[str, Any]]]
    create_command_sender: Callable[[Any], Any]
    register_windows: Callable[
        [Any, Any, Dict[str, Any], Any, Any, Any],
        None,
    ]
    on_registers_boot: Optional[Callable[[Any, Dict[str, Any]], None]] = None


def run_process_attached_frontend(
    process_ref: Any,
    *,
    hooks: FrontendLaunchHooks,
    initial_window: str = "loading",
    loading_delay_ms: int = 2000,
) -> int:
    """
    Создать FrontendManager, инициализировать, зарегистрировать окна, запустить цикл Qt.

    Returns:
        Код выхода приложения (0 при штатном завершении).
    """
    from frontend_module.core.qt_imports import QTimer

    from frontend_module.application.frontend_manager import FrontendManager

    config = hooks.build_ui_config(process_ref)
    registers, connection_map = hooks.build_registers()
    sender = hooks.create_command_sender(process_ref)

    if hooks.on_registers_boot is not None:
        hooks.on_registers_boot(registers, config)

    fm = FrontendManager(
        config=config,
        registers=registers,
        router=process_ref,
        connection_map=connection_map,
        queue_manager=getattr(process_ref, "_queue_manager", None),
        stop_event=getattr(process_ref, "_stop_event", None),
    )

    if not fm.initialize():
        process_ref._log_error("FrontendManager initialization failed")
        return 1

    app = fm.qt_app
    app.aboutToQuit.connect(process_ref.gui_request_shutdown)

    wm = fm.get_window_manager()
    hooks.register_windows(wm, fm, config, sender, app, process_ref)

    def _switch_to_main() -> None:
        wm.hide_window("loading")
        wm.show_window("main")

    QTimer.singleShot(loading_delay_ms, _switch_to_main)

    fm.run_app(initial_window=initial_window)
    fm.shutdown_app()
    return 0
