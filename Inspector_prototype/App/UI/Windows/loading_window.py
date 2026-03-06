# -*- coding: utf-8 -*-
"""
LoadingWindow — экран загрузки, отображаемый при старте приложения.

Показывает логотип, прогресс-бар и текстовый процент пока Loading-поток
ожидает готовности всех процессов фреймворка.

Жизненный цикл:
    WindowManager создаёт LoadingWindow → запускает Loading(QThread) →
    Loading.progress_updated  ──► LoadingWindow.update_progress
    Loading.window_close      ──► WindowManager.close_loading_window / show_main_window
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from App.resource_paths import get_resource_path


class LoadingWindow(QWidget):
    """
    Экран загрузки.

    Args:
        window_manager: WindowManager — источник fullscreen-флага и геометрии.
                        Может быть None при изолированном тестировании.
    """

    def __init__(self, window_manager=None) -> None:
        super().__init__()
        self._wm = window_manager
        self._setup_ui()
        self._apply_fullscreen()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self.setWindowTitle("Inspector — Loading")
        self.setMinimumSize(800, 500)

        # Контент по центру
        content = QVBoxLayout()
        content.setSpacing(0)

        logo_label = QLabel()
        pixmap = QPixmap(get_resource_path("innotech.png"))
        logo_label.setPixmap(pixmap)
        logo_label.setAlignment(Qt.AlignCenter)

        self._percent_label = QLabel("0%")
        self._percent_label.setAlignment(Qt.AlignCenter)
        self._percent_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; color: #2c3e50;"
        )

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setAlignment(Qt.AlignCenter)
        self._progress_bar.setFormat("%p%")

        content.addStretch()
        content.addWidget(logo_label)
        content.addSpacing(35)
        content.addWidget(self._percent_label)
        content.addSpacing(10)
        content.addWidget(self._progress_bar)
        content.addStretch()

        # Горизонтальное центрирование
        root = QHBoxLayout(self)
        root.addStretch(1)
        root.addLayout(content)
        root.addStretch(1)

    def _apply_fullscreen(self) -> None:
        if self._wm and getattr(self._wm, "fullscreen", False):
            self.showFullScreen()

    # ------------------------------------------------------------------
    # Public API (слот, подключается WindowManager к Loading.progress_updated)
    # ------------------------------------------------------------------

    def update_progress(self, percent: int) -> None:
        """Обновить прогресс-бар и метку (вызывается из Loading-потока через сигнал)."""
        self._progress_bar.setValue(percent)
        self._percent_label.setText(f"{percent}%")

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
