"""
Данные камеры — основной тип данных (root).
Поля заданы через единую схему field_data.data_schema, как в field_registers/draw.py.
"""
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from App.Registers.models.field_data.region import RegionData
from App.Registers.models.field_data.data_schema import (
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema,
)


class CameraData(BaseModel):
    """Данные камеры (основная модель данных)."""

    name: str = field_from_schema(
        'unknown',
        description='Имя камеры',
        info='Отображаемое имя камеры.',
    )
    hikvision_params: Dict[str, Any] = Field(
        default_factory=dict,
        description='Параметры камеры Hikvision',
        json_schema_extra={
            **DEFAULT_DATA_FIELD_SCHEMA,
            'info': 'Параметры подключения/настройки камеры Hikvision.',
        },
    )
    region_order: List[str] = Field(
        default_factory=list,
        description='Порядок регионов обработки',
        json_schema_extra={
            **DEFAULT_DATA_FIELD_SCHEMA,
            'info': 'Порядок имён регионов для отображения и обработки.',
        },
    )
    regions: Dict[str, RegionData] = Field(
        default_factory=dict,
        description='Регионы обработки по имени',
        json_schema_extra={
            **DEFAULT_DATA_FIELD_SCHEMA,
            'info': 'Словарь регионов обработки (имя -> RegionData).',
        },
    )
