"""EdgeItem -- связь между узлами (wire) на QGraphicsScene."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem

from .constants import WIRE_COLOR, WIRE_COLOR_HOVER, WIRE_WIDTH


@dataclass
class EdgeData:
    """Абстрактные данные связи."""
    source_id: str
    target_id: str
    label: str = ""


class EdgeItem(QGraphicsPathItem):
    """Визуальная связь (кубический Bezier) между NodeItem.

    Selectable для удаления. Подсветка при hover.
    """

    def __init__(self, data: EdgeData, parent=None) -> None:
        super().__init__(parent)
        self._data = data

        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)

        self._normal_pen = QPen(QColor(WIRE_COLOR), WIRE_WIDTH)
        self._hover_pen = QPen(QColor(WIRE_COLOR_HOVER), WIRE_WIDTH + 1)
        self._selected_pen = QPen(QColor("#4fc3f7"), WIRE_WIDTH + 1)

        self.setPen(self._normal_pen)

    @property
    def edge_data(self) -> EdgeData:
        return self._data

    @property
    def source_id(self) -> str:
        return self._data.source_id

    @property
    def target_id(self) -> str:
        return self._data.target_id

    def update_path(self, source_pos: tuple[float, float], target_pos: tuple[float, float]) -> None:
        """Обновить кривую Bezier по позициям портов."""
        sx, sy = source_pos
        tx, ty = target_pos

        # Контрольные точки для плавной кривой
        dx = abs(tx - sx) * 0.5

        path = QPainterPath()
        path.moveTo(QPointF(sx, sy))
        path.cubicTo(
            QPointF(sx + dx, sy),
            QPointF(tx - dx, ty),
            QPointF(tx, ty),
        )
        self.setPath(path)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isSelected():
            painter.setPen(self._selected_pen)
        else:
            painter.setPen(self.pen())
        painter.drawPath(self.path())

    def hoverEnterEvent(self, event) -> None:
        self.setPen(self._hover_pen)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self.setPen(self._normal_pen)
        self.update()
        super().hoverLeaveEvent(event)
