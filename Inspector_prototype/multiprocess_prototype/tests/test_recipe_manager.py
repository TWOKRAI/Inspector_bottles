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


def test_build_recipe_rows_non_empty():
    from multiprocess_prototype.frontend.widgets.tabs_setting.recipes_tab.recipe_rows import (
        build_recipe_rows,
    )

    registers, _ = create_registers()
    rows = build_recipe_rows(registers)
    assert len(rows) >= 1
    assert "register_name" in rows[0]
    assert "field_name" in rows[0]
