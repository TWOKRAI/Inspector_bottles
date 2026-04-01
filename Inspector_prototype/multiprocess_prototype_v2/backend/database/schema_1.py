# multiprocess_prototype\database\schema_1.py
"""
DetectionSchema — единственный источник полей для БД и сообщений.

Используется для:
- создания таблицы detections (CREATE TABLE)
- формирования payload команды db.save_detections (Processor)
- валидации и вставки (DatabaseProcess)
"""
from typing import Optional

from multiprocess_framework.modules.data_schema_module import (
    register_schema,
    SchemaBase,
)


@register_schema("DetectionSchema")
class DetectionSchema(SchemaBase):
    """Схема одной детекции. БД и сообщения — одни и те же поля."""

    id: Optional[int] = None
    timestamp: float = 0.0
    frame_name: str = ""
    frame_id: int = 0
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0
    center_x: int = 0
    center_y: int = 0
    area: int = 0
