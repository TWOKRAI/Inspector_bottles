"""DisplayTargetNode — нода канваса конструктора для display-окна.

Фаза 6: Display assignment.
Представляет display-окно на канвасе. Wire от process output -> display.frame
назначает поток на экран.

Один входной порт "frame". Визуально: зеленоватый фон (#3a5a3a),
заголовок "Display", body — имя + fps_limit.

Паттерн: ShmRouteNode (NodeItem subclass + BaseNode subclass).
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
_DISPLAY_LINE_HEIGHT = 15.0
_DISPLAY_PADDING_TOP = 4.0
_DISPLAY_FONT_SIZE_LABEL = 10
_DISPLAY_FONT_SIZE_INFO = 9

# Фоновый цвет display-ноды — зеленоватый, отличается от route-ноды
_DISPLAY_BG_COLOR = (58, 90, 58, 255)

# Минимальные размеры display-ноды
_DISPLAY_MIN_WIDTH = 140.0
_DISPLAY_MIN_HEIGHT = 60.0


class DisplayNodeItem(NodeItem):
    """QGraphicsItem для display-ноды — отображает имя экрана и fps_limit.

    Расширяет NodeItem: добавляет текстовый блок с меткой "Display"
    и строкой "{name} @ {fps_limit}fps" ниже заголовка.
    Фоновый цвет зеленоватый — отличает display-ноды от остальных.
    """

    def __init__(
        self,
        name: str = "node",
        parent: QtWidgets.QGraphicsItem | None = None,
    ) -> None:
        super().__init__(name, parent)
        self._display_name: str = ""
        self._fps_limit: int = 30
        # Минимальные размеры ноды
        self._min_width = _DISPLAY_MIN_WIDTH
        self._min_height = _DISPLAY_MIN_HEIGHT
        # Задаём зеленоватый фоновый цвет ноды
        self.color = _DISPLAY_BG_COLOR

    def set_display_info(self, name: str, fps_limit: int) -> None:
        """Обновить отображаемое имя и fps_limit ноды.

        Args:
            name: Имя display-окна для вывода в body.
            fps_limit: Ограничение fps. 0 = без ограничений.
        """
        self._display_name = name
        self._fps_limit = fps_limit
        self.update()

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionGraphicsItem,
        widget: QtWidgets.QWidget | None = None,
    ) -> None:
        """Рисуем стандартную ноду + метку Display и строку с именем/fps в body."""
        # Стандартная отрисовка NodeGraphQt (заголовок, порты, border)
        super().paint(painter, option, widget)

        from PySide6 import QtCore, QtGui as QtG

        painter.save()

        rect = self.boundingRect()
        # Начинаем ниже заголовка ноды (~26px от верха)
        y_start = 28.0 + _DISPLAY_PADDING_TOP
        x_left = rect.x() + 10.0

        # Метка типа ноды — "Display" зелёным цветом, жирный шрифт
        font = painter.font()
        font.setPixelSize(_DISPLAY_FONT_SIZE_LABEL)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QtG.QColor("#7acc7a"))
        painter.drawText(
            QtCore.QPointF(x_left, y_start + _DISPLAY_LINE_HEIGHT * 0.75),
            "Display",
        )

        # Строка с именем и fps — белым, обычный шрифт
        font.setBold(False)
        font.setPixelSize(_DISPLAY_FONT_SIZE_INFO)
        painter.setFont(font)
        painter.setPen(QtG.QColor("#cccccc"))

        # Формируем строку fps: 0 означает без ограничений
        fps_text = "unlimited" if self._fps_limit == 0 else f"{self._fps_limit}fps"
        # Если имя не задано — выводим только fps
        if self._display_name:
            info_line = f"{self._display_name} @ {fps_text}"
        else:
            info_line = fps_text

        painter.drawText(
            QtCore.QPointF(
                x_left,
                y_start + _DISPLAY_LINE_HEIGHT * 0.75 + _DISPLAY_LINE_HEIGHT,
            ),
            info_line,
        )

        painter.restore()


class DisplayTargetNode(BaseNode):
    """Нода NodeGraphQt = display-окно для вывода видеопотока.

    Принимает один входной порт "frame". Wire от выхода процесса к этому
    порту назначает поток на конкретный display.
    Имя окна и fps_limit задаются через set_display_data().

    Регистрация: graph.register_node(DisplayTargetNode)
    Создание:    graph.create_node("constructor.nodes.DisplayTargetNode")
    """

    # Общий namespace с ShmRouteNode и PluginProcessNode
    __identifier__ = "constructor.nodes"
    NODE_NAME = "DisplayTargetNode"

    def __init__(self, qgraphics_item: type | None = None) -> None:
        super().__init__(qgraphics_item or DisplayNodeItem)
        # Custom properties для хранения данных display-ноды
        self.create_property("display_key", "")
        self.create_property("display_name", "")
        self.create_property("fps_limit", 30)
        # Один фиксированный входной порт
        self.add_input("frame", multi_input=False, display_name=True)

    def set_display_data(
        self,
        display_key: str,
        name: str,
        fps_limit: int,
    ) -> None:
        """Установить данные display-ноды и обновить визуальное отображение.

        Args:
            display_key: Уникальный ключ display-окна.
            name: Человекочитаемое имя. Если пустое — используется display_key.
            fps_limit: Ограничение fps. 0 = без ограничений.
        """
        self.set_property("display_key", display_key)
        # Если имя не передано — используем ключ как имя
        resolved_name = name if name else display_key
        self.set_property("display_name", resolved_name)
        self.set_property("fps_limit", fps_limit)

        # Обновить визуальное отображение DisplayNodeItem
        view = self.view
        if isinstance(view, DisplayNodeItem):
            view.set_display_info(resolved_name, fps_limit)

        logger.debug(
            "DisplayTargetNode '%s': display_key=%s, name=%s, fps_limit=%d",
            self.name(),
            display_key,
            resolved_name,
            fps_limit,
        )

    @property
    def display_key(self) -> str:
        """Уникальный ключ display-окна."""
        return self.get_property("display_key") or ""


# Тип ноды для NodeGraphQt create_node()
DISPLAY_NODE_TYPE = "constructor.nodes.DisplayTargetNode"

__all__ = ["DisplayTargetNode", "DisplayNodeItem", "DISPLAY_NODE_TYPE"]
