"""StatusIndicator — цветной кружок статуса.

Универсальный виджет: не привязан к конкретным сущностям.
Цвет определяется по строковому состоянию из настраиваемого color_map.
"""

from __future__ import annotations

from typing import ClassVar

from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QColor,
    QPainter,
    QSize,
    QWidget,
    Qt,
)


__all__ = ["StatusIndicator"]


class StatusIndicator(QWidget):
    """Индикатор статуса — закрашенный круг."""

    DEFAULT_COLORS: ClassVar[dict[str, str]] = {
        "running": "#4caf50",
        "ready": "#8bc34a",
        "stopped": "#9e9e9e",
        "error": "#f44336",
        "starting": "#ff9800",
        "unknown": "#757575",
    }

    def __init__(
        self,
        size: int = 12,
        color_map: dict[str, str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._size = size
        self._color_map = {**self.DEFAULT_COLORS, **(color_map or {})}
        self._state = "unknown"
        self.setFixedSize(self._size, self._size)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                       #
    # ------------------------------------------------------------------ #

    def set_state(self, state: str) -> None:
        """Установить состояние (обновляет цвет)."""
        self._state = state
        self.update()

    def state(self) -> str:
        """Текущее строковое состояние."""
        return self._state

    # ------------------------------------------------------------------ #
    #  Qt overrides                                                        #
    # ------------------------------------------------------------------ #

    def paintEvent(self, event) -> None:
        """Рисует закрашенный круг."""
        color_hex = self._color_map.get(self._state, self._color_map["unknown"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color_hex))
        # Отступ 1px чтобы круг не обрезался
        margin = 1
        painter.drawEllipse(margin, margin, self._size - 2 * margin, self._size - 2 * margin)
        painter.end()

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._size, self._size)
