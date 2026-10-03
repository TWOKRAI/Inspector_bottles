# -*- coding: utf-8 -*-
"""Windows-safe чтение/запись изображений (non-ASCII пути): `np.fromfile` + `cv2.imdecode` / `imencode` + `tofile`.

Дом — `layer_render` (Task 2.1, перенос из `dataset_gen/core/catalog.py`; там имена остаются через импорт).
`cv2.imread`/`cv2.imwrite` не умеют non-ASCII пути на Windows — а имена классов бывают кириллицей.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def imread_unicode(path: str | Path, flags: int = cv2.IMREAD_UNCHANGED) -> np.ndarray:
    """Чтение изображения с поддержкой non-ASCII путей (Windows-safe).

    Pre:
      - файл существует и является изображением
    Post:
      - возвращён ndarray; исключение ValueError при нечитаемом файле
    """
    buf = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(buf, flags)
    if img is None:
        raise ValueError(f"Не удалось прочитать изображение: {path}")
    return img


def imwrite_unicode(path: str | Path, image_bgr: np.ndarray) -> None:
    """Запись изображения с поддержкой non-ASCII путей (формат — по суффиксу)."""
    suffix = Path(path).suffix or ".png"
    ok, buf = cv2.imencode(suffix, image_bgr)
    if not ok:
        raise ValueError(f"Не удалось закодировать изображение в {suffix}: {path}")
    buf.tofile(str(path))


def load_image_rgba(path: str | Path) -> np.ndarray:
    """Загрузить одиночное RGBA-изображение доп. слоя пресета — то же соглашение, что
    у эталонов класса (Windows-safe non-ASCII через `imread_unicode`, BGRA -> RGBA,
    обязательный альфа-канал), но через ПУБЛИЧНУЮ функцию каталога, не приватный метод.
    """
    img = imread_unicode(path, cv2.IMREAD_UNCHANGED)
    if img.ndim != 3 or img.shape[2] != 4:
        raise ValueError(f"Изображение слоя {path}: нужен альфа-канал (RGBA), получено shape={img.shape}")
    return cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
