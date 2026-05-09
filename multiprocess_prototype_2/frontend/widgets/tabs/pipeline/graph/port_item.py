"""PortItem -- визуальный порт на узле (input/output)."""
from __future__ import annotations

from PySide6.QtGui import QBrush, QColor, QPen
from PySide6.QtWidgets import QGraphicsEllipseItem

from .constants import PORT_RADIUS, CATEGORY_COLORS


class PortItem(QGraphicsEllipseItem):
    """Визуальный порт (кружок) на узле.

    port_type: "input" или "output".
    endpoint: полное имя порта "process.plugin.port".
    """

    def __init__(
        self,
        port_type: str,
        endpoint: str,
        category: str = "utility",
        parent=None,
    ) -> None:
        r = PORT_RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r, parent)
        self._port_type = port_type
        self._endpoint = endpoint
        self._category = category

        # Стиль
        color = CATEGORY_COLORS.get(category, "#9e9e9e")
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor("#ffffff"), 1))

        self.setAcceptHoverEvents(True)
        # Порт не должен быть movable/selectable отдельно от ноды
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)

    @property
    def port_type(self) -> str:
        return self._port_type

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def is_input(self) -> bool:
        return self._port_type == "input"

    @property
    def is_output(self) -> bool:
        return self._port_type == "output"

    def center_scene_pos(self) -> tuple[float, float]:
        """Центр порта в scene coordinates."""
        pos = self.scenePos()
        return pos.x(), pos.y()

    def hoverEnterEvent(self, event) -> None:
        """Подсветка при наведении."""
        self.setPen(QPen(QColor("#ffff00"), 2))
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        """Убрать подсветку."""
        self.setPen(QPen(QColor("#ffffff"), 1))
        self.update()
        super().hoverLeaveEvent(event)
