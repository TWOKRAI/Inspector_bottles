"""Контракт конфига и комплектного пресета ru_letters_disk."""

from __future__ import annotations


import pytest

from Services.dataset_gen import PRESETS_DIR
from Services.dataset_gen.core.config import GeneratorConfig


class TestFromDict:
    def test_relative_paths_resolved_from_base_dir(self, tmp_path):
        cfg = GeneratorConfig.from_dict(
            {"catalog": {"classes_dir": "sprites", "backgrounds_dir": "bg"}},
            base_dir=tmp_path,
        )
        assert cfg.catalog.classes_dir == (tmp_path / "sprites").resolve()
        assert cfg.catalog.backgrounds_dir == (tmp_path / "bg").resolve()

    def test_defaults_are_sane(self, tmp_path):
        cfg = GeneratorConfig.from_dict({"catalog": {"classes_dir": str(tmp_path)}})
        assert cfg.output.size == (128, 128)
        assert cfg.augment.rotation.range == (0.0, 360.0)
        assert cfg.symmetry.auto_detect is True

    def test_to_dict_roundtrip(self, tmp_path):
        cfg = GeneratorConfig.from_dict({"catalog": {"classes_dir": str(tmp_path)}, "seed": 5})
        d = cfg.to_dict()
        cfg2 = GeneratorConfig.from_dict(d)
        assert cfg2.seed == 5
        assert cfg2.output.size == cfg.output.size


class TestRuLettersPreset:
    @pytest.fixture
    def preset(self) -> GeneratorConfig:
        return GeneratorConfig.from_yaml(PRESETS_DIR / "ru_letters_disk.yaml")

    def test_loads_and_paths_absolute(self, preset):
        assert preset.catalog.classes_dir.is_absolute()
        assert preset.catalog.backgrounds_dir is None  # процедурные фоны по умолчанию

    def test_task_requirements(self, preset):
        # требования задачи: 128×128, поворот 0–360, глянец и движение конвейера
        assert preset.output.size == (128, 128)
        assert preset.augment.rotation.range == (0.0, 360.0)
        assert preset.augment.glare.enabled is True
        assert preset.augment.motion_blur.enabled is True
        assert preset.symmetry.auto_detect is True

    def test_preset_is_reproducible(self, preset):
        assert preset.seed is not None


class TestSpriteToolImportable:
    def test_ru_alphabet_has_33_letters(self):
        from Services.dataset_gen.tools.make_ru_letter_sprites import RU_UPPERCASE

        assert len(RU_UPPERCASE) == 33
        assert "Ё" in RU_UPPERCASE
