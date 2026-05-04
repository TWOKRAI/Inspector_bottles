"""ShmRouteNode — кастомная нода NodeGraphQt для fan-out маршрутизации.

Визуальное представление:
  +==================+
  | Route: frame_shm |
  |------------------|
  | IN: o frame      |
  | OUT: o out_1     |
  |      o out_2     |
  |      o out_3     |
  +==================+

Нода отображает точку ветвления данных: один входной SHM-канал → N выходов.
Используется для fan-out маршрутизации между процессами.

Регистрация: graph.register_node(ShmRouteNode)
Создание:    graph.create_node("constructor.nodes.ShmRouteNode")
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from NodeGraphQt import BaseNode
from NodeGraphQt.qgraphics.node_base import NodeItem

if TYPE_CHECKING:
    from PySide6 import QtGui, QtWidgets

logger = logging.getLogger(__name__)

# Параметры отрисовки body ноды
_ROUTE_LINE_HEIGHT = 15.0
_ROUTE_PADDING_TOP = 4.0
_ROUTE_PADDING_BOTTOM = 6.0
_ROUTE_FONT_SIZE = 9

# Фоновый цвет route-ноды — синеватый, отличается от ProcessNodeItem
_ROUTE_BG_COLOR = "#3a3a5a"

# Минимальные размеры route-ноды (компактнее ProcessNodeItem)
_ROUTE_MIN_WIDTH = 140.0
_ROUTE_MIN_HEIGHT = 60.0


class RouteNodeItem(NodeItem):
    """QGraphicsItem для SHM route-ноды — компактная отрисовка fan-out точки.

    Расширяет NodeItem: добавляет текстовый блок с именем SHM-канала
    и индикатором «Route» ниже заголовка.
    Размер компактнее чем ProcessNodeItem — подходит для узловых точек.
    """

    def __init__(
        self,
        name: str = "node",
        parent: QtWidgets.QGraphicsItem | None = None,
    ) -> None:
        super().__init__(name, parent)
        self._shm_name: str = ""
        # Минимальные размеры — меньше чем у ProcessNodeItem
        self._min_width = _ROUTE_MIN_WIDTH
        self._min_height = _ROUTE_MIN_HEIGHT

    def set_shm_name(self, shm_name: str) -> None:
        """Обновить имя SHM-канала для отображения в body."""
        self._shm_name = shm_name
        # Высота компактная — только одна строка с именем канала
        self._min_height = _ROUTE_MIN_HEIGHT

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        """Рисуем стандартную ноду + имя SHM-канала в body."""
        # Стандартная отрисовка NodeGraphQt (заголовок, порты, border)
        super().paint(painter, option, widget)

        from PySide6 import QtCore, QtGui as QtG

        painter.save()

        # Шрифт для текста body
        font = painter.font()
        font.setPixelSize(_ROUTE_FONT_SIZE)
        painter.setFont(font)

        rect = self.boundingRect()
        # Начинаем ниже заголовка ноды (~26px от верха)
        y_start = 28.0 + _ROUTE_PADDING_TOP
        x_left = rect.x() + 10.0

        # Строка с меткой типа ноды
        painter.setPen(QtG.QColor("#8888cc"))
        painter.drawText(
            QtCore.QPointF(x_left, y_start + _ROUTE_LINE_HEIGHT * 0.75),
            "fan-out",
        )

        # Строка с именем SHM-канала (если задан)
        if self._shm_name:
            painter.setPen(QtG.QColor("#cccccc"))
            painter.drawText(
                QtCore.QPointF(
                    x_left,
                    y_start + _ROUTE_LINE_HEIGHT * 0.75 + _ROUTE_LINE_HEIGHT,
                ),
                self._shm_name,
            )

        painter.restore()


class ShmRouteNode(BaseNode):
    """Нода NodeGraphQt = точка fan-out маршрутизации (1 вход → N выходов).

    Отображает SHM route-ноду: один входной порт, N выходных портов.
    Имя SHM-канала и количество выходов задаются через set_route_data().

    Регистрация: graph.register_node(ShmRouteNode)
    Создание:    graph.create_node("constructor.nodes.ShmRouteNode")
    """

    # Общий namespace с PluginProcessNode
    __identifier__ = "constructor.nodes"
    NODE_NAME = "ShmRouteNode"

    def __init__(self, qgraphics_item: type | None = None) -> None:
        super().__init__(qgraphics_item or RouteNodeItem)
        # Custom properties для хранения данных route-ноды
        self.create_property("route_key", "")
        self.create_property("shm_name", "")
        # Один фиксированный входной порт
        self.add_input("in", multi_input=False)

    def set_route_data(
        self,
        route_key: str,
        shm_name: str,
        output_count: int,
    ) -> None:
        """Установить данные route-ноды и создать выходные порты.

        Args:
            route_key: Уникальный ключ route-ноды (source_addr fan-out).
            shm_name: Имя SHM-канала, отображается в body.
            output_count: Количество выходных портов для создания.
        """
        self.set_property("route_key", route_key)
        self.set_property("shm_name", shm_name)

        # Обновить отрисовку RouteNodeItem
        view = self.view
        if isinstance(view, RouteNodeItem):
            view.set_shm_name(shm_name)

        # Удалить все существующие выходные порты
        for port in list(self.output_ports()):
            self.delete_output(port)

        # Создать нужное количество выходных портов
        for i in range(output_count):
            self.add_output(f"out_{i + 1}")

        logger.debug(
            "ShmRouteNode '%s': route_key=%s, shm=%s, outputs=%d",
            self.name(),
            route_key,
            shm_name,
            output_count,
        )

    def add_fan_out_port(self, name: str = "") -> None:
        """Добавить выходной порт fan-out.

        Args:
            name: Имя порта. Если пустое — автоматически out_{N}.
        """
        existing_count = len(self.output_ports())
        port_name = name if name else f"out_{existing_count + 1}"
        self.add_output(port_name)
        logger.debug("ShmRouteNode: добавлен порт '%s'", port_name)

    def remove_fan_out_port(self, name: str) -> None:
        """Удалить выходной порт fan-out по имени.

        Args:
            name: Имя порта для удаления.
        """
        for port in self.output_ports():
            if port.name() == name:
                self.delete_output(port)
                logger.debug("ShmRouteNode: удалён порт '%s'", name)
                return
        logger.warning("ShmRouteNode: порт '%s' не найден", name)

    @property
    def route_key(self) -> str:
        """Уникальный ключ route-ноды (source_addr fan-out)."""
        return self.get_property("route_key") or ""

    @property
    def shm_name(self) -> str:
        """Имя SHM-канала для отображения."""
        return self.get_property("shm_name") or ""


# Тип ноды для NodeGraphQt create_node()
ROUTE_NODE_TYPE = "constructor.nodes.ShmRouteNode"

__all__ = ["ShmRouteNode", "RouteNodeItem", "ROUTE_NODE_TYPE"]
