"""sources_tree_config — конфигурация EntityTreeWidget для вкладки «Источники».

Определяет структуру дерева камер/регионов:
- Parent level: камеры (camera_type, fps, resolution, channels, process_name, ...)
- Child level: регионы (x1, y1, x2, y2, enabled, is_main, processing_enabled, shm_enabled)
"""
from __future__ import annotations

from multiprocess_prototype.frontend.widgets.base.editor.entity_tree_config import (
    EntityLevel,
    EntityTreeConfig,
    ParamDef,
)


# ------------------------------------------------------------------
# Функции построения сводок
# ------------------------------------------------------------------

def _camera_summary(data: dict) -> str:
    """Построить строку сводки для камеры.

    Формат: «process_name | exec_mode | WxH | FPSfps»

    Args:
        data: Плоский dict значений параметров камеры.

    Returns:
        Строка сводки.
    """
    process_name = data.get("process_name", "")
    exec_mode = data.get("execution_mode", "process")
    resolution = data.get("resolution", "—")
    fps = data.get("fps", "—")
    return f"{process_name} | {exec_mode} | {resolution} | {fps}fps"


def _region_summary(data: dict) -> str:
    """Построить строку сводки для региона.

    Формат: «WxH main proc shm» (только активные флаги).

    Args:
        data: Плоский dict значений параметров региона.

    Returns:
        Строка сводки.
    """
    # Ширина и высота вычисляются из координат
    try:
        x1 = int(data.get("x1", 0))
        y1 = int(data.get("y1", 0))
        x2 = int(data.get("x2", 0))
        y2 = int(data.get("y2", 0))
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
    except (ValueError, TypeError):
        w, h = 0, 0

    flags: list[str] = []
    # Проверяем bool-поля (могут быть строками или bool)
    if _is_truthy(data.get("is_main", False)):
        flags.append("main")
    if _is_truthy(data.get("processing_enabled", True)):
        flags.append("proc")
    if _is_truthy(data.get("shm_enabled", False)):
        flags.append("shm")
    flags_str = " ".join(flags)
    return f"{w}×{h} {flags_str}".strip()


def _is_truthy(val: object) -> bool:
    """Проверить, является ли значение истинным (поддержка строковых "True"/"False").

    Args:
        val: Значение для проверки.

    Returns:
        True если значение истинно.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() == "true"
    return bool(val)


def _format_bool(val: object) -> str:
    """Отформатировать булево значение как ✓/✗.

    Args:
        val: Значение (bool или строка "True"/"False").

    Returns:
        «✓» или «✗».
    """
    return "✓" if _is_truthy(val) else "✗"


# ------------------------------------------------------------------
# Конфигурация дерева источников
# ------------------------------------------------------------------

SOURCES_TREE_CONFIG = EntityTreeConfig(
    columns=["Элемент", "Актив./Значение", "Комментарий", "Сводка"],
    parent_level=EntityLevel(
        name="camera",
        role_key="camera",
        icon="■",
        bold=True,
        params=[
            ParamDef("camera_type", "Тип", "Тип источника"),
            ParamDef("fps", "FPS", "Частота кадров", editable=True),
            ParamDef("resolution", "Разрешение", "Размер кадра"),
            ParamDef("channels", "Каналы", "RGB / Gray"),
            ParamDef("process_name", "Процесс", "Имя процесса", editable=True),
            ParamDef("execution_mode", "Режим", "process / thread", editable=True),
            ParamDef("region_processing", "Нарезка", "same_process / dedicated_processor", editable=True),
            ParamDef("ring_slots", "SHM ring", "Слоты кольцевого буфера", editable=True),
        ],
        summary_builder=_camera_summary,
    ),
    child_level=EntityLevel(
        name="region",
        role_key="region",
        icon="□",
        bold=False,
        params=[
            ParamDef("x1", "x1", "Левый край", editable=True),
            ParamDef("y1", "y1", "Верхний край", editable=True),
            ParamDef("x2", "x2", "Правый край", editable=True),
            ParamDef("y2", "y2", "Нижний край", editable=True),
            ParamDef("enabled", "enabled", "Активность региона", is_bool=True, formatter=_format_bool),
            ParamDef("is_main", "is_main", "Основной регион", is_bool=True, formatter=_format_bool),
            ParamDef("processing_enabled", "processing_enabled", "Обработка включена", is_bool=True, formatter=_format_bool),
            ParamDef("shm_enabled", "shm_enabled", "Отдельный SHM слот", is_bool=True, formatter=_format_bool),
        ],
        summary_builder=_region_summary,
    ),
    column_widths=[200, 120, 150, 280],
)


__all__ = ["SOURCES_TREE_CONFIG"]
