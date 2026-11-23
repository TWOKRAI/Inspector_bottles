"""CommandPanel — панель кнопок управления процессами."""

from __future__ import annotations
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget, QVBoxLayout, QGroupBox, QPushButton, QHBoxLayout

if TYPE_CHECKING:
    from ...bridge.command_sender import CommandSender


class CommandPanel(QWidget):
    """Панель с кнопками для отправки команд в процессы.

    FROZEN (4.2d, A1): команды start_capture/stop_capture удалены в 4.2a, живого вызова нет
    (панель нигде не создаётся). Не удалять — дремлющий путь остаётся контрактом.

    Пока: Start/Stop Capture для camera_0.
    В будущем — динамическая генерация из plugin.commands.
    """

    def __init__(self, command_sender: "CommandSender", parent=None):
        super().__init__(parent)
        self._sender = command_sender
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Группа: Camera
        camera_group = QGroupBox("Camera")
        camera_layout = QHBoxLayout(camera_group)

        btn_start = QPushButton("Start Capture")
        btn_start.clicked.connect(self._on_start_capture)
        camera_layout.addWidget(btn_start)

        btn_stop = QPushButton("Stop Capture")
        btn_stop.clicked.connect(self._on_stop_capture)
        camera_layout.addWidget(btn_stop)

        layout.addWidget(camera_group)
        layout.addStretch()

    def _on_start_capture(self) -> None:
        self._sender.send_command("camera_0", "start_capture")

    def _on_stop_capture(self) -> None:
        self._sender.send_command("camera_0", "stop_capture")
