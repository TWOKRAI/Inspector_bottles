# -*- coding: utf-8 -*-
"""
Регистры обработки изображений.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class ProcessingRegisters(BaseModel):
    """Регистры обработки изображений"""
    crop_top: int = Field(default=0, description='Обрезка сверху')
    crop_bottom: int = Field(default=2160, description='Обрезка снизу')
    crop_left: int = Field(default=0, description='Обрезка слева')
    crop_right: int = Field(default=3840, description='Обрезка справа')
    enable_processing: bool = Field(default=False, description='Включить обработку')
    show_mask: bool = Field(default=False, description='Показать маску')
    show_processed: bool = Field(default=False, description='Показать обработанное изображение')
    image_width: int = Field(default=1024, description='Ширина изображения')
    image_height: int = Field(default=780, description='Высота изображения')
    hl: int = Field(default=0, description='Hue нижний')
    sl: int = Field(default=0, description='Saturation нижний')
    vl: int = Field(default=0, description='Value нижний')
    hm: int = Field(default=179, description='Hue верхний')
    sm: int = Field(default=255, description='Saturation верхний')
    vm: int = Field(default=255, description='Value верхний')
    region_processor_type: Optional[str] = Field(default=None, description='Тип процессора: None (HSV), rgb, bgr, grayscale')
    enable_region_mode: bool = Field(default=False, description='Включить режим обработки регионов')
    region_config: Optional[Dict[str, Any]] = Field(default=None, description='Конфигурация регионов для обработки')
