"""Чистые данные графа Pipeline — БЕЗ Qt-зависимостей (Трек F, Task F.1).

Здесь живут dataclass'ы, которыми обмениваются presenter/codec и Qt-слой сцены:
NodeData, EdgeData, DisplayNodeData, PortSchema. Раньше они были объявлены
рядом с QGraphicsItem-классами (node_item/edge_item/display_node_item), что
тянуло PySide6 в любой импорт данных и мешало headless-тестам codec.

Определения перенесены сюда дословно; старые модули ре-экспортируют их для
обратной совместимости (импорты `from .graph.node_item import NodeData` и т.п.
продолжают работать). Модуль не импортирует Qt — его можно грузить headless.
"""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class EdgeData:
    """Абстрактные данные связи.

    implicit=True — внутрипроцессная стрелка цепочки (порядок плагинов внутри
    одного процесса). Это НЕ domain-wire: рисуется пунктиром, не выделяется,
    не удаляется пользователем, не экспортируется и не шлёт edge-телеметрию.
    """

    source_id: str
    target_id: str
    label: str = ""
    implicit: bool = False


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


@dataclass
class PortSchema:
    """Описание одного порта плагина для визуализации.

    Атрибуты:
        name: имя порта ("frame", "mask", "stats")
        direction: направление порта ("input" | "output")
        dtype: тип данных в MIME-подобном формате ("image/bgr", "any", "image/*")
        optional: если True — порт может быть не подключён
    """

    name: str
    direction: str  # "input" | "output"
    dtype: str = "any"
    optional: bool = False


__all__ = ["NodeData", "EdgeData", "DisplayNodeData", "PortSchema"]
