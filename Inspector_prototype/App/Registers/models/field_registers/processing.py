# -*- coding: utf-8 -*-
"""
Регистры обработки изображений.
Поля заданы через общую схему полей регистров.
"""
from pydantic import BaseModel
from typing import Optional, Dict, Any

from multiprocess_framework.refactored.modules.data_schema_module import FieldSchema
from App.Registers.models.field_registers.data_schema import DEFAULT_FIELD_SCHEMA, RegisterMetadataHelper

field_from_schema = FieldSchema(DEFAULT_FIELD_SCHEMA)


class ProcessingRegisters(RegisterMetadataHelper, BaseModel):
    """Регистры обработки изображений"""

    crop_top: int = field_from_schema(0, description='Обрезка сверху', info='Обрезка сверху (px)', min=0, max=10000)
    crop_bottom: int = field_from_schema(2160, description='Обрезка снизу', info='Обрезка снизу (px)', min=0, max=10000)
    crop_left: int = field_from_schema(0, description='Обрезка слева', info='Обрезка слева (px)', min=0, max=10000)
    crop_right: int = field_from_schema(3840, description='Обрезка справа', info='Обрезка справа (px)', min=0, max=10000)
    enable_processing: bool = field_from_schema(False, description='Включить обработку', info='Включить обработку')
    show_mask: bool = field_from_schema(False, description='Показать маску', info='Показать маску')
    show_processed: bool = field_from_schema(False, description='Показать обработанное изображение', info='Показать обработанное изображение')
    image_width: int = field_from_schema(1024, description='Ширина изображения', info='Ширина изображения (px)', min=1, max=10000)
    image_height: int = field_from_schema(780, description='Высота изображения', info='Высота изображения (px)', min=1, max=10000)
    hl: int = field_from_schema(0, description='Hue нижний', info='Hue нижний', min=0, max=179)
    sl: int = field_from_schema(0, description='Saturation нижний', info='Saturation нижний', min=0, max=255)
    vl: int = field_from_schema(0, description='Value нижний', info='Value нижний', min=0, max=255)
    hm: int = field_from_schema(179, description='Hue верхний', info='Hue верхний', min=0, max=179)
    sm: int = field_from_schema(255, description='Saturation верхний', info='Saturation верхний', min=0, max=255)
    vm: int = field_from_schema(255, description='Value верхний', info='Value верхний', min=0, max=255)
    region_processor_type: Optional[str] = field_from_schema(None, description='Тип процессора: None (HSV), rgb, bgr, grayscale', info='Тип процессора региона')
    enable_region_mode: bool = field_from_schema(False, description='Включить режим обработки регионов', info='Включить режим обработки регионов')
    region_config: Optional[Dict[str, Any]] = field_from_schema(None, description='Конфигурация регионов для обработки', info='Конфигурация регионов')
