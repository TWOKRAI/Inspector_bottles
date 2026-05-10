"""Константы для вкладки «Источники».

Роли данных теперь совпадают с EntityTreeWidget для единого визуального стиля.
Алиасы ROLE_CAM / ROLE_REG сохранены для обратной совместимости с widget.py.
"""
from __future__ import annotations

from multiprocess_prototype.frontend.widgets.base.editor.entity_tree_widget import (
    ROLE_CHILD,
    ROLE_PARAM,
    ROLE_PARENT,
    ROLE_TYPE,
)

# Алиасы: sources-специфичные имена -> универсальные роли EntityTreeWidget
# widget.py использует ROLE_CAM / ROLE_REG — они совпадают с ROLE_PARENT / ROLE_CHILD
ROLE_CAM = ROLE_PARENT   # ключ камеры
ROLE_REG = ROLE_CHILD    # ключ региона
# ROLE_TYPE и ROLE_PARAM — реэкспорт напрямую

DEFAULT_REGION = "main_image"

# Индексы колонок
COL_NAME = 0
COL_VAL = 1      # Актив./Значение
COL_COMMENT = 2
COL_SUMMARY = 3

# Параметры камеры для отображения в дереве
# (display_name, param_key, description)
CAM_PARAMS: list[tuple[str, str, str]] = [
    ("Тип", "camera_type", "Тип источника"),
    ("FPS", "fps", "Частота кадров"),
    ("Разрешение", "resolution", "Размер кадра"),
    ("Каналы", "channels", "RGB / Grayscale"),
    ("Процесс", "process_name", "Имя процесса"),
    ("Режим", "execution_mode", "process / thread"),
    ("Нарезка", "region_processing", "same_process / dedicated_processor"),
    ("SHM ring", "ring_slots", "Слоты кольцевого буфера"),
]

# Параметры, которые нельзя редактировать inline
CAM_READONLY_PARAMS = {"resolution", "channels"}

# Параметры региона для отображения в дереве
REG_PARAMS: list[tuple[str, str, str]] = [
    ("x1", "x1", "Левый край"),
    ("y1", "y1", "Верхний край"),
    ("x2", "x2", "Правый край"),
    ("y2", "y2", "Нижний край"),
    ("enabled", "enabled", "Активность региона"),
    ("is_main", "is_main", "Основной регион"),
    ("processing_enabled", "processing_enabled", "Обработка включена"),
    ("shm_enabled", "shm_enabled", "Отдельный SHM слот"),
]

__all__ = [
    "ROLE_TYPE", "ROLE_CAM", "ROLE_REG", "ROLE_PARAM",
    "ROLE_PARENT", "ROLE_CHILD",
    "DEFAULT_REGION",
    "COL_NAME", "COL_VAL", "COL_COMMENT", "COL_SUMMARY",
    "CAM_PARAMS", "CAM_READONLY_PARAMS", "REG_PARAMS",
]
