"""Каталог классов и фонов — реэкспорт из `Services.layer_render.catalog` (Task 2.4a).

Код переехал в `layer_render`; этот модуль сохраняет старый путь импорта. Те же объекты (`is`).
`imread_unicode`/`imwrite_unicode` реэкспортируются из `Services.layer_render.io` (Task 2.1).
"""

from __future__ import annotations

from Services.layer_render.catalog import BACKGROUND_SUFFIXES, SPRITE_SUFFIXES, ClassEntry, SpriteCatalog
from Services.layer_render.io import imread_unicode, imwrite_unicode

__all__ = [
    "BACKGROUND_SUFFIXES",
    "SPRITE_SUFFIXES",
    "ClassEntry",
    "SpriteCatalog",
    "imread_unicode",
    "imwrite_unicode",
]
