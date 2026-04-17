"""Detection database schema."""

from typing import Optional

from multiprocess_framework.modules.data_schema_module import SchemaBase, register_schema


@register_schema("DetectionSchemaV3")
class DetectionSchema(SchemaBase):
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
