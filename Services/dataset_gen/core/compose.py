"""Геометрия cut-and-paste: реэкспорт из `Services.layer_render.compose` (Task 2.1).

Функции переехали в `layer_render` (их общий дом для сцены и датасета); старый путь импорта сохранён,
объекты — те же самые (`is`). Порядок применения в пайплайне кадра: rotate_expand → crop_to_alpha →
fit_longest_side → composite (см. engine.generate_sample).
"""

from __future__ import annotations

from Services.layer_render.compose import (
    cast_contact_shadow,
    composite,
    crop_to_alpha,
    fit_longest_side,
    rotate_expand,
)

__all__ = [
    "cast_contact_shadow",
    "composite",
    "crop_to_alpha",
    "fit_longest_side",
    "rotate_expand",
]
