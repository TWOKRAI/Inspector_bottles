"""
Данные региона обработки (вспомогательная модель).
Поля заданы через единую схему field_data.data_schema, как в field_registers/draw.py.
"""
from typing import List

from pydantic import BaseModel, Field

from App.Registers.models.field_data.chain import ChainStepData
from App.Registers.models.field_data.data_schema import (
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema,
)


class RegionData(BaseModel):
    """Данные региона обработки."""

    x1: int = field_from_schema(
        0,
        description='Координата X1 региона',
        info='Левая верхняя координата X региона (px).',
        min=0,
    )
    y1: int = field_from_schema(
        0,
        description='Координата Y1 региона',
        info='Левая верхняя координата Y региона (px).',
        min=0,
    )
    x2: int = field_from_schema(
        0,
        description='Координата X2 региона',
        info='Правая нижняя координата X региона (px).',
        min=0,
    )
    y2: int = field_from_schema(
        0,
        description='Координата Y2 региона',
        info='Правая нижняя координата Y региона (px).',
        min=0,
    )
    enabled: bool = field_from_schema(
        True,
        description='Включён ли регион',
        info='Включён ли регион обработки.',
    )
    is_main: bool = field_from_schema(
        False,
        description='Основной ли это регион',
        info='Является ли регион основным (главным) для отображения.',
    )
    processing_enabled: bool = field_from_schema(
        True,
        description='Включена ли обработка в этом регионе',
        info='Включена ли обработка изображения в данном регионе.',
    )
    chains: List[ChainStepData] = Field(
        default_factory=list,
        description='Цепочки обработки региона',
        json_schema_extra={
            **DEFAULT_DATA_FIELD_SCHEMA,
            'info': 'Цепочка шагов обработки региона.',
        },
    )
