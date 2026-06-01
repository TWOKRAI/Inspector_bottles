"""NodeItem -- узел процесса на QGraphicsScene."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsTextItem

from .constants import CATEGORY_COLORS, NODE_CORNER_RADIUS, NODE_HEIGHT, NODE_WIDTH
from .port_item import PortItem
from .port_schema import PortSchema


@dataclass
class NodeData:
    """Абстрактные данные узла (не привязан к SystemBlueprint).

    Pipeline node = плагин (D.1): один процесс рисуется как контейнер с N
    отдельными нодами-плагинами. `node_id` плагин-ноды = ``{process}.{plugin}``.
    Поля process_name/plugin_index/plugin_name несут принадлежность к процессу
    и позицию в цепочке — нужны для группировки в контейнер (scene), drag между
    контейнерами и маршрутизации SetPluginConfig/MovePlugin (presenter).

    Поля добавлены В КОНЦЕ с дефолтами — позиционные вызовы
    ``NodeData(node_id, title, subtitle, category, x, y)`` остаются валидны.
    Узлы без process_name (raw-тесты, legacy) не группируются в контейнер.
    """

    node_id: str
    title: str
    subtitle: str = ""  # обычно category
    category: str = "utility"
    x: float = 0.0
    y: float = 0.0
    # Принадлежность к процессу (пусто → нода вне контейнера, legacy)
    process_name: str = ""
    # Индекс плагина в цепочке процесса (-1 → процесс без плагинов, fallback-нода)
    plugin_index: int = -1
    # Имя плагина (= имя регистра; пусто для process-fallback ноды)
    plugin_name: str = ""
    # Зафиксирована ли нода: не перетаскивается и пропускается авто-раскладкой.
    locked: bool = False


class NodeItem(QGraphicsRectItem):
    """Визуальный узел процесса на QGraphicsScene.

    Рисует: закрашенный прямоугольник с заголовком и подзаголовком (категория).
    Movable, selectable. Цвет по категории.

    Поддерживает Schema-Driven Ports: если передан port_schemas,
    создаёт N портов из схем (input слева, output справа).
    Иначе — backward compat: 1 input + 1 output.
    """

    def __init__(
        self,
        data: NodeData,
        port_schemas: list[PortSchema] | None = None,
        parent=None,
    ) -> None:
        super().__init__(0, 0, NODE_WIDTH, NODE_HEIGHT, parent)
        self._data = data

        # Позиция
        self.setPos(data.x, data.y)

        # Флаги. Перемещаемость зависит от lock: зафиксированную ноду не двигаем.
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, not data.locked)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges)

        # Стиль
        color = CATEGORY_COLORS.get(data.category, CATEGORY_COLORS["utility"])
        self.setBrush(QBrush(QColor(color)))
        self.setPen(QPen(QColor("#333333"), 1))

        # Текст -- title
        self._title_text = QGraphicsTextItem(data.title, self)
        self._title_text.setDefaultTextColor(QColor("#ffffff"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(10)
        self._title_text.setFont(font)
        self._title_text.setPos(8, 4)

        # Текст -- subtitle (категория)
        self._subtitle_text = QGraphicsTextItem(data.subtitle, self)
        self._subtitle_text.setDefaultTextColor(QColor("#dddddd"))
        small_font = QFont()
        small_font.setPointSize(8)
        self._subtitle_text.setFont(small_font)
        self._subtitle_text.setPos(8, 28)

        # D.3: флаг реального перетаскивания (отличить drag от простого клика-выбора).
        # Сбрасывается на mousePress, взводится в itemChange при смене позиции,
        # проверяется на mouseRelease → scene.on_node_drag_finished только при move.
        self._drag_moved = False

        # Порты (визуальные)
        self._input_ports: list[PortItem] = []
        self._output_ports: list[PortItem] = []

        if port_schemas is not None:
            # Schema-Driven: создать N портов из схем
            self._create_ports_from_schemas(port_schemas)
        else:
            # Backward compat: 1 input + 1 output
            self._create_default_ports()

    def _create_default_ports(self) -> None:
        """Создать один input и один output порт (backward compat)."""
        node_id = self._data.node_id
        category = self._data.category

        input_port = PortItem(
            "input",
            f"{node_id}.input",
            category,
            parent=self,
        )
        input_port.setPos(0, NODE_HEIGHT / 2)  # Левый край, середина
        self._input_ports.append(input_port)

        output_port = PortItem(
            "output",
            f"{node_id}.output",
            category,
            parent=self,
        )
        output_port.setPos(NODE_WIDTH, NODE_HEIGHT / 2)  # Правый край, середина
        self._output_ports.append(output_port)

    def _create_ports_from_schemas(self, schemas: list[PortSchema]) -> None:
        """Создать порты из схем (Schema-Driven Ports).

        Input-порты слева, output-порты справа, равномерно по высоте.
        Tooltip: "{schema.name}: {schema.dtype}".
        """
        node_id = self._data.node_id
        category = self._data.category

        # Разделить схемы на input и output
        input_schemas = [s for s in schemas if s.direction == "input"]
        output_schemas = [s for s in schemas if s.direction == "output"]

        # Создать input-порты (левый край)
        for i, schema in enumerate(input_schemas):
            y = self._port_y_position(i, len(input_schemas))
            endpoint = f"{node_id}.{schema.name}"
            port = PortItem("input", endpoint, category, parent=self)
            port.setPos(0, y)
            port.setToolTip(f"{schema.name}: {schema.dtype}")
            self._input_ports.append(port)

        # Создать output-порты (правый край)
        for i, schema in enumerate(output_schemas):
            y = self._port_y_position(i, len(output_schemas))
            endpoint = f"{node_id}.{schema.name}"
            port = PortItem("output", endpoint, category, parent=self)
            port.setPos(NODE_WIDTH, y)
            port.setToolTip(f"{schema.name}: {schema.dtype}")
            self._output_ports.append(port)

    def _port_y_position(self, index: int, total: int) -> float:
        """Вычислить Y-позицию порта при равномерном распределении по высоте.

        Если total == 1 — порт в середине узла.
        Если total > 1 — равномерно от 20% до 80% высоты узла.
        """
        if total == 1:
            return NODE_HEIGHT / 2
        # Равномерно распределить от 20% до 80% высоты
        margin_top = NODE_HEIGHT * 0.2
        margin_bottom = NODE_HEIGHT * 0.8
        step = (margin_bottom - margin_top) / (total - 1)
        return margin_top + index * step

    # ---- Properties ---- #

    @property
    def node_id(self) -> str:
        return self._data.node_id

    @property
    def data(self) -> NodeData:
        return self._data

    @property
    def locked(self) -> bool:
        """Зафиксирована ли нода (не перетаскивается)."""
        return self._data.locked

    def set_locked(self, locked: bool) -> None:
        """Зафиксировать/освободить ноду: меняет ItemIsMovable и перерисовывает."""
        self._data.locked = locked
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, not locked)
        self.update()

    @property
    def process_name(self) -> str:
        """Имя процесса, которому принадлежит плагин-нода (пусто → вне контейнера)."""
        return self._data.process_name

    @property
    def plugin_index(self) -> int:
        """Индекс плагина в цепочке процесса (-1 → process-fallback нода)."""
        return self._data.plugin_index

    @property
    def input_ports(self) -> list[PortItem]:
        """Все input-порты узла."""
        return list(self._input_ports)

    @property
    def output_ports(self) -> list[PortItem]:
        """Все output-порты узла."""
        return list(self._output_ports)

    @property
    def input_port(self) -> PortItem:
        """Первый input-порт (backward compat)."""
        return self._input_ports[0]

    @property
    def output_port(self) -> PortItem:
        """Первый output-порт (backward compat)."""
        return self._output_ports[0]

    def paint(self, painter: QPainter, option, widget=None) -> None:
        """Рисуем скруглённый прямоугольник."""
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Заливка
        painter.setBrush(self.brush())

        # Рамка: белая при выделении, золотая у зафиксированной, иначе обычная.
        if self.isSelected():
            painter.setPen(QPen(QColor("#ffffff"), 2))
        elif self._data.locked:
            painter.setPen(QPen(QColor("#ffc107"), 2))  # золотая = зафиксирована
        else:
            painter.setPen(self.pen())

        painter.drawRoundedRect(rect, NODE_CORNER_RADIUS, NODE_CORNER_RADIUS)

    def itemChange(self, change, value):
        """Обновить edge'ы при перемещении узла."""
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionHasChanged:
            self._drag_moved = True
            scene = self.scene()
            if scene is not None and hasattr(scene, "on_node_moved"):
                scene.on_node_moved(self._data.node_id)
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        """Начало взаимодействия — сбросить флаг перетаскивания (D.3)."""
        self._drag_moved = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """Завершение перетаскивания → уведомить scene (D.3).

        Только при реальном перемещении (не простой клик-выбор): scene определит
        целевой контейнер и решит про MovePlugin (cross-process / reorder).
        """
        super().mouseReleaseEvent(event)
        if self._drag_moved:
            self._drag_moved = False
            scene = self.scene()
            if scene is not None and hasattr(scene, "on_node_drag_finished"):
                scene.on_node_drag_finished(self._data.node_id)

    def center_pos(self) -> tuple[float, float]:
        """Центр узла в scene coordinates."""
        pos = self.pos()
        return pos.x() + NODE_WIDTH / 2, pos.y() + NODE_HEIGHT / 2

    def output_port_pos(self) -> tuple[float, float]:
        """Позиция первого выходного порта (правый край, середина)."""
        pos = self.pos()
        if self._output_ports:
            port_y = self._output_ports[0].pos().y()
            return pos.x() + NODE_WIDTH, pos.y() + port_y
        return pos.x() + NODE_WIDTH, pos.y() + NODE_HEIGHT / 2

    def input_port_pos(self) -> tuple[float, float]:
        """Позиция первого входного порта (левый край, середина)."""
        pos = self.pos()
        if self._input_ports:
            port_y = self._input_ports[0].pos().y()
            return pos.x(), pos.y() + port_y
        return pos.x(), pos.y() + NODE_HEIGHT / 2
