"""PluginProcessNode — кастомная нода NodeGraphQt для процесса-суперузла.

Визуальное представление:
  +================================+
  | camera_0             [source]  |
  |--------------------------------|
  |  1. capture                    |
  |  2. grayscale                  |
  |  3. resize_50                  |
  |--------------------------------|
  | IN:           OUT:             |
  | o frame       o region_1       |
  |               o frame_original |
  +================================+

Каждый процесс = одна нода. Плагины — список строк в body.
Порты = входы первого плагина + выходы последнего.
Wire-соединения — только межпроцессные.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from NodeGraphQt import BaseNode
from NodeGraphQt.qgraphics.node_base import NodeItem

if TYPE_CHECKING:
    from PySide6 import QtCore, QtGui, QtWidgets

logger = logging.getLogger(__name__)

# Размеры для отрисовки списка плагинов
_PLUGIN_LINE_HEIGHT = 16.0
_PLUGIN_PADDING_TOP = 4.0
_PLUGIN_PADDING_BOTTOM = 8.0
_PLUGIN_FONT_SIZE = 9
_PRIORITY_COLORS = {
    "high": "#e8a838",
    "realtime": "#e85838",
    "normal": "#888888",
}


class ProcessNodeItem(NodeItem):
    """QGraphicsItem для процесса — рисует список плагинов в body ноды.

    Расширяет стандартный NodeItem: добавляет текстовый блок
    с пронумерованными плагинами ниже заголовка.
    """

    def __init__(
        self,
        name: str = "node",
        parent: QtWidgets.QGraphicsItem | None = None,
    ) -> None:
        super().__init__(name, parent)
        self._plugin_names: list[str] = []
        self._priority: str = "normal"

    def set_plugin_names(self, names: list[str]) -> None:
        """Обновить список плагинов для отрисовки."""
        self._plugin_names = list(names)
        # Расширяем высоту ноды под плагины
        extra_h = (
            len(names) * _PLUGIN_LINE_HEIGHT
            + _PLUGIN_PADDING_TOP
            + _PLUGIN_PADDING_BOTTOM
        )
        self._min_height = max(80.0, 60.0 + extra_h)

    def set_priority(self, priority: str) -> None:
        """Обновить приоритет процесса (влияет на цвет индикатора)."""
        self._priority = priority

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        """Рисуем стандартную ноду + список плагинов."""
        # Стандартная отрисовка NodeGraphQt (заголовок, порты, border)
        super().paint(painter, option, widget)

        if not self._plugin_names:
            return

        from PySide6 import QtCore, QtGui as QtG

        painter.save()

        # Шрифт для списка плагинов
        font = painter.font()
        font.setPixelSize(_PLUGIN_FONT_SIZE)
        painter.setFont(font)
        painter.setPen(QtG.QColor("#cccccc"))

        rect = self.boundingRect()
        # Начинаем ниже заголовка ноды (примерно 26px от верха)
        y_start = 28.0 + _PLUGIN_PADDING_TOP
        x_left = rect.x() + 10.0

        for idx, name in enumerate(self._plugin_names):
            y = y_start + idx * _PLUGIN_LINE_HEIGHT
            text = f"{idx + 1}. {name}"
            painter.drawText(
                QtCore.QPointF(x_left, y + _PLUGIN_LINE_HEIGHT * 0.75),
                text,
            )

        # Индикатор приоритета (маленький кружок в правом верхнем углу)
        if self._priority != "normal":
            color = _PRIORITY_COLORS.get(self._priority, "#888888")
            painter.setBrush(QtG.QColor(color))
            painter.setPen(QtG.QColor(color))
            painter.drawEllipse(
                QtCore.QPointF(rect.right() - 12.0, rect.y() + 12.0),
                4.0,
                4.0,
            )

        painter.restore()


class PluginProcessNode(BaseNode):
    """Нода NodeGraphQt = один процесс системы (суперузел).

    Плагины отображаются как список в body, порты = I/O цепочки.
    Регистрация: graph.register_node(PluginProcessNode)
    Создание:    graph.create_node("constructor.nodes.PluginProcessNode")
    """

    # NodeGraphQt v0.5.2 использует имя класса для type_,
    # а NODE_NAME — только для отображения.
    __identifier__ = "constructor.nodes"
    NODE_NAME = "PluginProcessNode"

    def __init__(self, qgraphics_item: type | None = None) -> None:
        super().__init__(qgraphics_item or ProcessNodeItem)
        # Custom properties для хранения данных процесса
        self.create_property("process_key", "")
        self.create_property("priority", "normal")

    def set_process_data(
        self,
        process_key: str,
        plugin_names: list[str],
        priority: str = "normal",
    ) -> None:
        """Установить данные процесса для отображения.

        Args:
            process_key: Ключ процесса в SystemTopologyEditor.
            plugin_names: Упорядоченный список имён плагинов.
            priority: Приоритет процесса (normal/high/realtime).
        """
        self.set_property("process_key", process_key)
        self.set_property("priority", priority)

        view = self.view
        if isinstance(view, ProcessNodeItem):
            view.set_plugin_names(plugin_names)
            view.set_priority(priority)

    @property
    def process_key(self) -> str:
        """Ключ процесса в topology editor."""
        return self.get_property("process_key") or ""

    @property
    def priority(self) -> str:
        return self.get_property("priority") or "normal"


# Тип ноды для NodeGraphQt create_node()
PROCESS_NODE_TYPE = "constructor.nodes.PluginProcessNode"

__all__ = ["PluginProcessNode", "ProcessNodeItem", "PROCESS_NODE_TYPE"]
