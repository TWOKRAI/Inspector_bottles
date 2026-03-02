# -*- coding: utf-8 -*-
"""
Регистры параметров детектора кругов (cv2.HoughCircles).

Демонстрирует использование FieldRouting: один объект DRAW_ROUTING
вместо повторения routing={"channel": "control_draw"} в каждом поле.
"""
from typing import Annotated

from multiprocess_framework.refactored.modules.data_schema_module import (
    FieldMeta,
    FieldRouting,
    RegisterBase,
)

# Единый объект маршрутизации для всех полей этого регистра
DRAW_ROUTING = FieldRouting(channel="control_draw")


class DrawRegisters(RegisterBase):
    """Регистры параметров алгоритма детектора кругов (HoughCircles)."""

    # Флаг включения рисования кругов на изображении
    draw: bool = True

    dp: Annotated[
        float,
        FieldMeta(
            "Обратное разрешение аккумулятора",
            info="Отношение разрешения аккумулятора к разрешению входного изображения. "
                 "Чем меньше — тем точнее, но медленнее.",
            info_i18n={
                "ru": "Обратное разрешение аккумулятора Hough",
                "en": "Inverse ratio of accumulator resolution",
                "de": "Inverses Verhältnis der Akkumulator-Auflösung",
            },
            max=20.0,
            min=0.1,
            transfer_k=0.1,
            round_k=1,
            min_access=1,
            routing=DRAW_ROUTING,
        ),
    ] = 1.4

    minDist: Annotated[
        float,
        FieldMeta(
            "Минимальное расстояние между центрами кругов",
            info="Минимальное расстояние между центрами обнаруженных кругов (в пикселях).",
            unit="px",
            min=0.0,
            max=1000.0,
            routing=DRAW_ROUTING,
        ),
    ] = 50.0

    param1: Annotated[
        float,
        FieldMeta(
            "Верхний порог Canny",
            info="Верхний порог детектора Canny для обнаружения краёв.",
            min=0.0,
            max=200.0,
            routing=DRAW_ROUTING,
        ),
    ] = 100.0

    param2: Annotated[
        float,
        FieldMeta(
            "Порог аккумулятора",
            info="Порог для центров кругов в аккумуляторе. "
                 "Меньшее значение — больше ложных срабатываний.",
            min=0.0,
            max=200.0,
            routing=DRAW_ROUTING,
        ),
    ] = 30.0

    minRadius: Annotated[
        float,
        FieldMeta(
            "Минимальный радиус круга",
            info="Минимальный радиус искомых кругов (в пикселях). 0 — не ограничено.",
            unit="px",
            min=0.0,
            max=1000.0,
            routing=DRAW_ROUTING,
        ),
    ] = 0.0

    maxRadius: Annotated[
        float,
        FieldMeta(
            "Максимальный радиус круга",
            info="Максимальный радиус искомых кругов (в пикселях). 0 — не ограничено.",
            unit="px",
            min=0.0,
            max=1000.0,
            routing=DRAW_ROUTING,
        ),
    ] = 0.0
