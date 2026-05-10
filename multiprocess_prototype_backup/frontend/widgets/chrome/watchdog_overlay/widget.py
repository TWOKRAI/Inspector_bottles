# multiprocess_prototype/frontend/widgets/watchdog_overlay/widget.py
"""
WatchdogOverlay — полупрозрачный overlay поверх parent-виджета.

Показывается при потере кадров от backend (жёлтый фон + текст по центру).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class WatchdogOverlay(QWidget):
    """
    Полупрозрачный жёлтый overlay поверх parent-виджета.

    Используется для индикации задержки/отсутствия кадров от backend.
    """

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("WatchdogOverlay")
        # WA_StyledBackground необходим для применения background у кастомного QWidget
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel("Ожидание backend...", self)
        self._label.setObjectName("WatchdogOverlayLabel")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        # Изначально скрыт
        self.hide()

        # Подстраиваться под размер parent
        if parent is not None:
            self.resize(parent.size())

    def show_warning(self, text: str = "Ожидание backend...") -> None:
        """Показать overlay с указанным текстом."""
        self._label.setText(text)
        self.resize(self.parent().size())
        self.raise_()
        self.show()

    def hide_overlay(self) -> None:
        """Скрыть overlay."""
        self.hide()

    def resizeEvent(self, event) -> None:
        """Растянуться на весь parent при его изменении."""
        if self.parent() is not None:
            self.resize(self.parent().size())
        super().resizeEvent(event)
