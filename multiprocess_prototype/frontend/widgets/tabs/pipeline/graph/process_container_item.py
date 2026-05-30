"""ProcessContainerItem -- рамка-контейнер процесса вокруг его плагин-нод (D.1).

Pipeline node = плагин: один процесс рисуется как рамка с заголовком (имя
процесса), внутри которой лежат отдельные ноды-плагины. Контейнер — backdrop:
рисуется ПОД нодами (`setZValue`), не выделяется и не перехватывает клики
(плагин-ноды и фон над ним по Z). Геометрия — производная: `fit_to_members`
обнимает текущие позиции членов + отступы + заголовок. Перетаскивание плагина
между контейнерами не трогает Qt parent-child (контейнер не родитель нод) —
целевой контейнер определяется по позиции центра ноды (D.3).
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem

from .constants import (
    CONTAINER_BORDER,
    CONTAINER_CORNER_RADIUS,
    CONTAINER_FILL,
    CONTAINER_HEADER_H,
    CONTAINER_PADDING,
    CONTAINER_TITLE_COLOR,
    NODE_HEIGHT,
    NODE_WIDTH,
)

# Z-порядок: контейнер под всем (ноды по умолчанию 0, implicit-стрелки -0.5).
_CONTAINER_Z = -1.0


@dataclass
class ProcessContainerData:
    """Данные контейнера процесса."""

    process_name: str


class ProcessContainerItem(QGraphicsRectItem):
    """Рамка-контейнер процесса (backdrop под плагин-нодами).

    Не selectable, не movable, не принимает мышь — клики проходят к нодам/фону.
    `fit_to_members` пересчитывает rect/позицию по членам.
    """

    def __init__(self, data: ProcessContainerData, parent=None) -> None:
        super().__init__(parent)
        self._data = data

        self.setZValue(_CONTAINER_Z)
        # Backdrop: не интерактивен (клики → ноды сверху или фон сцены).
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)

        fill = QColor(CONTAINER_FILL)
        fill.setAlpha(120)
        self.setBrush(QBrush(fill))
        self.setPen(QPen(QColor(CONTAINER_BORDER), 1.5))

        # Заголовок — имя процесса.
        self._title = QGraphicsTextItem(data.process_name, self)
        self._title.setDefaultTextColor(QColor(CONTAINER_TITLE_COLOR))
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        self._title.setFont(font)

    @property
    def process_name(self) -> str:
        return self._data.process_name

    def set_process_name(self, name: str) -> None:
        """Обновить имя процесса (заголовок)."""
        self._data.process_name = name
        self._title.setPlainText(name)

    def fit_to_members(self, members: list) -> None:
        """Подогнать рамку под bounding-rect членов + отступы + заголовок.

        members — список плагин-нод (NodeItem). Если пуст — рамка сжимается до
        заголовка (процесс без плагинов). Координаты — в scene-системе: контейнер
        top-level, поэтому используем pos() членов и фиксированные размеры нод.
        """
        if members:
            min_x = min(m.pos().x() for m in members)
            min_y = min(m.pos().y() for m in members)
            max_x = max(m.pos().x() + NODE_WIDTH for m in members)
            max_y = max(m.pos().y() + NODE_HEIGHT for m in members)
        else:
            min_x = min_y = 0.0
            max_x = NODE_WIDTH
            max_y = NODE_HEIGHT

        pad = CONTAINER_PADDING
        header = CONTAINER_HEADER_H
        x = min_x - pad
        y = min_y - pad - header
        width = (max_x - min_x) + 2 * pad
        height = (max_y - min_y) + 2 * pad + header

        self.setPos(x, y)
        self.setRect(QRectF(0, 0, width, height))
        # Заголовок — в строке header слева.
        self._title.setPos(pad * 0.5, 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())
        painter.drawRoundedRect(self.rect(), CONTAINER_CORNER_RADIUS, CONTAINER_CORNER_RADIUS)
