"""Мост к `Services.dataset_gen.core.catalog`: line_sim переиспользует `SpriteCatalog`
для эталонов классов и его же Windows-safe загрузку RGBA для одиночных изображений
(доп. слои пресета) — ничего не сканирует и не декодирует заново.

Каталог фонов dataset_gen line_sim не нужен (сцена рисует свою ленту, не композицию
"объект на фоне") — `backgrounds_dir` всегда `None`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from Services.dataset_gen.core.catalog import SpriteCatalog
from Services.dataset_gen.core.config import CatalogConfig


def load_catalog(classes_dir: str | Path) -> SpriteCatalog:
    """Загрузить каталог классов (эталоны — жадно, в память); ошибки — от `SpriteCatalog`.

    Pre: classes_dir существует и содержит >=1 листовую папку со спрайтами.
    Post: catalog.num_classes >= 1.
    """
    catalog = SpriteCatalog(CatalogConfig(classes_dir=Path(classes_dir), backgrounds_dir=None))
    catalog.load()
    return catalog


def load_image_rgba(path: str | Path) -> np.ndarray:
    """Загрузить одиночное RGBA-изображение доп. слоя пресета.

    Переиспользует `SpriteCatalog._load_sprite` (Windows-safe non-ASCII, BGRA->RGBA,
    проверка альфа-канала) — то же соглашение, что у эталонов классов, не переписывается.
    """
    return SpriteCatalog._load_sprite(Path(path))  # noqa: SLF001 — намеренное переиспользование
