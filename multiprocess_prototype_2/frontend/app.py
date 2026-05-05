"""app.py — запуск Qt event loop для GuiProcess.

Функция run_gui(process) создаёт QApplication, главное окно-заглушку,
safety-таймер для остановки по флагу процесса и запускает event loop.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

if TYPE_CHECKING:
    from .process import GuiProcess


def run_gui(process: "GuiProcess") -> None:
    """Создать QApplication и запустить Qt event loop.

    Args:
        process: GuiProcess — используется для проверки флага остановки
                 и регистрации хука aboutToQuit.
    """
    # Получить существующий экземпляр или создать новый
    app = QApplication.instance() or QApplication(sys.argv)

    # Главное окно — заглушка для Task 4.2
    window = QMainWindow()
    window.setWindowTitle("Inspector v2")
    window.setCentralWidget(QWidget())
    window.resize(800, 600)

    # Safety-таймер: проверяем флаг остановки каждую секунду
    safety_timer = QTimer()
    safety_timer.setInterval(1000)

    def _check_stop() -> None:
        """Завершить Qt loop если процесс запросил остановку."""
        if process.should_stop():
            app.quit()

    safety_timer.timeout.connect(_check_stop)
    safety_timer.start()

    # При выходе из Qt — сигнализируем процессу
    def _on_about_to_quit() -> None:
        process._stop_requested = True

    app.aboutToQuit.connect(_on_about_to_quit)

    window.show()
    app.exec()
