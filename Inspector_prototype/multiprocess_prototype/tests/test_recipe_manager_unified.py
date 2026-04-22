# multiprocess_prototype/tests/test_recipe_manager_unified.py
"""Тесты RecipeManager: новый YAML (register_recipes + app_recipes) и legacy."""

from __future__ import annotations

import os
import tempfile

import yaml

from multiprocess_prototype.managers.recipe_manager import RecipeManager


class _FakeRegisters:
    def model_dump_all(self) -> dict:
        return {"cam": {"fps": 30}}

    def model_validate_all(self, data: dict, strict: bool = False) -> None:
        assert "cam" in data


def test_recipe_manager_legacy_load_maps_to_register_recipes():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "r.yaml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"current_recipe": 2, "recipes": {"0": {"cam": {"fps": 5}}}},
                f,
            )
        m = RecipeManager(data_path=path)
        assert m.get_current_register_recipe_number() == 2
        assert m._data["register_recipes"]["0"] == {"cam": {"fps": 5}}
        fake = _FakeRegisters()
        assert m.load_recipe_to_registers(fake, "0") is True


def test_recipe_manager_save_new_format_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "r.yaml")
        m = RecipeManager(data_path=path)
        m.save_registers_to_recipe(_FakeRegisters(), "1")
        app_snap = {
            "RecipesTabConfig": {"group_title": "Тест"},
            "ProcessingTabUiConfig": {"group_color": "Цвет"},
        }
        m.save_app_recipe_snapshot("1", app_snap)
        m.set_current_app_recipe_number(1)

        m2 = RecipeManager(data_path=path)
        assert m2.get_current_app_recipe_number() == 1
        loaded = m2.load_app_recipe_snapshot("1")
        assert loaded == app_snap

        with open(path, "r", encoding="utf-8") as f:
            raw_main = yaml.safe_load(f)
        assert "register_recipes" in raw_main
        assert "app_recipes" not in raw_main
        side = os.path.join(os.path.dirname(path), "settings_recipes.yaml")
        with open(side, "r", encoding="utf-8") as f:
            raw_side = yaml.safe_load(f)
        assert "app_recipes" in raw_side
