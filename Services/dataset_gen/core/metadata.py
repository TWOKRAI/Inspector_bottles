"""Метаданные классов — реэкспорт из `Services.layer_render.metadata` (Task 2.4a).

Код переехал в `layer_render`; этот модуль сохраняет старый путь импорта. Те же объекты (`is`).
"""

from __future__ import annotations

from Services.layer_render.metadata import META_FILENAMES, ClassMeta, load_meta, write_meta

__all__ = ["META_FILENAMES", "ClassMeta", "load_meta", "write_meta"]
