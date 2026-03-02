# -*- coding: utf-8 -*-
"""
RegionData — данные прямоугольного региона интереса (ROI).
"""
from typing import List

from pydantic import BaseModel, Field

from .chain import ChainStepData


class RegionData(BaseModel):
    """Прямоугольный регион интереса на изображении."""

    # Координаты прямоугольника (пиксели)
    x1: int = 0
    y1: int = 0
    x2: int = 0
    y2: int = 0

    # Флаги состояния
    enabled: bool = True
    is_main: bool = False
    processing_enabled: bool = True

    # Цепочка обработки региона
    chains: List[ChainStepData] = Field(default_factory=list)
