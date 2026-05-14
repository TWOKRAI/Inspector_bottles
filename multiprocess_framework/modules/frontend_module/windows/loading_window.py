# -*- coding: utf-8 -*-
"""
LoadingWindow — окно загрузки с логотипом и прогресс-баром.

Показывается при старте приложения до готовности процессов.
Слот update_progress(percent) для обновления прогресса.
"""

from __future__ import annotations

from typing import Optional

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QImage,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPixmap,
    QVBoxLayout,
    QWidget,
    Qt,
)


class LoadingWindow(QMainWindow):
    """
    Окно загрузки: логотип, ProgressBar, метка процентов.

    Параметры:
        logo_path: путь к изображению логотипа
        min_width, min_height: минимальный размер окна
        title: заголовок окна
    """

    def __init__(
        self,
        *,
        logo_path: Optional[str] = None,
        min_width: int = 400,
        min_height: int = 300,
        title: str = "Загрузка...",
        parent=None,
    ):
        super().__init__(parent)
        self._logo_path = logo_path
        self.setMinimumSize(min_width, min_height)
        self.setWindowTitle(title)
        self._init_ui()

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(20)
        layout.setContentsMargins(40, 40, 40, 40)

        # Логотип
        logo_label = QLabel()
        if self._logo_path:
            image = QImage(self._logo_path)
            if not image.isNull():
                scaled = image.scaled(
                    min(200, image.width()),
                    min(120, image.height()),
                    Qt.KeepAspectRatio,
                )
                pixmap = QPixmap.fromImage(scaled)
                if not pixmap.isNull():
                    logo_label.setPixmap(pixmap)
        if logo_label.pixmap() is None or logo_label.pixmap().isNull():
            logo_label.setText("Inspector")
            logo_label.setStyleSheet("font-size: 24px; color: #333;")
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_label)
        layout.addStretch()

        # ProgressBar
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setMinimumHeight(12)
        self._progress_bar.setTextVisible(True)
        layout.addWidget(self._progress_bar)

        # Метка процентов
        self._percent_label = QLabel("0%")
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._percent_label.setStyleSheet("font-size: 14px; color: #555;")
        layout.addWidget(self._percent_label)

    def update_progress(self, percent: int) -> None:
        """Обновить прогресс (0–100)."""
        percent = max(0, min(100, int(percent)))
        self._progress_bar.setValue(percent)
        self._percent_label.setText(f"{percent}%")
