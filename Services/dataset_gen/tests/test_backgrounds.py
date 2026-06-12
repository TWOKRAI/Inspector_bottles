"""Контракт фонов: процедурные текстуры + загрузка фото из папки (рекурсивно)."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from Services.dataset_gen.core.backgrounds import (
    _GENERATORS,
    brushed_metal_bg,
    conveyor_belt_bg,
    gradient_bg,
    procedural_background,
    speckled_bg,
)
from Services.dataset_gen.core.catalog import SpriteCatalog
from Services.dataset_gen.core.config import CatalogConfig

ALL = (gradient_bg, brushed_metal_bg, conveyor_belt_bg, speckled_bg)


class TestEachGenerator:
    @pytest.mark.parametrize("gen", ALL)
    def test_shape_and_dtype(self, gen):
        out = gen(np.random.default_rng(0), (64, 80))
        assert out.shape == (64, 80, 3)
        assert out.dtype == np.uint8

    @pytest.mark.parametrize("gen", ALL)
    def test_deterministic_by_seed(self, gen):
        a = gen(np.random.default_rng(5), (48, 48))
        b = gen(np.random.default_rng(5), (48, 48))
        assert (a == b).all()

    @pytest.mark.parametrize("gen", ALL)
    def test_not_flat(self, gen):
        # фон должен иметь фактуру, а не быть однотонной заливкой
        out = gen(np.random.default_rng(1), (96, 96))
        assert out.std() > 2.0


class TestDispatcher:
    def test_registry_covers_all(self):
        assert set(_GENERATORS) == set(ALL)

    def test_picks_varied_types(self):
        # на серии сидов выбираются разные генераторы — есть разнообразие
        rng = np.random.default_rng(0)
        results = [procedural_background(rng, (32, 32)).mean() for _ in range(40)]
        assert len(set(np.round(results, 1))) > 5


def _make_class_dir(tmp_path):
    """Минимальный каталог классов: одна подпапка-класс с RGBA-спрайтом."""
    classes = tmp_path / "classes"
    d = classes / "A"
    d.mkdir(parents=True)
    sprite = np.zeros((40, 40, 4), dtype=np.uint8)
    sprite[10:30, 10:30] = (255, 255, 255, 255)
    Image.fromarray(sprite).save(d / "base.png")
    return classes


class TestBackgroundFolderLoading:
    def test_photos_loaded_from_nested_subfolders(self, tmp_path):
        # фоны разложены по подпапкам-категориям — должны грузиться все
        classes = _make_class_dir(tmp_path)
        bg = tmp_path / "backgrounds"
        for category in ("belt", "tray"):
            (bg / category).mkdir(parents=True)
            color = np.full((50, 60, 3), 120, dtype=np.uint8)
            Image.fromarray(color).save(bg / category / "shot.png")

        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes, backgrounds_dir=bg))
        catalog.load()
        out = catalog.get_background(np.random.default_rng(0), (32, 32))
        assert out.shape == (32, 32, 3)

    def test_procedural_fallback_when_no_dir(self, tmp_path):
        classes = _make_class_dir(tmp_path)
        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes, backgrounds_dir=None))
        catalog.load()
        out = catalog.get_background(np.random.default_rng(0), (32, 32))
        assert out.shape == (32, 32, 3)


class TestClassMetadataIgnored:
    def test_service_folders_skipped(self, tmp_path):
        # рядом с классами лежат метаданные/служебные папки — не считаются классами
        classes = _make_class_dir(tmp_path)
        (classes / "_meta").mkdir()
        (classes / "_meta" / "notes.txt").write_text("info", encoding="utf-8")
        (classes / ".cache").mkdir()
        (classes / "labels.yaml").write_text("k: v", encoding="utf-8")

        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes))
        catalog.load()
        assert catalog.class_names == ["A"]
