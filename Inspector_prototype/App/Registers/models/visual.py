# -*- coding: utf-8 -*-
"""
Регистры визуальных настроек.
"""
from pydantic import BaseModel, Field


class VisualRegisters(BaseModel):
    """Регистры визуальных настроек"""
    image_scale: float = Field(default=0.5, description='Масштаб изображения')
