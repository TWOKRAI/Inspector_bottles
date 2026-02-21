# -*- coding: utf-8 -*-
"""
Модель данных шага цепочки обработки.
"""
from pydantic import BaseModel, Field
from typing import Dict, Any


class ChainStepData(BaseModel):
    """Шаг цепочки обработки региона"""
    processor_id: str = Field(description='ID процессора (rgb, bgr, hsv, grayscale, etc.)')
    params: Dict[str, Any] = Field(default_factory=dict, description='Параметры процессора')
    enabled: bool = Field(default=True, description='Включен ли шаг обработки')
