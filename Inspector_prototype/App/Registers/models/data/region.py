# -*- coding: utf-8 -*-
"""
Модель данных региона.
"""
from pydantic import BaseModel, Field
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .chain import ChainStepData


class RegionData(BaseModel):
    """Структура данных региона"""
    x1: int = Field(description='Координата X1 (левая граница)')
    y1: int = Field(description='Координата Y1 (верхняя граница)')
    x2: int = Field(description='Координата X2 (правая граница)')
    y2: int = Field(description='Координата Y2 (нижняя граница)')
    enabled: bool = Field(default=True, description='Включен ли регион')
    is_main: bool = Field(default=False, description='Является ли регион основным изображением')
    processing_enabled: bool = Field(default=True, description='Включена ли обработка для региона')
    chains: List['ChainStepData'] = Field(default_factory=list, description='Цепочка обработки региона')
