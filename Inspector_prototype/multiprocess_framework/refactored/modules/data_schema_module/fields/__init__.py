# -*- coding: utf-8 -*-
"""
Система полей регистров: FieldMeta + FieldRouting + type aliases + RegisterBase.

Использование:

    from typing import Annotated
    from multiprocess_framework.refactored.modules.data_schema_module import (
        FieldMeta, FieldRouting, RegisterBase,
        # Готовые type aliases:
        Percent, Pixels, HsvHue, HsvChannel, Scale, Seconds,
    )

    DRAW = FieldRouting(channel="control_draw")

    class DrawRegisters(RegisterBase):
        dp: Annotated[float, FieldMeta("Разрешение", min=0.1, max=20.0, routing=DRAW)] = 1.4
        minDist: Annotated[float, FieldMeta("Мин. расстояние", routing=DRAW)] = 50.0

    class ProcessingRegisters(RegisterBase):
        hl: HsvHue = 0          # Annotated[int, FieldMeta("Hue", min=0, max=179)]
        hm: HsvHue = 179
        crop_top: Pixels = 0    # Annotated[int, FieldMeta("Пиксели", min=0, max=10000)]
"""
from .field_meta import FieldMeta
from .field_routing import FieldRouting
from .register_mixin import RegisterMixin
from .register_base import RegisterBase
from .field_types import (
    Percent,
    NormalizedFloat,
    Scale,
    Milliseconds,
    Seconds,
    Pixels,
    ImageScale,
    HsvHue,
    HsvChannel,
    NetworkPort,
    FpsLimit,
)

__all__ = [
    # Ядро
    "FieldMeta",
    "FieldRouting",
    "RegisterMixin",
    "RegisterBase",
    # Переиспользуемые type aliases
    "Percent",
    "NormalizedFloat",
    "Scale",
    "Milliseconds",
    "Seconds",
    "Pixels",
    "ImageScale",
    "HsvHue",
    "HsvChannel",
    "NetworkPort",
    "FpsLimit",
]
