# -*- coding: utf-8 -*-
"""Вкладка Displays не теряет поля плашки ``plate_*`` (W2-c2c, П6).

Presenter поверх настоящих ``DisplayCatalogFromRecipe`` + ``RecipeStoreFromManager`` над YAML
в ``tmp_path``: ``FakeDisplayCatalog`` хранит ``DisplaySpec`` как есть и потери маппинга не видит.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import yaml

from multiprocess_framework.modules.recipe import RecipeManager
from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe
from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook
from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter

_RECIPE = """\
name: Demo
version: 1
displays:
  - id: d
    name: D
    plate_mode: silence
    plate_after_s: 5
    plate_text: '{title}'
    plate_source: cam_0.camera_device
blueprint:
  processes: []
  wires: []
"""

_EXPECTED = {
    "plate_mode": "silence",
    "plate_after_s": 5,
    "plate_text": "{title}",
    "plate_source": "cam_0.camera_device",
}


class _Engine:
    """Минимальный движок RecipeManager: каталог рецептов и активный slug."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir

    def get_active(self) -> str:
        return "demo"


def _presenter(recipes_dir: Path) -> tuple[DisplaysPresenter, MagicMock, Path]:
    path = recipes_dir / "demo.yaml"
    path.write_text(_RECIPE, encoding="utf-8")
    manager = RecipeManager(
        engine=_Engine(recipes_dir),
        state_proxy=None,
        logger=None,
        format_hook=InspectorRecipeFormatHook(),
    )
    store = RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)
    catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: "demo")
    view = MagicMock()
    return DisplaysPresenter(store=catalog, view=view), view, path


def _on_disk(path: Path, display_id: str) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return next(entry for entry in document["displays"] if entry["id"] == display_id)


def _plate(entry: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in entry.items() if key.startswith("plate_")}


def test_toggle_enabled_keeps_plate_fields(tmp_path: Path) -> None:
    presenter, view, path = _presenter(tmp_path)

    presenter.on_set_enabled("d", False)

    entry = _on_disk(path, "d")
    # Без этой строки тест зелен и тогда, когда переключение до файла не дошло.
    assert entry.get("enabled") is False
    assert _plate(entry) == _EXPECTED
    view.show_error.assert_not_called()


def test_duplicate_keeps_plate_fields(tmp_path: Path) -> None:
    presenter, view, path = _presenter(tmp_path)

    presenter.on_duplicate("d")

    assert _plate(_on_disk(path, "d_copy")) == _EXPECTED
    view.show_error.assert_not_called()
