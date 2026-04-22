# multiprocess_prototype/tests/test_recipe_manager.py
"""RecipeManager: снимок YAML ↔ model_dump_all / model_validate_all."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def _ensure_paths() -> None:
    proto = Path(__file__).resolve().parent.parent
    root = proto.parent
    mods = root / "multiprocess_framework" / "refactored" / "modules"
    for p in (str(root), str(mods)):
        if p not in sys.path:
            sys.path.insert(0, p)


_ensure_paths()

from multiprocess_prototype.managers.recipe_manager import RecipeManager
from multiprocess_prototype.registers import create_registers


def test_recipe_save_load_roundtrip():
    registers, _cm = create_registers()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "r.yaml")
        mgr = RecipeManager(data_path=path)
        mgr.save_registers_to_recipe(registers, "3")
        mgr2 = RecipeManager(data_path=path)
        assert mgr2.load_recipe_to_registers(registers, "3") is True


def test_recipe_load_migrates_legacy_crop_in_yaml():
    """Снимок с плоским legacy crop_regions загружается после migrate + validate."""
    registers, _ = create_registers()
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "legacy.yaml")
        import yaml

        payload = {
            "version": 1,
            "current_register_recipe": 0,
            "current_app_recipe": 0,
            "register_recipes": {
                "0": {
                    "camera": registers.get_register("camera").model_dump(),
                    "processor": {
                        **registers.get_register("processor").model_dump(),
                        "crop_regions": {
                            "only": {
                                "params": {"x_min": 0, "x_max": 4, "height": 2, "y_delta": 0},
                                "rect": {},
                            }
                        },
                    },
                    "renderer": registers.get_register("renderer").model_dump(),
                }
            },
            "app_recipes": {},
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(payload, f, allow_unicode=True)
        mgr = RecipeManager(data_path=path)
        assert mgr.load_recipe_to_registers(registers, "0") is True
        proc = registers.get_register("processor")
        r = proc.vision_pipeline.cameras["default"].regions["only"].rect
        assert [r.x, r.y, r.width, r.height] == [0, 0, 4, 2]


def test_recipe_manager_satisfies_protocol():
    from multiprocess_prototype.managers.recipe_manager_protocol import RecipeManagerProtocol

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "protocol.yaml")
        mgr = RecipeManager(data_path=path)
        assert isinstance(mgr, RecipeManagerProtocol)


def test_build_recipe_rows_non_empty():
    from multiprocess_prototype.frontend.widgets.recipes_widget.recipe_rows import (
        build_recipe_rows,
    )

    registers, _ = create_registers()
    rows = build_recipe_rows(registers)
    assert len(rows) >= 1
    assert "register_name" in rows[0]
    assert "field_name" in rows[0]


def test_recipe_manager_split_settings_yaml():
    """register_recipes в одном файле, app_recipes — в settings_recipes.yaml рядом."""
    registers, _ = create_registers()
    with tempfile.TemporaryDirectory() as tmp:
        main_path = os.path.join(tmp, "recipes.yaml")
        side_path = os.path.join(tmp, "settings_recipes.yaml")
        mgr = RecipeManager(data_path=main_path, app_recipes_path=side_path)
        mgr.save_registers_to_recipe(registers, "0")
        mgr.save_app_recipe_snapshot("0", {"RecipesTabConfig": {"group_title": "T"}})
        mgr2 = RecipeManager(data_path=main_path, app_recipes_path=side_path)
        assert "0" in mgr2._data.get("register_recipes", {})
        assert mgr2.load_app_recipe_snapshot("0") == {"RecipesTabConfig": {"group_title": "T"}}
        with open(main_path, "r", encoding="utf-8") as f:
            main_raw = f.read()
        assert "register_recipes" in main_raw
        assert "app_recipes" not in main_raw
        with open(side_path, "r", encoding="utf-8") as f:
            side_raw = f.read()
        assert "app_recipes" in side_raw


def test_settings_recipes_alias_loads_as_app_recipes():
    """Ключ settings_recipes в YAML читается как app_recipes."""
    with tempfile.TemporaryDirectory() as tmp:
        side_path = os.path.join(tmp, "settings_recipes.yaml")
        import yaml

        with open(side_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"version": 1, "settings_recipes": {"0": {"RecipesTabConfig": {"x": 1}}}},
                f,
            )
        main_path = os.path.join(tmp, "recipes.yaml")
        with open(main_path, "w", encoding="utf-8") as f:
            yaml.dump({"version": 1, "register_recipes": {}}, f)
        mgr = RecipeManager(data_path=main_path, app_recipes_path=side_path)
        snap = mgr.load_app_recipe_snapshot("0")
        assert snap == {"RecipesTabConfig": {"x": 1}}


def test_combined_legacy_recipes_yaml_splits_on_save():
    """Старый объединённый recipes.yaml с app_recipes внутри разносится в два файла при save."""
    registers, _ = create_registers()
    import yaml

    with tempfile.TemporaryDirectory() as tmp:
        main_path = os.path.join(tmp, "recipes.yaml")
        side_path = os.path.join(tmp, "settings_recipes.yaml")
        combined = {
            "version": 1,
            "current_register_recipe": 0,
            "current_app_recipe": 0,
            "register_recipes": {
                "0": {
                    "camera": registers.get_register("camera").model_dump(),
                    "processor": registers.get_register("processor").model_dump(),
                    "renderer": registers.get_register("renderer").model_dump(),
                }
            },
            "app_recipes": {
                "0": {"RecipesTabConfig": {"group_title": "G"}, "ProcessingTabUiConfig": {"group_color": "C"}}
            },
        }
        with open(main_path, "w", encoding="utf-8") as f:
            yaml.dump(combined, f, allow_unicode=True)
        assert not os.path.isfile(side_path)

        mgr = RecipeManager(data_path=main_path, app_recipes_path=side_path)
        assert mgr.load_app_recipe_snapshot("0")["RecipesTabConfig"]["group_title"] == "G"
        mgr.save()

        with open(main_path, "r", encoding="utf-8") as f:
            main_raw = yaml.safe_load(f)
        assert "app_recipes" not in main_raw
        assert "register_recipes" in main_raw

        assert os.path.isfile(side_path)
        with open(side_path, "r", encoding="utf-8") as f:
            side_raw = yaml.safe_load(f)
        assert side_raw["app_recipes"]["0"]["RecipesTabConfig"]["group_title"] == "G"
