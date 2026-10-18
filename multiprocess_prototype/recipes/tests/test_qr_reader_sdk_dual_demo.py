"""Тесты рецепта qr_reader_sdk_dual_demo.yaml — два считывателя ID3013 одновременно.

Ловят то, что ломается молча: два пустых или одинаковых `device_ip` (обе ноды возьмут один прибор,
вторая получит busy), перепутанные провода и дисплеи, отказ загрузчика (`SystemBlueprint.check()`).

Refs: plans/code-reader-gui.md
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from multiprocess_prototype.recipes.save import validate_recipe_blueprint

_RECIPES_DIR = Path(__file__).resolve().parent.parent
_RECIPE_FILE = _RECIPES_DIR / "qr_reader_sdk_dual_demo.yaml"
_SELFTRIGGER_FILE = _RECIPES_DIR / "qr_reader_sdk_dual_selftrigger.yaml"  # то же + запись режима съёмки в приборы
_ОБА_РЕЦЕПТА = [_RECIPE_FILE, _SELFTRIGGER_FILE]
_CHAINS = [("reader_1", "draw_1", "main"), ("reader_2", "draw_2", "second")]


def _load(recipe_file: Path = _RECIPE_FILE) -> dict:
    with open(recipe_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _node(name: str, recipe_file: Path = _RECIPE_FILE) -> dict:
    return next(p for p in _load(recipe_file)["blueprint"]["processes"] if p["process_name"] == name)


@pytest.mark.parametrize("recipe_file", _ОБА_РЕЦЕПТА, ids=lambda f: f.stem)
def test_blueprint_проходит_gate_валидатор(recipe_file: Path) -> None:
    validate_recipe_blueprint(_load(recipe_file)["blueprint"])


@pytest.mark.parametrize("recipe_file", _ОБА_РЕЦЕПТА, ids=lambda f: f.stem)
def test_blueprint_проходит_check_загрузчика(recipe_file: Path) -> None:
    """Тот же путь и та же проверка, что на старте стенда (см. test_qr_reader_sdk_demo)."""
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

    bp_dict = normalize_blueprint(load_topology_dict(recipe_file), load_system_config())
    topology = SystemBlueprint.model_validate(bp_dict)
    topology.infer_missing_collectors()
    errors = topology.check()
    assert errors == [], "check() загрузчика отклонил рецепт:\n  " + "\n  ".join(errors)


def test_движок_видит_рецепт() -> None:
    from multiprocess_framework.modules.state_store_module.core.tree_store import TreeStore
    from multiprocess_prototype.backend.state.recipes.recipe_engine import RecipeEngine

    engine = RecipeEngine(store=TreeStore(), recipes_dir=_RECIPES_DIR)
    assert "qr_reader_sdk_dual_demo" in engine.list()


def test_у_приборов_разные_непустые_device_ip() -> None:
    """Пустой device_ip = «первый найденный»: два одинаковых/пустых дают один прибор и busy на втором."""
    ips = [_node(reader)["plugins"][0]["device_ip"] for reader, _, _ in _CHAINS]
    assert all(ips), f"device_ip пустой: {ips}"
    assert len(set(ips)) == len(ips), f"device_ip совпадают: {ips}"


def test_у_приборов_разные_reader_id() -> None:
    ids = [_node(reader)["plugins"][0]["reader_id"] for reader, _, _ in _CHAINS]
    assert len(set(ids)) == len(ids), f"reader_id совпадают: {ids}"


@pytest.mark.parametrize(("reader", "draw", "display"), _CHAINS)
def test_цепочка_reader_draw_gui_и_свой_дисплей(reader: str, draw: str, display: str) -> None:
    bp = _load()["blueprint"]
    assert _node(reader)["chain_targets"] == [draw]
    assert _node(draw)["chain_targets"] == ["gui"]
    assert {"source": f"{reader}.code_reader_sdk.frame", "target": f"{draw}.overlay_draw.frame"} in bp["wires"]
    assert {"node_id": f"{draw}.overlay_draw.frame", "display_id": display} in bp["displays"]
    assert next(d for d in _load()["displays"] if d["id"] == display)["format"] == "BGR"


def test_провода_и_дисплеи_только_свои() -> None:
    """Ровно по одному проводу и дисплею на камеру: перекрёстная привязка смешала бы кадры."""
    bp = _load()["blueprint"]
    assert len(bp["wires"]) == len(_CHAINS)
    assert len(bp["displays"]) == len(_CHAINS)
    assert [d["id"] for d in _load()["displays"]] == [display for _, _, display in _CHAINS]


def test_режим_съёмки_у_обоих_читателей() -> None:
    """В рецепте qr_reader_sdk_dual_selftrigger оба прибора снимают по внутреннему таймеру 40 мс.

    Ключи рецепта — поля register плагина.

    Опечатка в ключе (`trigger_period` вместо `trigger_period_ms`) молча игнорировалась бы
    загрузчиком: прибор остался бы на аппаратном триггере. Проверяем и значения, и имена.
    """
    from Services.code_reader.plugin.sdk_registers import CodeReaderSdkRegisters

    fields = set(CodeReaderSdkRegisters.model_fields)
    служебные = {"plugin_class", "plugin_name", "category"}
    for reader, _, _ in _CHAINS:
        cfg = _node(reader, _SELFTRIGGER_FILE)["plugins"][0]
        assert cfg["trigger_mode"] == "On", reader
        assert cfg["trigger_source"] == "SelfTrigger", reader
        assert cfg["trigger_period_ms"] == 40, reader
        лишние = set(cfg) - служебные - fields
        assert not лишние, f"{reader}: ключи рецепта вне полей register: {sorted(лишние)}"


def test_основной_рецепт_не_пишет_режим_в_прибор() -> None:
    """qr_reader_sdk_dual_demo стоит в app.yaml по умолчанию: режим съёмки в камеры он писать не должен.

    Закрытие приложения убивает читателей до возврата режима, поэтому запись допустима только в
    отдельном рецепте, который запускают вручную (qr_reader_sdk_dual_selftrigger).
    """
    for reader, _, _ in _CHAINS:
        cfg = _node(reader)["plugins"][0]
        записано = {k for k in cfg if k.startswith("trigger_")}
        assert not записано, f"{reader}: основной рецепт пишет режим в прибор: {sorted(записано)}"
