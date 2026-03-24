# -*- coding: utf-8 -*-
"""
Регистры обработки изображений.

Демонстрирует использование type aliases (HsvHue, HsvChannel, Pixels)
вместо повторного написания Annotated[int, FieldMeta(..., min=0, max=179)].
"""
from typing import Annotated, Any, Dict, Optional

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
    HsvHue,
    HsvChannel,
    Pixels,
)


class ProcessingRegisters(RegisterBase):
    """Регистры параметров обработки изображения."""

    # --- Кадрирование (используем type alias Pixels) ---
    crop_top: Pixels = 0
    crop_bottom: Pixels = 2160
    crop_left: Pixels = 0
    crop_right: Pixels = 3840

    # --- Управление обработкой ---
    enable_processing: Annotated[
        bool,
        FieldMeta("Включить обработку", info="Включить алгоритм обработки изображения."),
    ] = False

    show_mask: Annotated[
        bool,
        FieldMeta("Показать маску", info="Показать HSV-маску вместо исходного изображения."),
    ] = False

    show_processed: Annotated[
        bool,
        FieldMeta("Показать обработанное", info="Показать обработанное изображение в UI."),
    ] = False

    # --- Размер изображения ---
    image_width: Annotated[
        int,
        FieldMeta("Ширина изображения", info="Ширина рабочего изображения (после кадрирования).", unit="px", min=1, max=10000),
    ] = 1024

    image_height: Annotated[
        int,
        FieldMeta("Высота изображения", info="Высота рабочего изображения (после кадрирования).", unit="px", min=1, max=10000),
    ] = 780

    # --- HSV-маска (type aliases HsvHue / HsvChannel вместо повторного Annotated) ---
    hl: HsvHue = 0    # Нижняя граница Hue (0–179)
    sl: HsvChannel = 0    # Нижняя граница Saturation (0–255)
    vl: HsvChannel = 0    # Нижняя граница Value (0–255)

    hm: HsvHue = 179  # Верхняя граница Hue (0–179)
    sm: HsvChannel = 255  # Верхняя граница Saturation (0–255)
    vm: HsvChannel = 255  # Верхняя граница Value (0–255)

    # --- Режим регионов ---
    region_processor_type: Annotated[
        Optional[str],
        FieldMeta(
            "Тип процессора региона",
            info="Цветовое пространство: None (HSV), 'rgb', 'bgr', 'grayscale'.",
        ),
    ] = None

    enable_region_mode: Annotated[
        bool,
        FieldMeta("Режим регионов", info="Включить независимую обработку регионов."),
    ] = False

    region_config: Annotated[
        Optional[Dict[str, Any]],
        FieldMeta("Конфигурация регионов", info="Параметры регионов для обработки."),
    ] = None
