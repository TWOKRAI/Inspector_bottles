"""
Шаг цепочки обработки региона (вспомогательная модель).
Поля заданы через единую схему field_data.data_schema, как в field_registers/draw.py.
"""
from typing import Any, Dict

from pydantic import BaseModel, Field

from App.Registers.models.field_data.data_schema import (
    DEFAULT_DATA_FIELD_SCHEMA,
    field_from_schema,
)


class ChainStepData(BaseModel):
    """Шаг цепочки обработки региона."""

    processor_id: str = field_from_schema(
        '',
        description='Идентификатор процессора/алгоритма',
        info='Идентификатор процессора или алгоритма в цепочке обработки региона.',
    )
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description='Параметры шага обработки',
        json_schema_extra={
            **DEFAULT_DATA_FIELD_SCHEMA,
            'info': 'Параметры шага обработки региона.',
        },
    )
    enabled: bool = field_from_schema(
        True,
        description='Включён ли шаг обработки',
        info='Включён ли данный шаг в цепочке обработки региона.',
    )
