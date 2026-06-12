"""Контракт метаданных классов: meta.yaml, наследование, иерархия подклассов."""

from __future__ import annotations

import numpy as np
import pytest
import yaml
from PIL import Image

from Services.dataset_gen.core.catalog import SpriteCatalog
from Services.dataset_gen.core.config import CatalogConfig, GeneratorConfig
from Services.dataset_gen.core.engine import DatasetEngine
from Services.dataset_gen.core.metadata import ClassMeta, load_meta


def _sprite(size: int = 40) -> np.ndarray:
    s = np.zeros((size, size, 4), dtype=np.uint8)
    s[8:32, 8:24] = (255, 255, 255, 255)  # несимметричный блок
    return s


def _make_class(directory, meta: dict | None = None):
    directory.mkdir(parents=True, exist_ok=True)
    Image.fromarray(_sprite()).save(directory / "base.png")
    if meta is not None:
        (directory / "meta.yaml").write_text(yaml.safe_dump(meta, allow_unicode=True), encoding="utf-8")


class TestLoadMeta:
    def test_missing_file_gives_empty_meta(self, tmp_path):
        assert load_meta(tmp_path).model_dump() == ClassMeta().model_dump()

    def test_known_and_extra_fields(self, tmp_path):
        (tmp_path / "meta.yaml").write_text("display_name: Буква А\nsymmetry: none\nartikul: A-001\n", encoding="utf-8")
        meta = load_meta(tmp_path)
        assert meta.display_name == "Буква А"
        assert meta.symmetry == "none"
        assert meta.extra == {"artikul": "A-001"}

    def test_json_meta_supported(self, tmp_path):
        (tmp_path / "meta.json").write_text('{"display_name": "X"}', encoding="utf-8")
        assert load_meta(tmp_path).display_name == "X"


class TestMerge:
    def test_child_overrides_parent(self):
        parent = ClassMeta(display_name="группа", symmetry="full", tags=["g"])
        child = ClassMeta(symmetry="none", tags=["c"])
        merged = parent.merged_with_child(child)
        assert merged.symmetry == "none"  # ребёнок переопределил
        assert merged.display_name == "группа"  # унаследовано
        assert merged.tags == ["c"]

    def test_extra_merged(self):
        parent = ClassMeta(line="L1")
        child = ClassMeta(station="S2")
        merged = parent.merged_with_child(child)
        assert merged.extra == {"line": "L1", "station": "S2"}


class TestCatalogMetadata:
    def test_meta_attached_to_class(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "A", {"display_name": "Буква А", "tags": ["letter"]})
        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes))
        catalog.load()
        assert catalog.entry(0).meta.display_name == "Буква А"
        assert catalog.entry(0).display_name == "Буква А"

    def test_inherited_meta_from_group(self, tmp_path):
        # meta.yaml в папке-группе наследуется подклассами
        classes = tmp_path / "classes"
        group = classes / "letters"
        group.mkdir(parents=True)
        (group / "meta.yaml").write_text("line: conveyor-1\n", encoding="utf-8")
        _make_class(group / "A", {"display_name": "А"})
        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes))
        catalog.load()
        assert catalog.entry(0).meta.extra.get("line") == "conveyor-1"


class TestHierarchy:
    def test_leaf_folders_are_classes(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "letters" / "vowels" / "А")
        _make_class(classes / "letters" / "consonants" / "Б")
        _make_class(classes / "digits" / "1")
        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes))
        catalog.load()
        # имена = листовые папки; путь хранит иерархию
        assert set(catalog.class_names) == {"А", "Б", "1"}
        paths = {e.qualified_name for e in catalog.classes}
        assert paths == {"letters/vowels/А", "letters/consonants/Б", "digits/1"}

    def test_duplicate_leaf_names_raise(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "groupA" / "X")
        _make_class(classes / "groupB" / "X")
        catalog = SpriteCatalog(CatalogConfig(classes_dir=classes))
        with pytest.raises(ValueError, match="Конфликт имён"):
            catalog.load()


class TestEngineUsesMeta:
    def test_meta_symmetry_overrides_detector(self, tmp_path):
        classes = tmp_path / "classes"
        # несимметричный спрайт, но meta объявляет full → должно победить детектор
        _make_class(classes / "A", {"symmetry": "full"})
        cfg = GeneratorConfig.from_dict({"catalog": {"classes_dir": str(classes)}})
        engine = DatasetEngine(cfg)
        assert engine.symmetry_map["A"] == "full"

    def test_global_override_beats_meta(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "A", {"symmetry": "full"})
        cfg = GeneratorConfig.from_dict(
            {"catalog": {"classes_dir": str(classes)}, "symmetry": {"overrides": {"A": "none"}}}
        )
        engine = DatasetEngine(cfg)
        assert engine.symmetry_map["A"] == "none"

    def test_class_path_in_label(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "letters" / "А")
        cfg = GeneratorConfig.from_dict({"catalog": {"classes_dir": str(classes)}, "seed": 1})
        engine = DatasetEngine(cfg)
        _, label = engine.generate_sample(0)
        assert label.class_path == "letters/А"
        assert label.class_name == "А"

    def test_class_registry_shape(self, tmp_path):
        classes = tmp_path / "classes"
        _make_class(classes / "A", {"display_name": "Буква А", "artikul": "A-1"})
        cfg = GeneratorConfig.from_dict({"catalog": {"classes_dir": str(classes)}})
        engine = DatasetEngine(cfg)
        reg = engine.class_registry
        assert reg[0]["name"] == "A"
        assert reg[0]["display_name"] == "Буква А"
        assert reg[0]["meta"]["artikul"] == "A-1"
        assert reg[0]["sprite_count"] == 1
