"""Мост к `Services.dataset_gen.core.catalog`: line_sim переиспользует `SpriteCatalog`
для эталонов классов и его же Windows-safe загрузку RGBA для одиночных изображений
(доп. слои пресета) — ничего не сканирует и не декодирует заново.

Каталог фонов dataset_gen line_sim не нужен (сцена рисует свою ленту, не композицию
"объект на фоне") — `backgrounds_dir` всегда `None`.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from Services.dataset_gen.core.catalog import SpriteCatalog, imread_unicode
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
    """Загрузить одиночное RGBA-изображение доп. слоя пресета — то же соглашение, что
    у эталонов класса (Windows-safe non-ASCII через `imread_unicode`, BGRA -> RGBA,
    обязательный альфа-канал), но через ПУБЛИЧНУЮ функцию каталога, не приватный метод.
    """
    img = imread_unicode(path, cv2.IMREAD_UNCHANGED)
    if img.ndim != 3 or img.shape[2] != 4:
        raise ValueError(f"Изображение слоя {path}: нужен альфа-канал (RGBA), получено shape={img.shape}")
    return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
