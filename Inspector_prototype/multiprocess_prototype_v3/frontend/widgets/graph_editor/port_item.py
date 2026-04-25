"""PortItem — визуальное представление порта узла на QGraphicsScene."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem

from .constants import PORT_COLORS, PORT_HIGHLIGHT_COLOR, PORT_INCOMPATIBLE_OPACITY, PORT_RADIUS

if TYPE_CHECKING:
    from .node_item import NodeItem


class PortItem(QGraphicsEllipseItem):
    """Круглый маркер порта, дочерний элемент NodeItem.

    Расположение:
    - input-порты — по левому краю узла
    - output-порты — по правому краю узла
    """

    def __init__(
        self,
        port_name: str,
        data_type: str,
        is_input: bool,
        is_optional: bool,
        parent_node_item: NodeItem,
    ) -> None:
        diameter = PORT_RADIUS * 2
        super().__init__(-PORT_RADIUS, -PORT_RADIUS, diameter, diameter, parent_node_item)

        self.port_name = port_name
        self.data_type = data_type
        self.is_input = is_input
        self.is_optional = is_optional
        self.parent_node_item: NodeItem = parent_node_item

        # Цвет по типу данных
        base_color = PORT_COLORS.get(data_type, PORT_COLORS["any"])
        self._base_color = base_color
        self._hover_color = base_color.lighter(140)

        self.setBrush(QBrush(base_color))
        self.setPen(QPen(base_color.darker(120), 1.0))

        # Hover-эффекты и tooltip
        self.setAcceptHoverEvents(True)
        optional_mark = " (опц.)" if is_optional else ""
        direction = "вход" if is_input else "выход"
        self.setToolTip(f"{port_name} [{data_type}] — {direction}{optional_mark}")

    # ------------------------------------------------------------------
    # Позиция центра порта в координатах сцены
    # ------------------------------------------------------------------

    def center_scene_pos(self) -> QPointF:
        """Возвращает центр порта в координатах сцены (для EdgeItem)."""
        return self.mapToScene(QRectF(self.rect()).center())

    # ------------------------------------------------------------------
    # Hover-эффекты
    # ------------------------------------------------------------------

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        """Подсветка при наведении."""
        self.setBrush(QBrush(self._hover_color))
        self.setPen(QPen(self._hover_color.darker(110), 1.5))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        """Сброс подсветки."""
        self.setBrush(QBrush(self._base_color))
        self.setPen(QPen(self._base_color.darker(120), 1.0))
        super().hoverLeaveEvent(event)

    # ------------------------------------------------------------------
    # Drag-connect: начало перетаскивания от output-порта
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        """Начать drag-создание связи если это output-порт (ЛКМ)."""
        if not self.is_input and event.button() == Qt.LeftButton:
            scene = self.scene()
            if scene is not None and hasattr(scene, "start_edge_drag"):
                scene.start_edge_drag(self)
                event.accept()
                return
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Подсветка при drag-connect
    # ------------------------------------------------------------------

    def set_highlight_compatible(self, compatible: bool) -> None:
        """Подсветить порт как совместимый (зелёный) или несовместимый (полупрозрачный).

        Вызывается из GraphScene при drag-создании связи.
        """
        if compatible:
            self.setBrush(QBrush(PORT_HIGHLIGHT_COLOR))
            self.setPen(QPen(PORT_HIGHLIGHT_COLOR.darker(110), 2.0))
        else:
            self.setOpacity(PORT_INCOMPATIBLE_OPACITY)

    def clear_highlight(self) -> None:
        """Сбросить подсветку к обычному состоянию."""
        self.setOpacity(1.0)
        self.setBrush(QBrush(self._base_color))
        self.setPen(QPen(self._base_color.darker(120), 1.0))
