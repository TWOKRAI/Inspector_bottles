# -*- coding: utf-8 -*-
"""
Переиспользуемые type alias-ы на основе Annotated[T, FieldMeta(...)].

Позволяют избежать повторного определения одинаковых метаданных
в разных регистрах. Можно использовать напрямую или как базу
для конкретных полей.

Пример:

    from multiprocess_framework.refactored.modules.data_schema_module import (
        RegisterBase, Percent, Pixels, HsvHue, HsvChannel,
    )

    class ProcessingRegisters(RegisterBase):
        # Вместо повторного Annotated[int, FieldMeta(..., min=0, max=179)]
        hl: HsvHue = 0
        hm: HsvHue = 179
        sl: HsvChannel = 0
        sm: HsvChannel = 255

        crop_top: Pixels = 0

    # Для добавления description к готовому типу используй FieldMeta напрямую,
    # либо создай расширенный alias:
    from typing import Annotated, get_args
    from data_schema_module.fields import FieldMeta

    Brightness = Annotated[int, FieldMeta("Яркость", unit="%", min=0, max=100, round_k=0)]
"""
from __future__ import annotations

from typing import Annotated

from .field_meta import FieldMeta

# ---------------------------------------------------------------------------
# Числовые: диапазоны и единицы измерения
# ---------------------------------------------------------------------------

# Процент 0..100
Percent = Annotated[float, FieldMeta("Процент", unit="%", min=0.0, max=100.0, round_k=1)]

# Нормализованное значение 0..1
NormalizedFloat = Annotated[float, FieldMeta("Значение [0..1]", min=0.0, max=1.0, round_k=3)]

# Масштаб (коэффициент)
Scale = Annotated[float, FieldMeta("Масштаб", min=0.01, max=100.0, round_k=2)]

# ---------------------------------------------------------------------------
# Время
# ---------------------------------------------------------------------------

Milliseconds = Annotated[float, FieldMeta("Миллисекунды", unit="мс", min=0.0)]
Seconds = Annotated[float, FieldMeta("Секунды", unit="с", min=0.0)]

# ---------------------------------------------------------------------------
# Изображение
# ---------------------------------------------------------------------------

# Пиксели (координата или размер)
Pixels = Annotated[int, FieldMeta("Пиксели", unit="px", min=0, max=10000)]

# Масштаб изображения в UI
ImageScale = Annotated[float, FieldMeta("Масштаб изображения", min=0.1, max=4.0, transfer_k=10.0, round_k=1)]

# ---------------------------------------------------------------------------
# HSV цветовое пространство
# ---------------------------------------------------------------------------

HsvHue = Annotated[int, FieldMeta("Hue", unit="°", min=0, max=179)]
HsvChannel = Annotated[int, FieldMeta("HSV-канал", min=0, max=255)]

# ---------------------------------------------------------------------------
# Сеть
# ---------------------------------------------------------------------------

NetworkPort = Annotated[int, FieldMeta("Порт", min=1, max=65535)]

# ---------------------------------------------------------------------------
# Fps / производительность
# ---------------------------------------------------------------------------

FpsLimit = Annotated[int, FieldMeta("Ограничение FPS", unit="кадр/с", min=0, max=480)]
