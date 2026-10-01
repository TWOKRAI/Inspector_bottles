"""Тесты рецепта qr_reader_demo.yaml — валидность и совпадение с плагином.

Проверяют то, что ломается молча: рецепт есть на диске, его blueprint проходит
gate-валидатор (`validate_recipe_blueprint`), движок его видит, а имена ноды,
класса плагина и его параметров совпадают с тем, что реально объявлено в
`Services/code_reader/plugin/`. Опечатка в `plugin_class` или в имени параметра
иначе всплыла бы только на живом запуске.

Refs: plans/qr-code-reader.md
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_prototype.recipes.save import validate_recipe_blueprint

_RECIPES_DIR = Path(__file__).resolve().parent.parent
_RECIPE_FILE = _RECIPES_DIR / "qr_reader_demo.yaml"


def _load() -> dict:
    with open(_RECIPE_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_рецепт_есть_на_диске() -> None:
    assert _RECIPE_FILE.exists()


def test_blueprint_проходит_gate_валидатор() -> None:
    validate_recipe_blueprint(_load()["blueprint"])


def test_движок_видит_рецепт() -> None:
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine

    engine = RecipeEngine(store=TreeStore(), recipes_dir=_RECIPES_DIR)
    assert "qr_reader_demo" in engine.list()


def test_класс_плагина_импортируется_и_это_тот_же_плагин() -> None:
    import importlib

    node = _load()["blueprint"]["processes"][1]
    pdef = node["plugins"][0]
    module_path, _, class_name = pdef["plugin_class"].rpartition(".")
    plugin_cls = getattr(importlib.import_module(module_path), class_name)
    assert plugin_cls.name == pdef["plugin_name"]
    assert plugin_cls.category == pdef["category"]


def test_параметры_рецепта_существуют_в_register_плагина() -> None:
    from Services.code_reader.plugin.registers import CodeReaderRegisters

    pdef = _load()["blueprint"]["processes"][1]["plugins"][0]
    service_keys = {"plugin_class", "plugin_name", "category"}
    unknown = set(pdef) - service_keys - set(CodeReaderRegisters.model_fields)
    assert not unknown, f"в рецепте параметры, которых нет в register: {sorted(unknown)}"


def test_порт_приёма_совпадает_с_подсказкой_в_шапке() -> None:
    """Комментарий про reader_sim --port должен называть тот же порт, что нода."""
    text = _RECIPE_FILE.read_text(encoding="utf-8")
    port = _load()["blueprint"]["processes"][1]["plugins"][0]["port"]
    assert f"--port {port}" in text
