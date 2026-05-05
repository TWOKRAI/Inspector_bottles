"""app.py — запуск Qt event loop для GuiProcess."""
from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout

from .windows.main_window import MainWindow
from .widgets.camera.view import CameraView
from .widgets.camera.presenter import CameraPresenter
from .bridge.command_sender import CommandSender
from .widgets.controls.command_panel import CommandPanel
from .widgets.controls.process_status import ProcessStatusWidget
from .widgets.topology.editor import TopologyEditorWidget

if TYPE_CHECKING:
    from .process import GuiProcess


def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop."""
    app = QApplication.instance() or QApplication(sys.argv)

    # Главное окно
    window = MainWindow()

    # Вкладка Camera
    camera_view = CameraView()
    camera_presenter = CameraPresenter(camera_view)
    window.add_tab(camera_view, "Camera")

    # Вкладка Controls
    controls_widget = QWidget()
    controls_layout = QVBoxLayout(controls_widget)

    command_sender = CommandSender(process)
    command_panel = CommandPanel(command_sender)
    process_status = ProcessStatusWidget()

    controls_layout.addWidget(command_panel)
    controls_layout.addWidget(process_status)

    window.add_tab(controls_widget, "Controls")

    # Вкладка Topology Editor
    topology_editor = TopologyEditorWidget()
    window.add_tab(topology_editor, "Topology")

    # Установить директорию топологий для редактора
    from pathlib import Path
    # По умолчанию — директория topology рядом с frontend/
    default_topo_dir = Path(__file__).resolve().parent.parent / "topology"
    topology_editor.set_topology_dir(default_topo_dir)

    # Сохранить ссылки в process для доступа из других задач
    process._window = window
    process._camera_presenter = camera_presenter

    # Подключить bridge signals
    def _on_frame_received(msg_dict: dict) -> None:
        """Slot: получен кадр через IPC.

        FrameShmMiddleware.on_receive уже подставил msg["frame"] (numpy)
        из SHM по координатам shm_actual_name.
        """
        frame = msg_dict.get("frame")
        if frame is not None:
            camera_presenter.on_frame(frame)
            window.increment_frame_count()

    process._bridge.frame_received.connect(_on_frame_received)
    # Подключить state updates к таблице статусов процессов
    process._bridge.state_updated.connect(process_status.on_state_updated)


    # FPS таймер: раз в секунду считать fps и обновлять StatusBar
    fps_timer = QTimer()
    fps_timer.setInterval(1000)

    def _update_fps() -> None:
        count = window.reset_frame_count()
        window.update_status(fps=float(count))

    fps_timer.timeout.connect(_update_fps)
    fps_timer.start()

    # Safety-таймер: проверяем флаг остановки каждую секунду
    safety_timer = QTimer()
    safety_timer.setInterval(1000)

    def _check_stop() -> None:
        """Завершить Qt loop если процесс запросил остановку."""
        if process.should_stop():
            app.quit()

    safety_timer.timeout.connect(_check_stop)
    safety_timer.start()

    # При выходе из Qt — сигнализируем процессу об остановке
    app.aboutToQuit.connect(lambda: setattr(process, '_stop_requested', True))

    window.show()
    app.exec()
