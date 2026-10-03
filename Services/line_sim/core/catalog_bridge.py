"""Мост к каталогу классов — реэкспорт из `Services.layer_render` (Task 2.4b).

`load_catalog` живёт в `Services.layer_render.catalog`, `load_image_rgba` — в `Services.layer_render.io`.
Те же объекты (`is`).
"""

from __future__ import annotations

from Services.layer_render.catalog import load_catalog
from Services.layer_render.io import load_image_rgba

__all__ = ["load_catalog", "load_image_rgba"]
