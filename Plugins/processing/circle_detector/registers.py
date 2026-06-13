"""CircleDetectorRegisters — все параметры circle_detector плагина.

V3_MY_PURE: register = единый источник параметров + FieldMeta.
Plugin всегда работает через self._reg (managed или локальный).

Универсальная обёртка над cv2.HoughCircles с выбором режима детектора
(классический HOUGH_GRADIENT и точный HOUGH_GRADIENT_ALT, OpenCV ≥ 4.3)
и настраиваемым препроцессингом (метод и сила сглаживания).
"""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.process_module.plugins import register_schema
from multiprocess_framework.modules.process_module.plugins import FieldMeta
from multiprocess_framework.modules.process_module.plugins import SchemaBase


# Режим детектора Хафа:
#   gradient     — cv2.HOUGH_GRADIENT, классический (param2 = порог аккумулятора)
#   gradient_alt — cv2.HOUGH_GRADIENT_ALT, точнее (param2 = «кругловатость» 0.0–1.0)
DetectMode = Literal["gradient", "gradient_alt"]

# Метод предварительного сглаживания перед детекцией:
#   median   — медианный фильтр (хорош против соли-перца)
#   gaussian — гауссово размытие (мягкое сглаживание)
#   none     — без сглаживания (для уже чистых кадров)
BlurMethod = Literal["median", "gaussian", "none"]


@register_schema("CircleDetectorRegistersV1")
class CircleDetectorRegisters(SchemaBase):
    """Все параметры circle_detector — режим, препроцессинг, HoughCircles, отрисовка."""

    # --- Источник изображения ---
    input_key: Annotated[
        str,
        FieldMeta(
            "Input Key",
            info="Ключ item: 'frame' (кадр) или 'mask' (маска hsv_mask — меньше ложных)",
        ),
    ] = "frame"
    keep_mask: Annotated[
        bool,
        FieldMeta(
            "Keep Mask",
            info="Не дропать маску после детекции (нужно display-ветке, напр. показать маску на дисплее)",
        ),
    ] = False

    # --- Режим детектора ---
    mode: Annotated[
        DetectMode,
        FieldMeta(
            "Detect Mode",
            info=(
                "gradient — классический HOUGH_GRADIENT (param2 = порог аккумулятора); "
                "gradient_alt — точный HOUGH_GRADIENT_ALT (param2 = кругловатость 0.0–1.0)"
            ),
            widget="combo",
        ),
    ] = "gradient"

    # --- Препроцессинг ---
    blur_method: Annotated[
        BlurMethod,
        FieldMeta(
            "Blur Method",
            info="Сглаживание перед детекцией: median / gaussian / none",
            widget="combo",
        ),
    ] = "median"
    blur_ksize: Annotated[
        int,
        FieldMeta(
            "Blur Kernel",
            info="Размер ядра сглаживания (нечётный; будет приведён к нечётному)",
            min=1,
            max=31,
        ),
    ] = 5

    # --- Параметры HoughCircles ---
    dp: Annotated[
        float,
        FieldMeta(
            "dp (inverse ratio)",
            info="Обратное отношение разрешения аккумулятора (1.0 = как у кадра, 2.0 = вдвое грубее)",
            min=1.0,
            max=4.0,
            transfer_k=10.0,
            round_k=1,
        ),
    ] = 1.2
    min_dist: Annotated[
        int,
        FieldMeta(
            "Min Distance",
            info="Минимальное расстояние между центрами окружностей (px)",
            min=1,
            max=2000,
            unit="px",
        ),
    ] = 20
    param1: Annotated[
        int,
        FieldMeta(
            "Param1 (Canny high)",
            info="Верхний порог Canny для границ (нижний = param1/2)",
            min=1,
            max=500,
        ),
    ] = 100
    param2: Annotated[
        float,
        FieldMeta(
            "Param2",
            info=(
                "gradient: порог аккумулятора (меньше → больше ложных кругов); "
                "gradient_alt: кругловатость 0.0–1.0 (≈0.9 строго)"
            ),
            min=0.0,
            max=300.0,
            transfer_k=10.0,
            round_k=1,
        ),
    ] = 30.0
    min_radius: Annotated[
        int,
        FieldMeta(
            "Min Radius",
            info="Минимальный радиус окружности (px, 0 = без нижней границы)",
            min=0,
            max=2000,
            unit="px",
        ),
    ] = 0
    max_radius: Annotated[
        int,
        FieldMeta(
            "Max Radius",
            info="Максимальный радиус (px, 0 = без верхней границы)",
            min=0,
            max=2000,
            unit="px",
        ),
    ] = 0

    # --- Отрисовка ---
    draw_circles: Annotated[
        bool,
        FieldMeta(
            "Draw Circles",
            info="Рисовать найденные окружности и центры на кадре",
        ),
    ] = True
    circle_color_bgr: Annotated[
        list[int],
        FieldMeta(
            "Circle Color BGR",
            info="Цвет окружностей в формате BGR",
            widget="color3",
        ),
    ] = [0, 255, 0]
    circle_thickness: Annotated[
        int,
        FieldMeta(
            "Circle Thickness",
            info="Толщина линии окружности (px)",
            min=1,
            max=20,
        ),
    ] = 2
    draw_center: Annotated[
        bool,
        FieldMeta(
            "Draw Center",
            info="Отмечать центр найденной окружности точкой",
        ),
    ] = True
