# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты 2.10 (домен): поле ``run_view`` дисплея, пункты D1-D4.

Написаны по приёмочным пунктам задачи 2.10 до реализации. Ожидаемые значения — литералы.
Цепочка дублирования настоящая: ``DisplaysPresenter`` -> ``DisplayCatalogFromRecipe`` ->
``RecipeStoreFromManager`` -> ``RecipeManager`` (``InspectorRecipeFormatHook``) -> YAML в ``tmp_path``.

Запуск (из корня worktree, PYTHONPATH=корень, PYTHONUTF8=1), класс ``light``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.entities.recipe import Recipe
from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplaySpec,
    definition_to_spec,
    spec_to_definition_dict,
)

# --------------------------------------------------------------------------- #
# D1, D2: схема DisplayDefinition
# --------------------------------------------------------------------------- #


def test_d1_run_view_default_is_always() -> None:
    defn = DisplayDefinition.from_dict({"id": "d"})

    assert getattr(defn, "run_view", "<нет>") == "always"


def test_d2_running_is_accepted() -> None:
    """Контроль."""
    defn = DisplayDefinition.from_dict({"id": "d", "run_view": "running"})

    assert defn.run_view == "running"


@pytest.mark.parametrize(
    ("value", "leak"),
    [("Running", "Running"), ("", None), (1, "1"), (None, "None")],
    ids=["upper", "empty", "int", "none"],
)
def test_d2_bad_value_is_rejected_without_echo(value: Any, leak: str | None) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayDefinition.from_dict({"id": "d", "run_view": value})

    error = caught.value.errors()[0]
    assert error["loc"] == ("run_view",)
    # без этой проверки тест зелён и без поля: extra="forbid" отклоняет любой незнакомый ключ
    assert error["type"] != "extra_forbidden"
    if leak is not None:  # пустую строку «не найти в тексте» нельзя: она есть в любом
        assert leak not in error["msg"]


# --------------------------------------------------------------------------- #
# D3: круг DisplaySpec, minimize
# --------------------------------------------------------------------------- #


def test_d3_mapping_keeps_running_both_ways() -> None:
    defn = DisplayDefinition.from_dict({"id": "d", "run_view": "running"})

    spec = definition_to_spec(defn)
    back = spec_to_definition_dict(spec)

    assert getattr(spec, "run_view", "<нет>") == "running"
    assert back.get("run_view", "<нет>") == "running"


def test_d3_spec_default_is_always() -> None:
    spec = DisplaySpec(display_id="d", display_name="D")

    assert getattr(spec, "run_view", "<нет>") == "always"


def test_d3_minimize_drops_default_run_view() -> None:
    from multiprocess_prototype.adapters.recipe_canonical import minimize

    assert minimize(("displays", 0), {"id": "d", "run_view": "always"}) == {"id": "d"}


def test_d3_minimize_keeps_running() -> None:
    from multiprocess_prototype.adapters.recipe_canonical import minimize

    assert minimize(("displays", 0), {"id": "d", "run_view": "running"}) == {"id": "d", "run_view": "running"}


# --------------------------------------------------------------------------- #
# D3: on_duplicate над настоящей цепочкой и YAML
# --------------------------------------------------------------------------- #

_SLUG = "demo"

_RECIPE_RUNNING = (
    "name: Demo\n"
    "version: 1\n"
    "displays:\n"
    "  - id: d\n"
    "    name: D\n"
    "    run_view: running\n"
    "blueprint:\n"
    "  processes: []\n"
    "  wires: []\n"
)

_RECIPE_WITHOUT_KEY = (
    "name: Demo\nversion: 1\ndisplays:\n  - id: d\n    name: D\nblueprint:\n  processes: []\n  wires: []\n"
)


class _Engine:
    """Минимальный движок RecipeManager: каталог рецептов и активный slug."""

    def __init__(self, recipes_dir: Path) -> None:
        self.recipes_dir = recipes_dir

    def get_active(self) -> str | None:
        return _SLUG


def _build_presenter(recipes_dir: Path, text: str) -> tuple[Any, MagicMock, Path]:
    """Настоящий presenter над настоящим каталогом и стором; view — заглушка, пишущая вызовы."""
    from multiprocess_framework.modules.recipe import RecipeManager
    from multiprocess_prototype.adapters.catalogs.display_catalog_recipe import DisplayCatalogFromRecipe
    from multiprocess_prototype.adapters.stores.recipe_store import RecipeStoreFromManager
    from multiprocess_prototype.backend.recipe_format_hook import InspectorRecipeFormatHook
    from multiprocess_prototype.frontend.widgets.tabs.displays.presenter import DisplaysPresenter

    path = recipes_dir / f"{_SLUG}.yaml"
    path.write_text(text, encoding="utf-8")
    manager = RecipeManager(
        engine=_Engine(recipes_dir),
        state_proxy=None,
        logger=None,
        format_hook=InspectorRecipeFormatHook(),
    )
    store = RecipeStoreFromManager(recipe_manager=manager, recipe_dir=recipes_dir)
    catalog = DisplayCatalogFromRecipe(recipe_store=store, get_active_slug=lambda: _SLUG)
    view = MagicMock()
    return DisplaysPresenter(store=catalog, view=view), view, path


def _displays_on_disk(path: Path) -> dict[str, dict[str, Any]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {entry["id"]: entry for entry in document["displays"]}


def test_d3_duplicate_keeps_running(tmp_path: Path) -> None:
    presenter, view, path = _build_presenter(tmp_path, _RECIPE_RUNNING)

    presenter.on_duplicate("d")

    displays = _displays_on_disk(path)
    assert sorted(displays) == ["d", "d_copy"]
    assert displays["d_copy"].get("run_view", "<нет>") == "running"
    assert displays["d"].get("run_view", "<нет>") == "running"
    view.show_error.assert_not_called()


def test_d3_duplicate_without_key_writes_no_run_view(tmp_path: Path) -> None:
    """Контроль: умолчание в файл не пишется и после записи настоящей цепочкой."""
    presenter, view, path = _build_presenter(tmp_path, _RECIPE_WITHOUT_KEY)

    presenter.on_duplicate("d")

    displays = _displays_on_disk(path)
    assert sorted(displays) == ["d", "d_copy"]
    assert [key for entry in displays.values() for key in entry if key == "run_view"] == []
    view.show_error.assert_not_called()


# --------------------------------------------------------------------------- #
# D4: негодное значение в рецепте не отменяет загрузку
# --------------------------------------------------------------------------- #


def test_d4_bad_run_view_loads_as_always_with_one_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        recipe = Recipe.from_dict({"name": "r", "version": 3, "displays": [{"id": "a", "run_view": "Running"}]})

    assert getattr(recipe.displays[0], "run_view", "<нет>") == "always"
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, f"ожидали ровно одно WARNING: {warnings}"
    assert "run_view" in warnings[0]
    assert "Running" not in caplog.text
