"""entity_tree_config — декларативный конфиг для универсального дерева EntityTreeWidget.

Чистые dataclass-ы без Qt-зависимостей. Определяют структуру дерева:
колонки, уровни иерархии (parent/child), параметры каждого уровня.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ParamDef:
    """Определение одного параметра для отображения в дереве.

    Attributes:
        key:       Ключ в dict данных ("class_path", "fps", ...).
        label:     Отображаемое имя ("Класс", "FPS", ...).
        comment:   Подсказка / описание ("Класс процесса", "Частота кадров", ...).
        editable:  Можно ли редактировать inline.
        is_bool:   Показывать как булевый флаг (True/False).
        formatter: Кастомная функция форматирования значения (value -> str).
    """

    key: str
    label: str
    comment: str = ""
    editable: bool = False
    is_bool: bool = False
    formatter: Callable[[object], str] | None = None


@dataclass
class EntityLevel:
    """Определение одного уровня иерархии (parent или child).

    Attributes:
        name:            Имя уровня ("process", "camera", "worker", "region").
        role_key:        Ключ роли для идентификации при selection persistence.
        params:          Параметры этого уровня для отображения в группе «Параметры».
        icon:            Иконка элемента ("■", "□").
        bold:            Bold шрифт для имени.
        summary_builder: Функция построения строки сводки (data_dict -> str).
    """

    name: str
    role_key: str
    params: list[ParamDef]
    icon: str = "□"
    bold: bool = False
    summary_builder: Callable[[dict], str] | None = None


@dataclass
class EntityTreeConfig:
    """Полная конфигурация дерева.

    Attributes:
        columns:       Заголовки колонок (обычно 4: имя, значение, комментарий, сводка).
        parent_level:  Конфиг родительских элементов (верхний уровень).
        child_level:   Конфиг дочерних элементов (второй уровень).
        column_widths: Ширины колонок в пикселях (опционально).
    """

    columns: list[str]
    parent_level: EntityLevel
    child_level: EntityLevel
    column_widths: list[int] = field(default_factory=list)


__all__ = ["ParamDef", "EntityLevel", "EntityTreeConfig"]
