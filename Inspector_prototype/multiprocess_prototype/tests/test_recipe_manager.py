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
        assert "default" in proc.crop_regions
        assert proc.crop_regions["default"]["only"] == [0, 0, 4, 2]


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
