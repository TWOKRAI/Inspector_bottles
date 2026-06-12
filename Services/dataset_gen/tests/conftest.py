"""Фикстуры: синтетические спрайты с известной симметрией + временный каталог.

Спрайты строятся кодом (без бинарных файлов в репозитории):
  disk — белый круг → полная симметрия (full);
  bar  — прямоугольный брусок 4:1 → симметрия 180°;
  lshape — Г-образная фигура → без симметрии (none).
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from PIL import Image

from Services.dataset_gen.core.config import GeneratorConfig


def _blank(size: int) -> np.ndarray:
    return np.zeros((size, size, 4), dtype=np.uint8)


def make_disk_sprite(size: int = 96) -> np.ndarray:
    # центр строго в (size-1)/2 — иначе полупиксельный сдвиг ломает симметрию
    sprite = _blank(size)
    c = (size - 1) / 2.0
    yy, xx = np.ogrid[:size, :size]
    mask = (xx - c) ** 2 + (yy - c) ** 2 <= (size / 2.0 - 4) ** 2
    sprite[mask] = (255, 255, 255, 255)
    return sprite


def make_bar_sprite(size: int = 96) -> np.ndarray:
    # прямоугольник с чётными отступами: центр совпадает с центром спрайта
    sprite = _blank(size)
    h = size // 8
    sprite[size // 2 - h : size // 2 + h, 6 : size - 6] = (40, 200, 60, 255)
    return sprite


def make_lshape_sprite(size: int = 96) -> np.ndarray:
    sprite = _blank(size)
    cv2.rectangle(sprite, (10, 10), (30, size - 10), (220, 60, 60, 255), -1)
    cv2.rectangle(sprite, (10, size - 34), (size - 10, size - 10), (220, 60, 60, 255), -1)
    return sprite


@pytest.fixture
def disk_sprite() -> np.ndarray:
    return make_disk_sprite()


@pytest.fixture
def bar_sprite() -> np.ndarray:
    return make_bar_sprite()


@pytest.fixture
def lshape_sprite() -> np.ndarray:
    return make_lshape_sprite()


@pytest.fixture
def catalog_dir(tmp_path):
    """Каталог классов: disk / bar / lshape (по одному эталону) + 2 фона."""
    classes = tmp_path / "classes"
    for name, sprite in (
        ("bar", make_bar_sprite()),
        ("disk", make_disk_sprite()),
        ("lshape", make_lshape_sprite()),
    ):
        d = classes / name
        d.mkdir(parents=True)
        Image.fromarray(sprite).save(d / "base.png")

    backgrounds = tmp_path / "backgrounds"
    backgrounds.mkdir()
    rng = np.random.default_rng(7)
    for i in range(2):
        bg = rng.integers(0, 255, size=(200, 260, 3), dtype=np.uint8)
        Image.fromarray(bg).save(backgrounds / f"bg{i}.png")
    return tmp_path


@pytest.fixture
def base_config(catalog_dir) -> GeneratorConfig:
    """Конфиг с детерминированным seed поверх временного каталога."""
    return GeneratorConfig.from_dict(
        {
            "catalog": {
                "classes_dir": str(catalog_dir / "classes"),
                "backgrounds_dir": str(catalog_dir / "backgrounds"),
            },
            "output": {"size": [96, 96], "frames_per_class": 4},
            "seed": 123,
        }
    )
