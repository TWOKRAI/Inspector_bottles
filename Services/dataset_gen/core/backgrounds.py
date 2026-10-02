"""Процедурные фоны — реэкспорт из `Services.layer_render.procedural_backgrounds` (Task 2.4a).

Код переехал в `layer_render`; этот модуль сохраняет старый путь импорта. Те же объекты (`is`).
`_GENERATORS` реэкспортируется намеренно: его читает `dataset_gen/tests/test_backgrounds.py`.
"""

from __future__ import annotations

from Services.layer_render.procedural_backgrounds import (
    _GENERATORS,
    brushed_metal_bg,
    conveyor_belt_bg,
    gradient_bg,
    procedural_background,
    speckled_bg,
)

__all__ = [
    "_GENERATORS",
    "brushed_metal_bg",
    "conveyor_belt_bg",
    "gradient_bg",
    "procedural_background",
    "speckled_bg",
]
