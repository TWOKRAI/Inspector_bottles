"""DisplayNodeItem -- узел SHM-канала (display) на QGraphicsScene.

Отличия от NodeItem:
- Категория фиксирована как «display», цвет фона DISPLAY_CATEGORY_COLOR.
- Заголовок статический: «Display».
- Подзаголовок: display_name или display_id если имя пустое.
- Ровно ОДИН входной порт «frame», выходных нет.
- Метод set_display() обновляет display_id / display_name без пересоздания узла.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem

from .constants import DISPLAY_CATEGORY_COLOR, NODE_CORNER_RADIUS, NODE_HEIGHT, NODE_WIDTH
from .port_item import PortItem


@dataclass
class DisplayNodeData:
    """Данные узла Display (привязка к SHM-каналу).

    Категория всегда «display» — отдельный датакласс, не наследует NodeData.
    """

    node_id: str
    display_id: str
    display_name: str = ""
    x: float = 0.0
    y: float = 0.0

    @property
    def category(self) -> str:
        """Категория фиксирована."""
        return "display"


class DisplayNodeItem(QGraphicsRectItem):
    """Визуальный узел Display на QGraphicsScene.

    Рисует зелёный прямоугольник с заголовком «Display» и подзаголовком
    (display_name или display_id). Movable, selectable.
    Один входной порт «frame» на левой стороне (середина высоты).
    Выходных портов нет.
    """

    def __init__(self, data: DisplayNodeData, parent=None) -> None:
        super().__init__(0, 0, NODE_WIDTH, NODE_HEIGHT, parent)
        self._data = data

        # Позиция на сцене
        self.setPos(data.x, data.y)

        # Флаги: перемещаемый, выделяемый, отслеживать изменения позиции
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Флаг реального перетаскивания (отличить drag от клика-выбора), free-layout.
        self._drag_moved = False

        # Стиль: зелёный фон, тёмная рамка
        self.setBrush(QBrush(QColor(DISPLAY_CATEGORY_COLOR)))
        self.setPen(QPen(QColor("#333333"), 1))

        # Заголовок — статический «Display»
        self._title_text = QGraphicsTextItem("Display", self)
        self._title_text.setDefaultTextColor(QColor("#ffffff"))
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(10)
        self._title_text.setFont(title_font)
        self._title_text.setPos(8, 4)

        # Подзаголовок — display_name или display_id
        subtitle = data.display_name if data.display_name else data.display_id
        self._subtitle_text = QGraphicsTextItem(subtitle, self)
        self._subtitle_text.setDefaultTextColor(QColor("#dddddd"))
        small_font = QFont()
        small_font.setPointSize(8)
        self._subtitle_text.setFont(small_font)
        self._subtitle_text.setPos(8, 28)

        # Порты: только один входной «frame» (левый край, середина)
        self._input_ports: list[PortItem] = []
        self._output_ports: list[PortItem] = []  # всегда пуст

        # endpoint порта = "display.<node_id>.frame" — этот префикс распознаётся
        # presenter.add_wire как display-target (→ dispatch(BindDisplay)). node_id
        # бокса = display_id (канал). См. ADR DOM-001.
        frame_port = PortItem(
            "input",
            f"display.{data.node_id}.frame",
            "display",
            parent=self,
        )
        frame_port.setPos(0, NODE_HEIGHT / 2)
        frame_port.setToolTip("frame: image/*")
        self._input_ports.append(frame_port)

    # ------------------------------------------------------------------ #
    #  Публичный API                                                        #
    # ------------------------------------------------------------------ #

    @property
    def node_id(self) -> str:
        """ID узла (для совместимости с сигналами GraphScene)."""
        return self._data.node_id

    @property
    def data(self) -> DisplayNodeData:
        """Внутренние данные узла (read-only доступ)."""
        return self._data

    @property
    def display_id(self) -> str:
        """ID SHM-канала (для round-trip сериализации)."""
        return self._data.display_id

    @property
    def input_ports(self) -> list[PortItem]:
        """Входные порты узла (ровно один: frame)."""
        return list(self._input_ports)

    @property
    def output_ports(self) -> list[PortItem]:
        """Выходные порты — всегда пустой список."""
        return list(self._output_ports)

    def set_display(self, display_id: str, display_name: str = "") -> None:
        """Обновить привязку к SHM-каналу без пересоздания узла.

        Меняет display_id, display_name и перерисовывает подзаголовок.
        """
        self._data.display_id = display_id
        self._data.display_name = display_name

        subtitle = display_name if display_name else display_id
        self._subtitle_text.setPlainText(subtitle)
        self.update()

    # ------------------------------------------------------------------ #
    #  Позиционирование портов                                              #
    # ------------------------------------------------------------------ #

    def input_port_pos(self) -> tuple[float, float]:
        """Позиция входного порта «frame» в scene coordinates."""
        pos = self.pos()
        if self._input_ports:
            port_y = self._input_ports[0].pos().y()
            return pos.x(), pos.y() + port_y
        return pos.x(), pos.y() + NODE_HEIGHT / 2

    def output_port_pos(self) -> tuple[float, float]:
        """Позиция выходного порта — нет, возвращаем правый край для совместимости."""
        pos = self.pos()
        return pos.x() + NODE_WIDTH, pos.y() + NODE_HEIGHT / 2

    # ------------------------------------------------------------------ #
    #  Отрисовка                                                            #
    # ------------------------------------------------------------------ #

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """Рисуем скруглённый прямоугольник (аналогично NodeItem)."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        painter.setBrush(self.brush())

        if self.isSelected():
            painter.setPen(QPen(QColor("#ffffff"), 2))
        else:
            painter.setPen(self.pen())

        painter.drawRoundedRect(rect, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

    def itemChange(self, change, value):
        """Обновить edge'ы при перемещении узла (аналогично NodeItem)."""
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            self._drag_moved = True
            scene = self.scene()
            if scene is not None and hasattr(scene, "on_node_moved"):
                scene.on_node_moved(self._data.node_id)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Начало взаимодействия — сбросить флаг перетаскивания."""
        self._drag_moved = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Завершение перетаскивания → зафиксировать новую позицию (free-layout).

        Только при реальном перемещении: scene эмитит node_position_changed,
        presenter дебаунс-сохраняет позицию бокса в рецепт.
        """
        super().mouseReleaseEvent(event)
        if getattr(self, "_drag_moved", False):
            self._drag_moved = False
            scene = self.scene()
            if scene is not None and hasattr(scene, "on_node_drag_finished"):
                scene.on_node_drag_finished(self._data.node_id)
