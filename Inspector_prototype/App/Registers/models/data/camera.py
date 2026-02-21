# -*- coding: utf-8 -*-
"""
Модель данных камеры.
"""
from pydantic import BaseModel, Field
from typing import Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .region import RegionData


class CameraData(BaseModel):
    """Структура данных камеры"""
    name: str = Field(description='Название камеры')
    hikvision_params: Dict[str, float] = Field(default_factory=dict, description='Параметры камеры Hikvision')
    region_order: List[str] = Field(default_factory=list, description='Порядок регионов')
    regions: Dict[str, 'RegionData'] = Field(default_factory=dict, description='Регионы камеры')
