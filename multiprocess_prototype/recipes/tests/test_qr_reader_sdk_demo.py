"""Тесты рецепта qr_reader_sdk_demo.yaml — валидность и совпадение с плагинами.

Ловят то, что ломается молча: blueprint проходит gate-валидатор, движок видит
рецепт, а имена классов, плагинов и параметров обеих нод (SDK и TCP) совпадают с
тем, что объявлено в `Services/code_reader/plugin/`. Опечатка в параметре иначе
всплыла бы только на живом запуске.

Refs: plans/code-reader-sdk.md
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.recipes.save import validate_recipe_blueprint

_RECIPES_DIR = Path(__file__).resolve().parent.parent
_RECIPE_FILE = _RECIPES_DIR / "qr_reader_sdk_demo.yaml"
_SERVICE_KEYS = {"plugin_class", "plugin_name", "category"}


def _load() -> dict:
    with open(_RECIPE_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _node(name: str) -> dict:
    return next(p for p in _load()["blueprint"]["processes"] if p["process_name"] == name)


def test_blueprint_проходит_gate_валидатор() -> None:
    validate_recipe_blueprint(_load()["blueprint"])


def test_движок_видит_рецепт() -> None:
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine

    engine = RecipeEngine(store=TreeStore(), recipes_dir=_RECIPES_DIR)
    assert "qr_reader_sdk_demo" in engine.list()


@pytest.mark.parametrize(
    ("node", "registers"),
    [
        ("reader_sdk", "Services.code_reader.plugin.sdk_registers.CodeReaderSdkRegisters"),
        ("reader_tcp", "Services.code_reader.plugin.registers.CodeReaderRegisters"),
    ],
)
def test_ноды_совпадают_с_плагинами(node: str, registers: str) -> None:
    pdef = _node(node)["plugins"][0]
    module_path, _, class_name = pdef["plugin_class"].rpartition(".")
    plugin_cls = getattr(importlib.import_module(module_path), class_name)
    assert plugin_cls.name == pdef["plugin_name"]
    assert plugin_cls.category == pdef["category"]

    reg_module, _, reg_name = registers.rpartition(".")
    reg_cls = getattr(importlib.import_module(reg_module), reg_name)
    assert plugin_cls.register_class is reg_cls
    unknown = set(pdef) - _SERVICE_KEYS - set(reg_cls.model_fields)
    assert not unknown, f"{node}: в рецепте параметры, которых нет в register: {sorted(unknown)}"


def test_sdk_нода_отдаёт_кадр_в_gui() -> None:
    """Кадр SDK-ноды должен доезжать до gui — без chain_targets стенд ничего не покажет."""
    assert _node("reader_sdk")["chain_targets"] == ["gui"]
