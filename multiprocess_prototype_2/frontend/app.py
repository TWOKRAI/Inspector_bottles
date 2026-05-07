"""app.py — запуск Qt event loop для GuiProcess."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .app_context import build_app_context
from .windows.main_window import MainWindow
from .widgets.image_panel import ImagePanelWidget
from .tab_factory import TabFactory
from .styles.theme_loader import apply_default_theme

if TYPE_CHECKING:
    from .process import GuiProcess

logger = logging.getLogger(__name__)

# Папка с плагинами прототипа: multiprocess_prototype_2/plugins/
_PLUGINS_DIR = Path(__file__).resolve().parents[1] / "plugins"


def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    # 1. Применить тему
    apply_default_theme(app)

    # 2. Сканировать плагины и построить RegistersManagerV2
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_prototype_2.registers.manager import RegistersManagerV2

    try:
        PluginRegistry.discover(str(_PLUGINS_DIR))
    except Exception as e:
        logger.warning("Не удалось обнаружить плагины: %s", e)

    registers_manager = RegistersManagerV2.from_registry(PluginRegistry)

    # 3. Создать AppContext
    ctx = build_app_context(
        process,
        plugin_registry=PluginRegistry,
        registers_manager=registers_manager,
    )

    # 3a. Создать GuiStateBindings — занимает слот bridge.set_state_callback
    #     (Phase 10B: табы обращаются через ctx.bindings().bind(...))
    from .state.bindings import GuiStateBindings
    bindings = GuiStateBindings(process._bridge)
    ctx.extras["bindings"] = bindings

    # 4. Создать MainWindow
    window = MainWindow()

    # 4b. Создать и установить ImagePanel
    image_panel = ImagePanelWidget()
    window.set_image_panel(image_panel)

    # 5. Создать TabFactory и заполнить табы
    tab_factory = TabFactory(ctx)
    tab_factory.create_tabs(window.tab_widget)

    # 6. Подключить bridge callbacks
    _setup_bridge_callbacks(process, image_panel, window)

    # 7. Запустить таймеры (fps, safety)
    _setup_timers(app, process, window)

    # 8. Сохранить ссылки в process
    process._window = window
    process._app_context = ctx

    window.show()
    app.exec()


def _setup_bridge_callbacks(
    process: "GuiProcess",
    image_panel: ImagePanelWidget,
    window: MainWindow,
) -> None:
    """Подключить bridge signals к виджетам."""
    _frame_trace_cnt = 0

    def _on_frame_received(msg_dict: dict) -> None:
        nonlocal _frame_trace_cnt
        _frame_trace_cnt += 1

        frame = msg_dict.get("frame")

        if _frame_trace_cnt % 30 == 1:
            process._log_info(
                f"[TRACE] _on_frame_received #{_frame_trace_cnt}: "
                f"has_frame={frame is not None}, "
                f"frame_shape={frame.shape if frame is not None and hasattr(frame, 'shape') else None}, "
                f"data_type={msg_dict.get('data_type', '?')}, "
                f"keys={list(msg_dict.keys())[:10]}",
                module="gui",
            )

        if frame is not None:
            image_panel.display_frame("main", frame)
            window.increment_frame_count()

    process._bridge.set_frame_callback(_on_frame_received)
    # State callback занят GuiStateBindings (создан в run_gui, Phase 10A)


def _setup_timers(
    app: QApplication,
    process: "GuiProcess",
    window: MainWindow,
) -> None:
    """FPS таймер + safety таймер."""
    # FPS таймер: раз в секунду
    fps_timer = QTimer()
    fps_timer.setInterval(1000)

    def _update_fps() -> None:
        count = window.reset_frame_count()
        window.update_status(fps=float(count))

    fps_timer.timeout.connect(_update_fps)
    fps_timer.start()

    # Safety таймер: проверяем флаг остановки
    safety_timer = QTimer()
    safety_timer.setInterval(1000)

    def _check_stop() -> None:
        if process.should_stop():
            app.quit()

    safety_timer.timeout.connect(_check_stop)
    safety_timer.start()

    # При выходе из Qt — сигнализируем процессу
    app.aboutToQuit.connect(lambda: setattr(process, '_stop_requested', True))

    # Сохранить ссылки на таймеры чтобы GC не убил их
    window._fps_timer = fps_timer
    window._safety_timer = safety_timer
