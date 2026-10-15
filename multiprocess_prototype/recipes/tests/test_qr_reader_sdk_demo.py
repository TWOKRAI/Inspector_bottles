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


def test_blueprint_проходит_check_загрузчика() -> None:
    """Тот же путь и та же проверка, что на старте стенда (`launch.py` → `BlueprintAssembler.assemble`).

    `validate_recipe_blueprint` зовёт `check_structure()` без реестра плагинов и молчит на текстовом
    `shape` порта; загрузчик зовёт `check()` с реестром и отклоняет такой рецепт («Wire … несовместим»).
    Путь: `load_topology_dict` → `normalize_blueprint` → `model_validate` → `infer_missing_collectors` → `check`.
    """
    from multiprocess_framework.modules.app_module import discover
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import SystemBlueprint
    from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry
    from multiprocess_prototype.backend.assembly.normalize import normalize_blueprint
    from multiprocess_prototype.backend.config.schemas import load_system_config
    from multiprocess_prototype.backend.launch import load_topology_dict

    project_root = _RECIPES_DIR.parent.parent
    discover(plugin_paths=[str(project_root / "Plugins"), str(project_root / "Services")], service_paths=[])
    # страж «ноль наблюдений»: с пустым реестром check() молча пропускает плагины и вернёт []
    for name in ("code_reader_sdk", "overlay_draw"):
        assert PluginRegistry.get(name) is not None, f"реестр не знает {name}: check() ничего бы не проверил"

    bp_dict = normalize_blueprint(load_topology_dict(_RECIPE_FILE), load_system_config())
    topology = SystemBlueprint.model_validate(bp_dict)
    topology.infer_missing_collectors()
    errors = topology.check()
    assert errors == [], "check() загрузчика отклонил рецепт:\n  " + "\n  ".join(errors)


def test_цвет_рамки_из_таблицы_рецепта_ok_зелёный_bad_красный() -> None:
    """Сквозной путь: SdkFrame -> `_overlay` с labels рецепта -> `overlay_draw` с color_table рецепта -> пиксель.

    Цвета в overlay источника нет (только group), поэтому зелёный/красный на линии может дать лишь таблица.
    Граница слоёв: Services не знает Plugins, так что тест живёт здесь, в прототипе.
    """
    from unittest.mock import MagicMock

    import numpy as np

    from Plugins.render.overlay_draw.plugin import OverlayDrawPlugin
    from Services.code_reader.plugin.sdk_plugin import _overlay
    from Services.code_reader.tests.test_sdk_reader import bad_code, code, frame

    sdk_cfg = _node("reader_sdk")["plugins"][0]
    draw_cfg = _node("draw")["plugins"][0]
    square = [[100, 100], [300, 100], [300, 300], [100, 300]]

    plugin = OverlayDrawPlugin()
    ctx = MagicMock()
    ctx.registers = None
    ctx.config = {k: v for k, v in draw_cfg.items() if k not in _SERVICE_KEYS}
    ctx.log_info = MagicMock()
    plugin.configure(ctx)

    def pixel_on_top_edge(sdk_frame) -> tuple[int, ...]:
        overlay = _overlay(sdk_frame, (1, 0, 0), sdk_cfg["labels"])
        gray = np.full((1024, 1280, 3), 90, dtype=np.uint8)
        (out,) = plugin.process([{"frame": gray, "overlay": overlay}])
        return tuple(int(v) for v in out["frame"][100, 200])

    assert pixel_on_top_edge(frame([code("QR-A", corners=square)])) == (0, 200, 0)
    assert pixel_on_top_edge(frame([bad_code(corners=square)], no_read=1)) == (0, 0, 255)


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


def test_sdk_нода_отдаёт_кадр_в_draw_а_draw_в_gui() -> None:
    """Кадр SDK-ноды идёт в draw (рамка, текст), draw — в gui; без chain_targets стенд ничего не покажет."""
    assert _node("reader_sdk")["chain_targets"] == ["draw"]
    assert _node("draw")["chain_targets"] == ["gui"]


def test_провод_и_дисплей_идут_через_draw() -> None:
    bp = _load()["blueprint"]
    assert {"source": "reader_sdk.code_reader_sdk.frame", "target": "draw.overlay_draw.frame"} in bp["wires"]
    assert bp["displays"] == [{"node_id": "draw.overlay_draw.frame", "display_id": "main"}]
    assert next(d for d in _load()["displays"] if d["id"] == "main")["format"] == "BGR"
