"""CameraView — отображение BGR-кадров через QPixmap."""
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout


class ICameraView(Protocol):
    """Интерфейс CameraView для MVP."""

    def update_pixmap(self, pixmap: QPixmap) -> None: ...
    def set_placeholder(self, text: str) -> None: ...


class CameraView(QWidget):
    """Виджет отображения камеры. BGR numpy → QPixmap."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._label = QLabel("Нет сигнала")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setMinimumSize(320, 240)
        self._label.setStyleSheet(
            "background-color: #1a1a2e; color: #aaa; font-size: 16px;"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

    def update_pixmap(self, pixmap: QPixmap) -> None:
        """Установить pixmap с масштабированием под размер label."""
        scaled = pixmap.scaled(
            self._label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)

    def set_placeholder(self, text: str) -> None:
        """Показать текст-placeholder вместо изображения."""
        self._label.clear()
        self._label.setText(text)

    def resizeEvent(self, event) -> None:
        """При resize — перемасштабировать текущий pixmap."""
        super().resizeEvent(event)
        pixmap = self._label.pixmap()
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self._label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._label.setPixmap(scaled)
