# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты W2-c2c: поля ``plate_*`` в схеме дисплея и вкладка Displays.

Написаны по спеке ``plans/2026-11-25_multicam-observability/tasks/W2-c2c.md`` до реализации.
Ожидаемые значения — литералы из спеки. Тесты presenter-а идут по настоящей цепочке
``DisplaysPresenter`` -> ``DisplayCatalogFromRecipe`` -> ``RecipeStoreFromManager`` ->
``RecipeManager`` (``InspectorRecipeFormatHook``) -> YAML в ``tmp_path``; итог читается из файла.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml
from pydantic import ValidationError

from multiprocess_prototype.domain.entities.display import DisplayDefinition
from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplaySpec,
    definition_to_spec,
    spec_to_definition_dict,
)

_PLATE_KEYS = ("plate_mode", "plate_after_s", "plate_text", "plate_source")


def _plate_of(obj: Any) -> tuple[Any, ...]:
    """Четвёрка полей плашки из объекта (атрибуты) или dict (ключи; нет ключа — ``<нет>``)."""
    if isinstance(obj, dict):
        return tuple(obj.get(key, "<нет>") for key in _PLATE_KEYS)
    return tuple(getattr(obj, key, "<нет>") for key in _PLATE_KEYS)


# --------------------------------------------------------------------------- #
# DisplayDefinition: схема
# --------------------------------------------------------------------------- #


def test_accepts_plate_fields() -> None:
    defn = DisplayDefinition.from_dict(
        {
            "id": "d",
            "plate_mode": "silence",
            "plate_after_s": 5,
            "plate_text": "{title}",
            "plate_source": "cam_0.camera_device",
        }
    )

    assert _plate_of(defn) == ("silence", 5, "{title}", "cam_0.camera_device")


def test_plate_fields_default_values() -> None:
    defn = DisplayDefinition.from_dict({"id": "d"})

    assert _plate_of(defn) == ("hold", 2, "", "")


@pytest.mark.parametrize("mode", ["hold", "silence", "trigger"])
def test_accepts_each_plate_mode(mode: str) -> None:
    defn = DisplayDefinition.from_dict({"id": "d", "plate_mode": mode})

    assert getattr(defn, "plate_mode", "<нет>") == mode


@pytest.mark.parametrize("seconds", [1, 600])
def test_accepts_plate_after_s_boundaries(seconds: int) -> None:
    defn = DisplayDefinition.from_dict({"id": "d", "plate_after_s": seconds})

    assert getattr(defn, "plate_after_s", "<нет>") == seconds


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plate_mode", "blink"),
        ("plate_after_s", 0),
        ("plate_after_s", 601),
        ("plate_after_s", True),
        ("plate_after_s", "5"),
        ("plate_after_s", 5.0),
    ],
    ids=["mode_blink", "after_0", "after_601", "after_bool", "after_str", "after_float"],
)
def test_rejects_bad_mode_and_range(field: str, value: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        DisplayDefinition.from_dict({"id": "d", field: value})

    msg = caught.value.errors()[0]["msg"]
    assert field in msg
    if field == "plate_mode":
        assert "blink" not in msg


# --------------------------------------------------------------------------- #
# DisplaySpec и маппинг
# --------------------------------------------------------------------------- #


def test_display_spec_plate_defaults() -> None:
    spec = DisplaySpec(display_id="d", display_name="D")

    assert _plate_of(spec) == ("hold", 2, "", "")


def test_mapping_carries_plate_fields_both_ways() -> None:
    defn = DisplayDefinition.from_dict(
        {
            "id": "d",
            "plate_mode": "trigger",
            "plate_after_s": 600,
            "plate_text": "{title}",
            "plate_source": "cam_0.camera_device",
        }
    )

    spec = definition_to_spec(defn)
    back = spec_to_definition_dict(spec)

    assert _plate_of(spec) == ("trigger", 600, "{title}", "cam_0.camera_device")
    assert _plate_of(back) == ("trigger", 600, "{title}", "cam_0.camera_device")


# --------------------------------------------------------------------------- #
# minimize: умолчания в файл не пишутся
# --------------------------------------------------------------------------- #


def test_minimize_drops_defaults() -> None:
    from multiprocess_prototype.adapters.recipe_canonical import minimize

    value = {"id": "d", "plate_mode": "hold", "plate_after_s": 2, "plate_text": "", "plate_source": ""}

    assert minimize(("displays", 0), value) == {"id": "d"}


def test_minimize_keeps_non_default_plate_values() -> None:
    from multiprocess_prototype.adapters.recipe_canonical import minimize

    value = {"id": "d", "plate_mode": "silence", "plate_after_s": 5, "plate_text": "", "plate_source": ""}

    assert minimize(("displays", 0), value) == {"id": "d", "plate_mode": "silence", "plate_after_s": 5}


# --------------------------------------------------------------------------- #
# Вкладка Displays: настоящая цепочка над YAML
# --------------------------------------------------------------------------- #

_SLUG = "demo"

_RECIPE_WITH_PLATE = (
    "name: Demo\n"
    "version: 1\n"
    "displays:\n"
    "  - id: d\n"
    "    name: D\n"
    "    plate_mode: silence\n"
    "    plate_after_s: 5\n"
    "    plate_text: '{title}'\n"
    "    plate_source: cam_0.camera_device\n"
    "blueprint:\n"
    "  processes: []\n"
    "  wires: []\n"
)

_RECIPE_WITHOUT_PLATE = (
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


def test_toggle_enabled_keeps_plate_fields(tmp_path: Path) -> None:
    presenter, view, path = _build_presenter(tmp_path, _RECIPE_WITH_PLATE)

    presenter.on_set_enabled("d", False)

    source = _displays_on_disk(path)["d"]
    # Переключение действительно дошло до файла — иначе «поля целы» ничего не значит.
    assert source.get("enabled") is False
    assert _plate_of(source) == ("silence", 5, "{title}", "cam_0.camera_device")
    view.show_error.assert_not_called()


def test_duplicate_keeps_plate_fields(tmp_path: Path) -> None:
    presenter, view, path = _build_presenter(tmp_path, _RECIPE_WITH_PLATE)

    presenter.on_duplicate("d")

    displays = _displays_on_disk(path)
    assert sorted(displays) == ["d", "d_copy"]
    assert _plate_of(displays["d_copy"]) == ("silence", 5, "{title}", "cam_0.camera_device")
    assert _plate_of(displays["d"]) == ("silence", 5, "{title}", "cam_0.camera_device")
    view.show_error.assert_not_called()


def test_duplicate_without_plate_writes_no_plate_keys(tmp_path: Path) -> None:
    """Контроль цепочки и «умолчания не пишутся»: у экрана без плашки ключи в файле не появляются."""
    presenter, view, path = _build_presenter(tmp_path, _RECIPE_WITHOUT_PLATE)

    presenter.on_duplicate("d")

    displays = _displays_on_disk(path)
    assert sorted(displays) == ["d", "d_copy"]
    assert [key for entry in displays.values() for key in entry if key.startswith("plate_")] == []
    view.show_error.assert_not_called()
